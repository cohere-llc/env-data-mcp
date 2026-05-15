"""Sentinel-5P TROPOMI L2 offline adapter — CDSE catalogue + Cloud-Optimized GeoTIFF reader.

Data source: ``s3://meeo-s5p/COGT/``
Coverage: Global, July 2018–present (orbit-granule Cloud-Optimized GeoTIFF files)
Auth required: No (anonymous; CDSE and MEEO S3 are both public)
License: ESA Copernicus Open Access — attribution required

Supported products
------------------
CO  → carbonmonoxide_total_column          (mol m⁻²)
NO2 → nitrogendioxide_tropospheric_column  (mol m⁻²)
CH4 → methane_mixing_ratio_bias_corrected  (ppb)

Query strategy
--------------
1. Call the Copernicus Data Space Ecosystem (CDSE) OData API with a spatial
   intersection filter to find only the 1–2 orbit granules per day that
   actually cover the target point or bbox.  For a 1-month query this
   reduces ~420 candidate granules to ~47.

2. Fetch the Cloud-Optimized GeoTIFF (COGT) file for each matching granule
   from the MEEO public S3 bucket using GDAL VSICURL HTTP range GETs.  A
   COG point read downloads ~650 KB (the TIFF header + the tile covering
   the target location) instead of the ~5.5 MB needed to read the raw
   NetCDF, and GDAL handles the range requests automatically.

3. All granule COG reads are performed in parallel (16 worker threads).

Resulting latency: ~2 s (CDSE) + ~7 s (parallel COGT reads) ≈ <10 s for a
full calendar month, vs ~100 s with the previous per-day listing approach.
"""

from __future__ import annotations

import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
import numpy as np
import rasterio
from rasterio.env import Env
from rasterio.windows import from_bounds

from env_data_mcp.helpers import bbox_centroid, build_meta, check_runtime, clamp_bbox, parse_date
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

_BUCKET_URL = "https://meeo-s5p.s3.amazonaws.com"
_PROCESSING_MODE = "OFFL"
_CDSE_ODATA_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"

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

# QA threshold — pixels with qa_value (0–1 scale) below this are excluded.
# COGT files store qa_value on a 0–100 integer scale; we divide by 100
# before comparing so this constant stays in the familiar 0–1 space.
_QA_THRESHOLD = 0.5

# GDAL/VSICURL environment for efficient COG range reads.
_GDAL_OPTS: dict[str, str] = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_CHUNK_SIZE": "65536",
    "GDAL_HTTP_MAX_RETRY": "2",
}

# Number of threads for parallel COGT reads.
_GRANULE_IO_WORKERS = 16


# ---------------------------------------------------------------------------
# CDSE granule catalogue
# ---------------------------------------------------------------------------


def _cdse_query_granules(
    product: str,
    start_date: str,
    end_date: str,
    *,
    lat: float | None = None,
    lon: float | None = None,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lon: float | None = None,
    max_lon: float | None = None,
) -> list[str]:
    """Return ``.nc`` granule names that cover a point or bbox in a date range.

    Calls the Copernicus Data Space Ecosystem (CDSE) OData API with a spatial
    intersection filter so only the 1–2 granules per day that actually observe
    the target location are returned.  For a 1-month query this is typically
    ~47 granules rather than ~420.

    Either (*lat*, *lon*) for a point query or all four bbox parameters for
    a region query must be supplied as keyword arguments.
    """
    folder = _PRODUCTS[product]["folder"]
    # CDSE Name prefix: e.g. "S5P_OFFL_L2__CO" from folder "L2__CO____"
    name_prefix = f"S5P_OFFL_{folder.rstrip('_')}"

    if lat is not None and lon is not None:
        area = f"geography'SRID=4326;POINT({lon} {lat})'"
    else:
        # Closed bbox polygon: SW → SE → NE → NW → SW
        area = (
            f"geography'SRID=4326;POLYGON(("
            f"{min_lon} {min_lat},{max_lon} {min_lat},"
            f"{max_lon} {max_lat},{min_lon} {max_lat},"
            f"{min_lon} {min_lat}))'"
        )

    end_dt = parse_date(end_date) + datetime.timedelta(days=1)
    filt = (
        f"Collection/Name eq 'SENTINEL-5P'"
        f" and startswith(Name,'{name_prefix}')"
        f" and OData.CSC.Intersects(area={area})"
        f" and ContentDate/Start ge {start_date}T00:00:00.000Z"
        f" and ContentDate/Start lt {end_dt.isoformat()}T00:00:00.000Z"
    )

    names: list[str] = []
    skip = 0
    page_size = 1000
    while True:
        resp = httpx.get(
            _CDSE_ODATA_URL,
            params={
                "$filter": filt,
                "$top": str(page_size),
                "$skip": str(skip),
                "$select": "Name",
            },
            timeout=30,
        )
        resp.raise_for_status()
        page = resp.json().get("value", [])
        names.extend(r["Name"] for r in page)
        if len(page) < page_size:
            break
        skip += page_size
    return names


