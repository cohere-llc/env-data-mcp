"""Sentinel-5P TROPOMI L2 offline adapter — anonymous S3 reader.

Data source: ``s3://meeo-s5p/OFFL/``
Coverage: Global, July 2018–present (orbit-granule HDF5/NetCDF4 files)
Auth required: No (anonymous S3 access, ``--no-sign-request``)
License: ESA Copernicus Open Access — attribution required

Supported products
------------------
CO  → carbonmonoxide_total_column          (mol m⁻²)
NO2 → nitrogendioxide_tropospheric_column  (mol m⁻²)
CH4 → methane_mixing_ratio_bias_corrected  (ppb)

Query strategy
--------------
Sentinel-5P makes ~14 polar-orbit passes per day; each granule covers a
~2 700 km swath.  For a point query we:

1. List the NC granule files for the requested date from S3.
2. For each granule open the file with h5py and read *only* the latitude
   and longitude arrays (precise HTTP byte-range requests via s3fs with
   ``cache_type='none'``).
3. Quickly check whether the target lat/lon falls inside the granule swath
   by comparing against the array bounding box (no pixel-level search).
4. For matching granules, load qa_value and the product variable, find
   the nearest pixel (argmin over flattened distance array) and return the
   pixel's value if the QA flag passes.
5. Return one record per matching granule; callers can aggregate if needed.

h5py is used directly rather than xarray+h5netcdf because h5netcdf's
file-open traversal issues many scattered HTTP requests, making it ~10×
slower per granule for remote HDF5 files.

For a bbox query the same granule-selection logic applies, but we return
the spatial mean of all QA-passing pixels whose centroids fall inside the
bbox.
"""

from __future__ import annotations

import time
from typing import Any

import h5py
import numpy as np
import s3fs

from env_data_mcp.helpers import bbox_centroid, build_meta, clamp_bbox, parse_date
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# License and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "Contains modified Copernicus Sentinel data. ESA Copernicus Open Access.",
    "license_url": "https://sentinel.esa.int/web/sentinel/sentinel-data-access/sentinel-products/license",
    "citation": (
        "Contains modified Copernicus Sentinel data [year]. "
        "Processed by ESA and the Copernicus Atmosphere Monitoring Service (CAMS)."
    ),
}

_BUCKET = "meeo-s5p"
_PROCESSING_MODE = "OFFL"  # Offline reprocessed; most reliable coverage

# Map short product name → S3 folder suffix and primary variable name.
_PRODUCTS: dict[str, dict[str, str]] = {
    "CO": {
        "folder": "L2__CO____",
        "variable": "carbonmonoxide_total_column",
        "units": "mol m-2",
        "description": "Carbon monoxide total column retrieved from TROPOMI",
        "valid_range": "0 to 0.5",
    },
    "NO2": {
        "folder": "L2__NO2___",
        "variable": "nitrogendioxide_tropospheric_column",
        "units": "mol m-2",
        "description": "Tropospheric nitrogen dioxide vertical column retrieved from TROPOMI",
        "valid_range": "-1e-5 to 1e-3",
    },
    "CH4": {
        "folder": "L2__CH4___",
        "variable": "methane_mixing_ratio_bias_corrected",
        "units": "ppb",
        "description": "Bias-corrected methane dry-air column-averaged mixing ratio",
        "valid_range": "1600 to 2200",
    },
}

VARIABLE_INFO: dict[str, dict[str, str]] = {
    p: {
        "description": info["description"],
        "units": info["units"],
        "valid_range": info["valid_range"],
    }
    for p, info in _PRODUCTS.items()
}

# QA threshold — only pixels with qa_value >= this are used.
_QA_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Core query logic (testable without MCP)
# ---------------------------------------------------------------------------


