"""OCO-2 Level 3 daily XCO2 grid adapter.

Data source: NASA GES DISC via CMR + direct HTTPS download
Collection:  OCO2_GEOS_L3CO2_DAY, version 10r (GEOS assimilation product)
Coverage:    Global, 0.5°×0.625° grid, 2014-09 to present (daily)
Auth:        NASA EarthData bearer token — set ``EARTHDATA_TOKEN`` env var
License:     NASA Open Data Policy (public domain)
"""

from __future__ import annotations

import io
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import h5py
import httpx
import numpy as np

from env_data_mcp.helpers import (
    auth_missing_response,
    build_meta,
    check_runtime,
    clamp_bbox,
    parse_date,
)
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# License and variable metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "NASA Open Data Policy (public domain)",
    "license_url": "https://www.nasa.gov/open/data.html",
    "citation": (
        "Weir, B., Ott, L., et al. (2021). OCO-2 GEOS Level 3 daily, 0.5x0.625 deg assimilation, "
        "V10r. Goddard Earth Sciences Data and Information Services Center (GES DISC). "
        "https://doi.org/10.5067/Y9M4NM9MPCGH"
    ),
}

VARIABLE_INFO: dict[str, dict[str, str]] = {
    "xco2": {
        "description": "Column-averaged dry-air mole fraction of CO2",
        "units": "ppm",
        "valid_range": "380 to 430 (typical tropospheric range)",
    },
    "xco2_quality_flag": {
        "description": "Quality flag: 0 = good, 1 = caution, 2 = bad",
        "units": "unitless",
        "valid_range": "0, 1, 2",
    },
    "xco2_uncertainty": {
        "description": "1-sigma retrieval uncertainty",
        "units": "ppm",
        "valid_range": "0 to 5",
    },
}

# ---------------------------------------------------------------------------
# CMR / data-access constants
# ---------------------------------------------------------------------------

_CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
_SHORT_NAME = "OCO2_GEOS_L3CO2_DAY"
_VERSION = "10r"
_FILL_VALUE = -9999.0