# ---------------------------------------------------------------------------
# COGT URL builder and per-granule readers
# ---------------------------------------------------------------------------


def _cogt_url(granule_name: str, product: str, variable: str) -> str:
    """Return a GDAL VSICURL URL for a COGT variable file.

    Granule names follow the pattern::

        S5P_OFFL_L2__CO_____YYYYMMDDTHHMMSS_..._PROC.nc

    The orbit-start date occupies characters 20–27 (``YYYYMMDD``).
    """
    date_part = granule_name[20:28]  # YYYYMMDD
    yyyy, mm, dd = date_part[:4], date_part[4:6], date_part[6:8]
    folder = _PRODUCTS[product]["folder"]
    base = granule_name.removesuffix(".nc")
    key = f"COGT/OFFL/{folder}/{yyyy}/{mm}/{dd}/{base}_PRODUCT_{variable}_4326.tif"
    return f"/vsicurl/{_BUCKET_URL}/{key}"


def _read_cogt_point(
    granule_name: str,
    product: str,
    target_lat: float,
    target_lon: float,
) -> dict[str, Any] | None:
    """Fetch the product and QA values at a point from a COGT granule.

    Uses GDAL VSICURL range GETs to download only the ~650 KB tile covering
    the target location from each Cloud-Optimized GeoTIFF, rather than the
    full ~15 MB file.  Returns a record dict or ``None`` if the pixel is
    nodata or below the QA threshold.
    """
    variable = _PRODUCTS[product]["variable"]
    units = _PRODUCTS[product]["units"]
    co_url = _cogt_url(granule_name, product, variable)
    qa_url = _cogt_url(granule_name, product, "qa_value")
    try:
        with Env(aws_unsigned=True, **_GDAL_OPTS):
            with rasterio.open(co_url) as ds:
                co_nodata = ds.nodata
                co_val = float(list(ds.sample([(target_lon, target_lat)]))[0][0])
            with rasterio.open(qa_url) as ds:
                qa_nodata = ds.nodata
                qa_val = float(list(ds.sample([(target_lon, target_lat)]))[0][0])
    except Exception:
        return None

    if (co_nodata is not None and co_val == co_nodata) or not np.isfinite(co_val) or co_val < -1e10:
        return None
    if qa_nodata is not None and qa_val == qa_nodata:
        return None
    # COGT qa_value is stored on a 0–100 scale; normalise to 0–1 for comparison.
    if qa_val / 100.0 < _QA_THRESHOLD:
        return None

    date_str = granule_name[20:28]
    date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    granule_id = granule_name.removesuffix(".nc")
    return {
        "date": date_iso,
        "granule_id": granule_id,
        "latitude": target_lat,
        "longitude": target_lon,
        product: co_val,
        f"{product}_units": units,
    }