def _granule_path_prefix(product: str, date_str: str) -> str:
    """Return the S3 path prefix for a product + date.

    E.g. ``meeo-s5p/OFFL/L2__CO____/2019/08/19/``
    """
    d = parse_date(date_str)
    folder = _PRODUCTS[product]["folder"]
    return f"{_BUCKET}/{_PROCESSING_MODE}/{folder}/{d.year}/{d.month:02d}/{d.day:02d}/"


def _extract_pixel_point(
    lat_f: np.ndarray,
    lon_f: np.ndarray,
    qa_f: np.ndarray,
    val_f: np.ndarray,
    target_lat: float,
    target_lon: float,
) -> float | None:
    """Extract the nearest valid pixel value for a point query.

    All four input arrays must be pre-flattened 1-D numpy arrays of the same
    length.  Returns ``None`` if the target falls outside the granule swath,
    the nearest pixel's QA score is below the threshold, or the value is a fill.
    """
    # Quick bounding-box check — avoids argmin over millions of pixels when
    # the target is outside the granule swath entirely.
    lat_margin = 1.0  # degrees
    lon_margin = 2.0
    if (
        target_lat < float(lat_f.min()) - lat_margin
        or target_lat > float(lat_f.max()) + lat_margin
        or target_lon < float(lon_f.min()) - lon_margin
        or target_lon > float(lon_f.max()) + lon_margin
    ):
        return None

    # Euclidean distance (small-angle approximation; good enough for nearest-pixel).
    dist = (lat_f - target_lat) ** 2 + (lon_f - target_lon) ** 2
    idx = int(np.argmin(dist))

    if float(qa_f[idx]) < _QA_THRESHOLD:
        return None

    raw = float(val_f[idx])
    # Fill values are typically large negative or positive numbers.
    if not np.isfinite(raw) or raw < -1e10:
        return None
    return raw