# Candidate HDF5 paths for the XCO2 variable (tried in order).
# Different OCO-2 L3 file versions may use slightly different group names.
_XCO2_PATHS = [
    "HDFEOS/GRIDS/OCO-2 Level 3 Gridded XCO2/Data Fields/XCO2",
    "HDFEOS/GRIDS/OCO-2 Level 3 Daily, 0.5x0.625 deg Grid/Data Fields/XCO2",
    "XCO2",
]
_XCO2PREC_SUFFIXES = ["/XCO2PREC", "/XAPRIORI", "/XCO2_RETRIEVAL_ERROR"]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_fill_value(ds: h5py.Dataset) -> float:
    """Extract the fill value, handling numpy 0-d or 1-d array attributes."""
    fill = ds.attrs.get("_FillValue", _FILL_VALUE)
    if hasattr(fill, "flat"):
        return float(next(iter(fill.flat)))
    return float(fill)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _cmr_search(start_date: str, end_date: str, token: str) -> list[dict[str, Any]]:
    """Return all OCO-2 L3 granules whose time range overlaps [start_date, end_date]."""
    resp = httpx.get(
        _CMR_GRANULES,
        params={
            "short_name": _SHORT_NAME,
            "version": _VERSION,
            "temporal[]": f"{start_date}T00:00:00Z,{end_date}T23:59:59Z",
            "page_size": 200,
            "sort_key": "start_date",
        },
        headers=_auth_headers(token),
        timeout=30.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.json().get("feed", {}).get("entry", [])


def _granule_date(granule: dict[str, Any]) -> str:
    """Return the ISO 8601 date (YYYY-MM-DD) for the granule's start time."""
    ts = granule.get("time_start", "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", ts)
    return m.group(1) if m else ts[:10]


def _granule_id(granule: dict[str, Any]) -> str:
    return granule.get("producer_granule_id") or granule.get("title", "")


def _get_download_url(granule: dict[str, Any]) -> str | None:
    """Extract the best download URL from a CMR granule entry.

    Prefers OPeNDAP file links (smaller subset requests possible), then direct
    data downloads.  ``service#`` OPeNDAP endpoints (collection-level, no file
    extension) are skipped — they are not directly downloadable.
    """
    _FILE_EXTS = (".he5", ".nc", ".nc4", ".h5")
    links = granule.get("links", [])
    # 1. Try OPeNDAP file link (rel must contain 'opendap'; must be a direct file)
    for lnk in links:
        rel = lnk.get("rel", "")
        href = lnk.get("href", "")
        if "opendap" in rel.lower() and any(href.endswith(ext) for ext in _FILE_EXTS):
            return href
    # 2. Fall back to direct data download link
    for lnk in links:
        rel = lnk.get("rel", "")
        href = lnk.get("href", "")
        if "data#" in rel and any(href.endswith(ext) for ext in _FILE_EXTS):
            return href
    # 3. Last resort: any non-HTML link
    for lnk in links:
        href = lnk.get("href", "")
        if href.startswith("https://") and not href.endswith(".html"):
            return href
    return None


def _fetch_granule_bytes(url: str, token: str) -> bytes:
    """Download a granule file from GES DISC and return its raw bytes.

    Raises ValueError with a user-friendly message on HTTP 401 (expired token).
    """
    resp = httpx.get(url, headers=_auth_headers(token), timeout=120.0, follow_redirects=True)
    if resp.status_code == 401:
        raise ValueError(
            "EarthData token rejected (HTTP 401) — token may be expired. "
            "Regenerate at https://urs.earthdata.nasa.gov/ → Profile → Generate Token "
            "and update EARTHDATA_TOKEN in .env."
        )
    resp.raise_for_status()
    return resp.content


def _open_xco2_dataset(hf: h5py.File) -> h5py.Dataset | None:
    """Return the XCO2 dataset from an open h5py file, trying known paths."""
    for path in _XCO2_PATHS:
        try:
            ds = hf[path]
            if isinstance(ds, h5py.Dataset):
                return ds
        except KeyError:
            continue
    # Fallback: walk all datasets and find one named XCO2
    result: list[h5py.Dataset] = []

    def _visit(name: str, obj: Any) -> None:
        if (
            isinstance(obj, h5py.Dataset)
            and "XCO2" in name.upper()
            and not any(s in name.upper() for s in ("PREC", "ERROR", "APRIORI", "OBS"))
        ):
            result.append(obj)

    hf.visititems(_visit)
    return result[0] if result else None


def _grid_params(nrows: int, ncols: int) -> tuple[float, float, float, float]:
    """Infer (lat_origin, lon_origin, lat_step, lon_step) from grid dimensions.

    OCO-2 L3 grids are cell-centred with the first cell at half-step from the
    coordinate origin.  Common shapes:
      - (180, 360)  → 1.0° × 1.0°
      - (360, 576)  → 0.5° × 0.625°
    """
    lat_step = 180.0 / nrows
    lon_step = 360.0 / ncols
    lat_origin = -90.0 + lat_step / 2.0  # centre of first (southernmost) row
    lon_origin = -180.0 + lon_step / 2.0
    return lat_origin, lon_origin, lat_step, lon_step


def _point_to_idx(
    lat: float,
    lon: float,
    lat_origin: float,
    lon_origin: float,
    lat_step: float,
    lon_step: float,
    nrows: int,
    ncols: int,
) -> tuple[int, int]:
    """Convert WGS84 (lat, lon) to (row, col) indices on the OCO-2 L3 grid."""
    i = int(round((lat - lat_origin) / lat_step))
    j = int(round((lon - lon_origin) / lon_step))
    return max(0, min(nrows - 1, i)), max(0, min(ncols - 1, j))


def _parse_xco2_point(
    content: bytes, lat: float, lon: float, date_str: str, gid: str
) -> dict[str, Any] | None:
    """Open HDF5 content and extract XCO2 at the nearest grid cell to (lat, lon).

    Returns None if the pixel is fill-valued (no data at this location/date).
    Handles both the legacy 2D (ppm) format and the current GEOS 3D (mol/mol) format.
    """
    with h5py.File(io.BytesIO(content), "r") as hf:
        xco2_ds = _open_xco2_dataset(hf)
        if xco2_ds is None:
            return None
        data = xco2_ds[:]
        if data.ndim == 3:
            data = data[0]  # squeeze daily time dimension (GEOS L3 format)
        nrows, ncols = data.shape
        fill = _get_fill_value(xco2_ds)

        # Prefer explicit coordinate arrays (GEOS L3); fall back to inferred grid.
        if "lat" in hf and "lon" in hf:
            lat_arr: np.ndarray = cast(h5py.Dataset, hf["lat"])[:]
            lon_arr: np.ndarray = cast(h5py.Dataset, hf["lon"])[:]
            i = int(np.argmin(np.abs(lat_arr - lat)))
            j = int(np.argmin(np.abs(lon_arr - lon)))
            actual_lat = round(float(lat_arr[i]), 4)
            actual_lon = round(float(lon_arr[j]), 4)
        else:
            lat_orig, lon_orig, lat_step, lon_step = _grid_params(nrows, ncols)
            i, j = _point_to_idx(lat, lon, lat_orig, lon_orig, lat_step, lon_step, nrows, ncols)
            actual_lat = round(lat_orig + i * lat_step, 4)
            actual_lon = round(lon_orig + j * lon_step, 4)

        val = float(data[i, j])
        if val <= fill or np.isnan(val):
            return None
        if val < 1.0:
            val *= 1e6  # convert mol/mol → ppm (GEOS L3 product)

        # Try to get precision / uncertainty
        prec: float | None = None
        base = (xco2_ds.name or "").rsplit("/", 1)[0]  # parent group path
        for suf in _XCO2PREC_SUFFIXES:
            candidate = base + suf
            if candidate in hf:
                _prec_obj = hf[candidate]
                if isinstance(_prec_obj, h5py.Dataset):
                    p_data = _prec_obj[:]
                    if p_data.ndim == 3:
                        p_data = p_data[0]
                    p = float(p_data[i, j])
                    if p > fill and not np.isnan(p):
                        if p < 1.0:
                            p *= 1e6  # mol/mol → ppm
                        prec = round(p, 3)
                break

        return {
            "date": date_str,
            "xco2": round(val, 3),
            "xco2_uncertainty": prec,
            "units": "ppm",
            "latitude": actual_lat,
            "longitude": actual_lon,
            "granule_id": gid,
        }


def _parse_xco2_bbox(
    content: bytes,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    date_str: str,
    gid: str,
) -> list[dict[str, Any]]:
    """Extract all non-fill XCO2 cells within the bounding box.

    Handles both the legacy 2D (ppm) format and the current GEOS 3D (mol/mol) format.
    """
    records: list[dict[str, Any]] = []
    with h5py.File(io.BytesIO(content), "r") as hf:
        xco2_ds = _open_xco2_dataset(hf)
        if xco2_ds is None:
            return records
        data = xco2_ds[:]
        if data.ndim == 3:
            data = data[0]  # squeeze daily time dimension (GEOS L3 format)
        nrows, ncols = data.shape
        fill = _get_fill_value(xco2_ds)

        # Compute bbox slice indices using explicit coords (GEOS) or inferred grid (legacy).
        if "lat" in hf and "lon" in hf:
            lat_arr: np.ndarray = cast(h5py.Dataset, hf["lat"])[:]
            lon_arr: np.ndarray = cast(h5py.Dataset, hf["lon"])[:]
            lat_mask = (lat_arr >= min_lat) & (lat_arr <= max_lat)
            lon_mask = (lon_arr >= min_lon) & (lon_arr <= max_lon)
            i_idx = np.where(lat_mask)[0]
            j_idx = np.where(lon_mask)[0]
            if len(i_idx) == 0 or len(j_idx) == 0:
                return records
            i_lo, i_hi = int(i_idx[0]), int(i_idx[-1]) + 1
            j_lo, j_hi = int(j_idx[0]), int(j_idx[-1]) + 1
            row_lats = [round(float(lat_arr[i_lo + di]), 4) for di in range(i_hi - i_lo)]
            col_lons = [round(float(lon_arr[j_lo + dj]), 4) for dj in range(j_hi - j_lo)]
        else:
            lat_orig, lon_orig, lat_step, lon_step = _grid_params(nrows, ncols)
            args = (lat_orig, lon_orig, lat_step, lon_step, nrows, ncols)
            i_lo, _ = _point_to_idx(min_lat, min_lon, *args)
            i_hi, _ = _point_to_idx(max_lat, max_lon, *args)
            _, j_lo = _point_to_idx(min_lat, min_lon, *args)
            _, j_hi = _point_to_idx(max_lat, max_lon, *args)
            # Guard against reversed bbox
            i_lo, i_hi = min(i_lo, i_hi), max(i_lo, i_hi) + 1
            j_lo, j_hi = min(j_lo, j_hi), max(j_lo, j_hi) + 1
            row_lats = [round(lat_orig + (i_lo + di) * lat_step, 4) for di in range(i_hi - i_lo)]
            col_lons = [round(lon_orig + (j_lo + dj) * lon_step, 4) for dj in range(j_hi - j_lo)]

        # Slice the spatial window after loading — OCO-2 L3 daily files are
        # ~3–5 MB, so loading the full array into memory is acceptable.
        # data[i_lo:i_hi, j_lo:j_hi] limits iteration to only the requested cells.
        base = (xco2_ds.name or "").rsplit("/", 1)[0]
        prec_data: np.ndarray | None = None
        for suf in _XCO2PREC_SUFFIXES:
            candidate = base + suf
            if candidate in hf:
                _prec_obj = hf[candidate]
                if isinstance(_prec_obj, h5py.Dataset):
                    prec_raw = _prec_obj[:]
                    if prec_raw.ndim == 3:
                        prec_raw = prec_raw[0]
                    prec_data = prec_raw[i_lo:i_hi, j_lo:j_hi]
                break

        slice_data = data[i_lo:i_hi, j_lo:j_hi]
        for di in range(slice_data.shape[0]):
            for dj in range(slice_data.shape[1]):
                val = float(slice_data[di, dj])
                if val <= fill or np.isnan(val):
                    continue
                if val < 1.0:
                    val *= 1e6  # mol/mol → ppm (GEOS L3 product)
                prec: float | None = None
                if prec_data is not None:
                    p = float(prec_data[di, dj])
                    if p > fill and not np.isnan(p):
                        if p < 1.0:
                            p *= 1e6  # mol/mol → ppm
                        prec = round(p, 3)
                records.append(
                    {
                        "date": date_str,
                        "xco2": round(val, 3),
                        "xco2_uncertainty": prec,
                        "units": "ppm",
                        "latitude": row_lats[di],
                        "longitude": col_lons[dj],
                        "granule_id": gid,
                    }
                )
    return records


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
def oco2_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Return OCO-2 daily XCO2 values at a point for a date range.

    Requires ``EARTHDATA_TOKEN`` (free registration at
    https://urs.earthdata.nasa.gov/).  One record per day that has
    data at the nearest grid cell to (latitude, longitude).

    Args:
        latitude: WGS84 decimal latitude.
        longitude: WGS84 decimal longitude.
        start_date: Inclusive start, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end, ISO 8601 ``YYYY-MM-DD``.
        max_runtime_s: Acceptable runtime in seconds; see timing docs.

    Returns:
        ``{"data": list[dict], "_meta": dict}`` — each record has ``date``,
        ``xco2``, ``xco2_uncertainty``, ``units``, ``latitude``,
        ``longitude``, ``granule_id``.
    """
    t0 = time.perf_counter()
    _sd = parse_date(start_date)
    _ed = parse_date(end_date)
    n_days = (_ed - _sd).days + 1
    if warn := check_runtime("oco2", n_days, 0.0, max_runtime_s):
        return warn
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "max_runtime_s": max_runtime_s,
    }
    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        return auth_missing_response(
            "oco2",
            LICENSE_INFO,
            "EARTHDATA_TOKEN environment variable is not set. "
            "Register free at https://urs.earthdata.nasa.gov/ then generate "
            "a token under Profile → Generate Token.",
            query_params,
        )

    try:
        granules = _cmr_search(start_date, end_date, token)
        records: list[dict[str, Any]] = []

        def _fetch_point(g: dict[str, Any]) -> dict[str, Any] | None:
            url = _get_download_url(g)
            if not url:
                return None
            content = _fetch_granule_bytes(url, token)
            return _parse_xco2_point(content, latitude, longitude, _granule_date(g), _granule_id(g))

        with ThreadPoolExecutor(max_workers=10) as pool:
            for rec in pool.map(_fetch_point, granules):
                if rec is not None:
                    records.append(rec)
        records.sort(key=lambda r: r["date"])
        latency = time.perf_counter() - t0
        return {
            "data": records,
            "_meta": build_meta(
                source="oco2",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=True,
                success=True,
                variables=["xco2", "xco2_uncertainty"],
                variable_info={k: VARIABLE_INFO[k] for k in ("xco2", "xco2_uncertainty")},
                error=(
                    "No data found for the given location and date range." if not records else None
                ),
            ),
        }
    except ValueError as exc:
        latency = time.perf_counter() - t0
        err_str = str(exc)
        return {
            "data": [],
            "_meta": build_meta(
                source="oco2",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=True,
                success=False,
                error=err_str,
            ),
        }


@mcp.tool()
def oco2_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    limit: int | None = None,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Return OCO-2 daily XCO2 values within a bounding box for a date range.

    Args:
        min_lat: Southern boundary (WGS84 decimal degrees).
        max_lat: Northern boundary.
        min_lon: Western boundary.
        max_lon: Eastern boundary.
        start_date: Inclusive start, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end, ISO 8601 ``YYYY-MM-DD``.
        limit: Maximum number of records to return.  Pass ``None`` (default)
            to return all records.  ``_meta.capped`` is ``True`` when the cap
            was reached.
        max_runtime_s: Acceptable runtime in seconds; see timing docs.

    Returns:
        ``{"data": list[dict], "_meta": dict}``
    """
    t0 = time.perf_counter()
    _sd = parse_date(start_date)
    _ed = parse_date(end_date)
    bbox = clamp_bbox(
        {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
    )
    n_days = (_ed - _sd).days + 1
    area_deg2 = (bbox["max_lat"] - bbox["min_lat"]) * (bbox["max_lon"] - bbox["min_lon"])
    if warn := check_runtime("oco2", n_days, area_deg2, max_runtime_s):
        return warn
    query_params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
        "max_runtime_s": max_runtime_s,
        **bbox,
    }
    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        return auth_missing_response(
            "oco2",
            LICENSE_INFO,
            "EARTHDATA_TOKEN environment variable is not set. "
            "Register free at https://urs.earthdata.nasa.gov/ then generate "
            "a token under Profile → Generate Token.",
            query_params,
        )

    try:
        granules = _cmr_search(start_date, end_date, token)

        def _fetch_bbox(g: dict[str, Any]) -> list[dict[str, Any]]:
            url = _get_download_url(g)
            if not url:
                return []
            content = _fetch_granule_bytes(url, token)
            return _parse_xco2_bbox(
                content,
                bbox["min_lat"],
                bbox["max_lat"],
                bbox["min_lon"],
                bbox["max_lon"],
                _granule_date(g),
                _granule_id(g),
            )

        records: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            for batch in pool.map(_fetch_bbox, granules):
                records.extend(batch)
        records.sort(key=lambda r: r["date"])
        records = records[:limit] if limit is not None else records
        capped = limit is not None and len(records) >= limit
        latency = time.perf_counter() - t0
        meta = build_meta(
            source="oco2",
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info=LICENSE_INFO,
            auth_required=True,
            auth_present=True,
            success=True,
            variables=["xco2", "xco2_uncertainty"],
            variable_info={k: VARIABLE_INFO[k] for k in ("xco2", "xco2_uncertainty")},
            error="No data found for the given bbox and date range." if not records else None,
        )
        meta["capped"] = capped
        return {"data": records, "_meta": meta}
    except ValueError as exc:
        latency = time.perf_counter() - t0
        err_str = str(exc)
        return {
            "data": [],
            "_meta": build_meta(
                source="oco2",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=True,
                success=False,
                error=err_str,
            ),
        }