def _read_cogt_bbox(
    granule_name: str,
    product: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> dict[str, Any] | None:
    """Compute the spatial mean over a bbox from a COGT granule.

    Reads a raster window covering the bbox from both the product and
    ``qa_value`` COG files, filters by QA threshold, and returns the mean
    product value.  Returns ``None`` if there are no valid pixels.
    """
    variable = _PRODUCTS[product]["variable"]
    units = _PRODUCTS[product]["units"]
    co_url = _cogt_url(granule_name, product, variable)
    qa_url = _cogt_url(granule_name, product, "qa_value")
    try:
        with Env(aws_unsigned=True, **_GDAL_OPTS):
            with rasterio.open(co_url) as ds:
                co_nodata = ds.nodata
                window = from_bounds(min_lon, min_lat, max_lon, max_lat, ds.transform)
                co_data = ds.read(1, window=window).astype(np.float64)
            with rasterio.open(qa_url) as ds:
                qa_nodata = ds.nodata
                qa_data = ds.read(1, window=window).astype(np.float64)
    except Exception:
        return None

    co_valid = (
        (co_data != co_nodata) if co_nodata is not None else np.ones(co_data.shape, dtype=bool)
    )
    qa_valid = (
        (qa_data != qa_nodata) if qa_nodata is not None else np.ones(qa_data.shape, dtype=bool)
    )
    qa_pass = (qa_data / 100.0) >= _QA_THRESHOLD
    mask = co_valid & qa_valid & qa_pass & np.isfinite(co_data) & (co_data > -1e10)

    if not mask.any():
        return None

    mean_val = float(np.mean(co_data[mask]))
    date_str = granule_name[20:28]
    date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    granule_id = granule_name.removesuffix(".nc")
    return {
        "date": date_iso,
        "granule_id": granule_id,
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        f"{product}_mean": mean_val,
        f"{product}_units": units,
    }


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
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Return Sentinel-5P TROPOMI column values at a point for a date range.

    First queries the Copernicus Data Space Ecosystem (CDSE) catalogue to
    identify only the orbit granules that spatially cover the target point,
    then reads just the Cloud-Optimized GeoTIFF tile covering that point
    from the MEEO public S3 bucket.  Typical latency: <10 s for 1 month.

    Args:
        latitude: WGS84 decimal latitude.
        longitude: WGS84 decimal longitude.
        start_date: Inclusive start date, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end date, ISO 8601 ``YYYY-MM-DD``.
        product: One of ``"CO"``, ``"NO2"``, or ``"CH4"``.

    Returns:
        ``{"data": list[dict], "_meta": dict}`` — one record per granule that
        covers the target point with valid QA.  Each record contains ``date``,
        ``granule_id``, ``latitude``, ``longitude``, the product value, and
        ``{product}_units``.
    """
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "product": product,
        "max_runtime_s": max_runtime_s,
    }
    try:
        product_upper = product.upper()
        if product_upper not in _PRODUCTS:
            raise ValueError(f"Unknown product {product!r}. Choose from: {list(_PRODUCTS)}")
        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        if warn := check_runtime("sentinel5p", n_days, 0.0, max_runtime_s):
            return warn
        granule_names = _cdse_query_granules(
            product_upper, start_date, end_date, lat=latitude, lon=longitude
        )
        records: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=_GRANULE_IO_WORKERS) as pool:
            futures = {
                pool.submit(_read_cogt_point, g, product_upper, latitude, longitude): g
                for g in granule_names
            }
            for future in as_completed(futures):
                rec = future.result()
                if rec is not None:
                    records.append(rec)
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
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Return spatially-averaged Sentinel-5P TROPOMI values over a bounding box.

    First queries CDSE for granules covering the bbox, then reads the
    matching raster window from each granule's Cloud-Optimized GeoTIFF and
    averages all QA-passing pixels.  Typical latency: <10 s for 1 month.

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
        "max_runtime_s": max_runtime_s,
    }
    try:
        product_upper = product.upper()
        if product_upper not in _PRODUCTS:
            raise ValueError(f"Unknown product {product!r}. Choose from: {list(_PRODUCTS)}")
        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        bbox = clamp_bbox(
            {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
        )
        area_deg2 = (bbox["max_lat"] - bbox["min_lat"]) * (bbox["max_lon"] - bbox["min_lon"])
        if warn := check_runtime("sentinel5p", n_days, area_deg2, max_runtime_s):
            return warn
        query_params.update(bbox)
        granule_names = _cdse_query_granules(
            product_upper,
            start_date,
            end_date,
            min_lat=bbox["min_lat"],
            max_lat=bbox["max_lat"],
            min_lon=bbox["min_lon"],
            max_lon=bbox["max_lon"],
        )
        records: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=_GRANULE_IO_WORKERS) as pool:
            futures = {
                pool.submit(
                    _read_cogt_bbox,
                    g,
                    product_upper,
                    bbox["min_lat"],
                    bbox["max_lat"],
                    bbox["min_lon"],
                    bbox["max_lon"],
                ): g
                for g in granule_names
            }
            for future in as_completed(futures):
                rec = future.result()
                if rec is not None:
                    records.append(rec)
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