def _extract_mean_bbox(
    lat_f: np.ndarray,
    lon_f: np.ndarray,
    qa_f: np.ndarray,
    val_f: np.ndarray,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> float | None:
    """Compute a spatial mean over pixels whose centroids fall inside the bbox.

    All four input arrays must be pre-flattened 1-D numpy arrays of the same
    length.  Returns ``None`` if no QA-passing pixels exist within the bbox.
    """
    # Quick bounding-box check.
    if (
        max_lat < float(lat_f.min()) - 1.0
        or min_lat > float(lat_f.max()) + 1.0
        or max_lon < float(lon_f.min()) - 2.0
        or min_lon > float(lon_f.max()) + 2.0
    ):
        return None

    mask = (
        (lat_f >= min_lat)
        & (lat_f <= max_lat)
        & (lon_f >= min_lon)
        & (lon_f <= max_lon)
        & (qa_f >= _QA_THRESHOLD)
    )
    valid_vals = val_f[mask]
    if len(valid_vals) == 0:
        return None
    finite_mask = np.isfinite(valid_vals) & (valid_vals > -1e10)
    if not finite_mask.any():
        return None
    return float(np.mean(valid_vals[finite_mask]))


def _query_granules_point(
    product: str,
    date_str: str,
    target_lat: float,
    target_lon: float,
    fs: s3fs.S3FileSystem,
) -> list[dict[str, Any]]:
    """Return per-granule records for a point query on a single date."""
    prefix = _granule_path_prefix(product, date_str)
    try:
        granule_paths = [f for f in fs.ls(prefix, detail=False) if f.endswith(".nc")]
    except FileNotFoundError:
        return []

    variable = _PRODUCTS[product]["variable"]
    units = _PRODUCTS[product]["units"]
    records: list[dict[str, Any]] = []
    lat_margin = 1.0
    lon_margin = 2.0

    for path in granule_paths:
        try:
            # cache_type='none' issues precise byte-range HTTP requests rather than
            # pre-fetching large blocks.  h5py is used directly (not xarray) because
            # h5netcdf's file-open traversal issues many scattered HTTP requests,
            # making it ~10× slower per granule than h5py's targeted chunk reads.
            with (
                fs.open(path, "rb", cache_type="none") as fobj,
                h5py.File(fobj, "r") as hf,
            ):
                # Load lat/lon first for the cheap bounding-box pre-filter.
                lat_f = hf["PRODUCT/latitude"][:].ravel()
                lon_f = hf["PRODUCT/longitude"][:].ravel()

                # Skip granules whose swath doesn't cover the target.
                if (
                    target_lat < float(lat_f.min()) - lat_margin
                    or target_lat > float(lat_f.max()) + lat_margin
                    or target_lon < float(lon_f.min()) - lon_margin
                    or target_lon > float(lon_f.max()) + lon_margin
                ):
                    continue

                # Granule passes bbox — load the expensive qa and product arrays.
                qa_f = hf["PRODUCT/qa_value"][:].ravel()
                val_f = hf[f"PRODUCT/{variable}"][:].ravel()

                value = _extract_pixel_point(lat_f, lon_f, qa_f, val_f, target_lat, target_lon)
        except Exception:
            continue
        if value is None:
            continue
        granule_id = path.split("/")[-1].replace(".nc", "")
        records.append(
            {
                "date": date_str,
                "granule_id": granule_id,
                "latitude": target_lat,
                "longitude": target_lon,
                product: value,
                f"{product}_units": units,
            }
        )
    return records


def _query_granules_bbox(
    product: str,
    date_str: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    fs: s3fs.S3FileSystem,
) -> list[dict[str, Any]]:
    """Return per-granule mean records for a bbox query on a single date."""
    prefix = _granule_path_prefix(product, date_str)
    try:
        granule_paths = [f for f in fs.ls(prefix, detail=False) if f.endswith(".nc")]
    except FileNotFoundError:
        return []

    variable = _PRODUCTS[product]["variable"]
    units = _PRODUCTS[product]["units"]
    records: list[dict[str, Any]] = []

    for path in granule_paths:
        try:
            with (
                fs.open(path, "rb", cache_type="none") as fobj,
                h5py.File(fobj, "r") as hf,
            ):
                # Load lat/lon first for the cheap bounding-box pre-filter.
                lat_f = hf["PRODUCT/latitude"][:].ravel()
                lon_f = hf["PRODUCT/longitude"][:].ravel()

                # Skip granules whose swath doesn't overlap the bbox.
                if (
                    max_lat < float(lat_f.min()) - 1.0
                    or min_lat > float(lat_f.max()) + 1.0
                    or max_lon < float(lon_f.min()) - 2.0
                    or min_lon > float(lon_f.max()) + 2.0
                ):
                    continue

                # Granule overlaps bbox — load the expensive qa and product arrays.
                qa_f = hf["PRODUCT/qa_value"][:].ravel()
                val_f = hf[f"PRODUCT/{variable}"][:].ravel()

                value = _extract_mean_bbox(
                    lat_f, lon_f, qa_f, val_f, min_lat, max_lat, min_lon, max_lon
                )
        except Exception:
            continue
        if value is None:
            continue
        granule_id = path.split("/")[-1].replace(".nc", "")
        records.append(
            {
                "date": date_str,
                "granule_id": granule_id,
                "min_lat": min_lat,
                "max_lat": max_lat,
                "min_lon": min_lon,
                "max_lon": max_lon,
                f"{product}_mean": value,
                f"{product}_units": units,
            }
        )
    return records


def _iter_dates(start_date: str, end_date: str) -> list[str]:
    """Return list of ISO date strings from start_date to end_date inclusive."""
    import datetime

    start = parse_date(start_date)
    end = parse_date(end_date)
    out = []
    current = start
    while current <= end:
        out.append(current.isoformat())
        current += datetime.timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
def sentinel5p_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    product: str = "CO",
) -> dict[str, Any]:
    """Return Sentinel-5P TROPOMI column values at a point for a date range.

    Reads orbit-granule NetCDF files from the ESA/MEEO public S3 bucket
    (``s3://meeo-s5p``) using anonymous access.  For each date, all granules
    are scanned; only those whose swath covers the target point contribute
    records.  Latency scales with the number of days requested (~5–30 s/day).

    Args:
        latitude: WGS84 decimal latitude.
        longitude: WGS84 decimal longitude.
        start_date: Inclusive start date, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end date, ISO 8601 ``YYYY-MM-DD``.
        product: One of ``"CO"``, ``"NO2"``, or ``"CH4"``.

    Returns:
        ``{"data": list[dict], "_meta": dict}`` — one record per granule that
        covers the target point.  Each record contains ``date``, ``granule_id``,
        ``latitude``, ``longitude``, the product value, and ``{product}_units``.
    """
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "product": product,
    }
    try:
        product_upper = product.upper()
        if product_upper not in _PRODUCTS:
            raise ValueError(f"Unknown product {product!r}. Choose from: {list(_PRODUCTS)}")
        parse_date(start_date)
        parse_date(end_date)
        dates = _iter_dates(start_date, end_date)
        # Connection timeout prevents indefinite hangs when the S3 endpoint is
        # slow or unresponsive; read_timeout covers per-chunk HTTP range reads.
        fs = s3fs.S3FileSystem(
            anon=True,
            config_kwargs={"connect_timeout": 30, "read_timeout": 120},
        )
        records: list[dict[str, Any]] = []
        for date_str in dates:
            records.extend(_query_granules_point(product_upper, date_str, latitude, longitude, fs))
        latency = time.perf_counter() - t0
        meta = build_meta(
            source="sentinel5p",
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info=LICENSE_INFO,
            variables=[product_upper],
            variable_info={product_upper: VARIABLE_INFO[product_upper]},
            success=True,
            error=(
                f"No {product_upper} data found for this location and date range."
                if not records
                else None
            ),
        )
        return {"data": records, "_meta": meta}
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="sentinel5p",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }


@mcp.tool()
def sentinel5p_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    product: str = "CO",
) -> dict[str, Any]:
    """Return spatially-averaged Sentinel-5P TROPOMI values over a bounding box.

    For each date in the range, all granules whose swath overlaps the bbox are
    processed; pixels inside the bbox with QA ≥ 0.5 are averaged.

    Args:
        min_lat: Southern boundary (WGS84 decimal degrees).
        max_lat: Northern boundary.
        min_lon: Western boundary.
        max_lon: Eastern boundary.
        start_date: Inclusive start date, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end date, ISO 8601 ``YYYY-MM-DD``.
        product: One of ``"CO"``, ``"NO2"``, or ``"CH4"``.
    """
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "product": product,
    }
    try:
        product_upper = product.upper()
        if product_upper not in _PRODUCTS:
            raise ValueError(f"Unknown product {product!r}. Choose from: {list(_PRODUCTS)}")
        parse_date(start_date)
        parse_date(end_date)
        bbox = clamp_bbox(
            {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
        )
        dates = _iter_dates(start_date, end_date)
        fs = s3fs.S3FileSystem(
            anon=True,
            config_kwargs={"connect_timeout": 30, "read_timeout": 120},
        )
        records: list[dict[str, Any]] = []
        for date_str in dates:
            records.extend(
                _query_granules_bbox(
                    product_upper,
                    date_str,
                    bbox["min_lat"],
                    bbox["max_lat"],
                    bbox["min_lon"],
                    bbox["max_lon"],
                    fs,
                )
            )
        latency = time.perf_counter() - t0
        meta = build_meta(
            source="sentinel5p",
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info=LICENSE_INFO,
            variables=[product_upper],
            variable_info={product_upper: VARIABLE_INFO[product_upper]},
            success=True,
            error=(
                f"No {product_upper} data found for this bbox and date range."
                if not records
                else None
            ),
        )
        lat, lon = bbox_centroid(bbox)
        meta["bbox_centroid_lat"] = lat
        meta["bbox_centroid_lon"] = lon
        return {"data": records, "_meta": meta}
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="sentinel5p",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }
