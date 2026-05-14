"""EMIT L2B Mineral spectral unmixing adapter.

Data source: NASA LP DAAC via CMR + OPeNDAP subsetting
Collection:  EMITL2BMIN, version 001
Coverage:    Global land surfaces, August 2022 – present (sparse; orbit-based)
Auth:        NASA EarthData bearer token — set ``EARTHDATA_TOKEN`` env var
License:     NASA Open Data Policy (public domain)

Access strategy
---------------
EMIT L2B files can be 100–800 MB.  Direct download is impractical inside an
interactive tool.  Instead we use two lightweight OPeNDAP requests:

  1. ``?/location/lat,/location/lon,/mineral_metadata/mineral_name``
     Downloads the full 2-D lat/lon arrays and the mineral-name list.
     Typical compressed size: 2–8 MB per scene.

  2. ``?/spectral_abundance[i:i][j:j][0:N-1]``
     Downloads mineral spectral-abundance fractions for the single found
     pixel.  Tiny (~1 KB).

For bbox queries each pixel in the bbox is returned individually.
"""

from __future__ import annotations

import io
import os
import re
import time
from typing import Any

import h5py
import httpx
import numpy as np

from env_data_mcp.helpers import (
    auth_missing_response,
    build_meta,
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
        "Green, R. O., et al. (2023). EMIT L2B Estimated Mineral "
        "Identification and Band Depth and Uncertainty, V001. "
        "NASA EOSDIS Land Processes Distributed Active Archive Center. "
        "https://doi.org/10.5067/EMIT/EMITL2BMIN.001"
    ),
}

VARIABLE_INFO: dict[str, dict[str, str]] = {
    "spectral_abundance": {
        "description": "Fractional spectral abundance of identified mineral",
        "units": "unitless (0–1)",
        "valid_range": "0 to 1",
    },
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
_SHORT_NAME = "EMITL2BMIN"
_VERSION = "001"
_MAX_GRANULES = 5
_ABUNDANCE_THRESHOLD = 0.005  # ignore trace abundances below 0.5 %

# OPeNDAP base — the CMR-provided OPeNDAP link already contains this prefix,
# but we construct it ourselves for the subsetting second request.
_OPENDAP_BASE = "https://opendap.earthdata.nasa.gov"

# Candidate paths for variables inside the EMIT L2B NetCDF4/HDF5 file.
# Hyrax may expose them with or without the leading slash.
_LAT_PATHS = ["/location/lat", "location/lat", "lat"]
_LON_PATHS = ["/location/lon", "location/lon", "lon"]
_MINERAL_NAME_PATHS = [
    "/mineral_metadata/mineral_name",
    "mineral_metadata/mineral_name",
    "mineral_name",
]
_ABUNDANCE_PATHS = ["/spectral_abundance", "spectral_abundance"]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _cmr_search(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    start_date: str,
    end_date: str,
    token: str,
) -> list[dict[str, Any]]:
    """Return EMIT L2B granules whose spatial footprint overlaps the bbox."""
    resp = httpx.get(
        _CMR_GRANULES,
        params={
            "short_name": _SHORT_NAME,
            "version": _VERSION,
            "bounding_box": f"{min_lon},{min_lat},{max_lon},{max_lat}",
            "temporal[]": f"{start_date}T00:00:00Z,{end_date}T23:59:59Z",
            "page_size": _MAX_GRANULES,
            "sort_key": "start_date",
        },
        headers=_auth_headers(token),
        timeout=30.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.json().get("feed", {}).get("entry", [])[:_MAX_GRANULES]


def _granule_id(granule: dict[str, Any]) -> str:
    return granule.get("producer_granule_id") or granule.get("title", "")


def _granule_date(granule: dict[str, Any]) -> str:
    ts = granule.get("time_start", "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", ts)
    return m.group(1) if m else ts[:10]


def _get_opendap_url(granule: dict[str, Any]) -> str | None:
    """Extract the OPeNDAP base URL from a CMR granule entry."""
    links = granule.get("links", [])
    for lnk in links:
        rel = lnk.get("rel", "")
        href = lnk.get("href", "")
        if "opendap" in rel.lower() or "opendap" in href.lower():
            # Strip any existing suffix — we'll add .nc4 ourselves
            return re.sub(r"\.(dap|nc4|dmr|dds|das)$", "", href)
    return None


def _fetch_opendap_nc4(base_url: str, var_expr: str, token: str) -> bytes:
    """Make an OPeNDAP DAP4 request and return the NetCDF4 response bytes.

    ``var_expr`` is appended after ``?`` to select/subset variables, e.g.
    ``"/location/lat,/location/lon"`` or
    ``"/spectral_abundance[0:0][10:10][0:9]"``.
    """
    url = f"{base_url}.nc4?{var_expr}"
    resp = httpx.get(url, headers=_auth_headers(token), timeout=120.0, follow_redirects=True)
    if resp.status_code == 401:
        raise ValueError(
            "EarthData token rejected (HTTP 401) — token may be expired. "
            "Regenerate at https://urs.earthdata.nasa.gov/ → Profile → Generate Token "
            "and update EARTHDATA_TOKEN in .env."
        )
    resp.raise_for_status()
    return resp.content


def _get_dataset(hf: h5py.File, *paths: str) -> h5py.Dataset | None:
    """Try a sequence of HDF5 paths and return the first that resolves."""
    for p in paths:
        try:
            obj = hf[p]
            if isinstance(obj, h5py.Dataset):
                return obj
        except KeyError:
            continue
    return None


def _decode_mineral_names(ds: h5py.Dataset) -> list[str]:
    """Return mineral name strings from a variable-length or fixed-length HDF5 dataset."""
    raw = ds[:]
    names: list[str] = []
    for item in raw.flat:
        if isinstance(item, bytes):
            names.append(item.decode("utf-8", errors="replace").strip())
        else:
            names.append(str(item).strip())
    return names


def _find_nearest_pixel(
    lat_arr: np.ndarray,
    lon_arr: np.ndarray,
    query_lat: float,
    query_lon: float,
    max_dist_deg: float = 0.1,
) -> tuple[int, int] | None:
    """Return (row, col) of the pixel nearest to (query_lat, query_lon).

    Returns None when the closest pixel is farther than max_dist_deg
    (roughly 11 km at equator for the default 0.1°).
    """
    dist2 = (lat_arr - query_lat) ** 2 + (lon_arr - query_lon) ** 2
    flat_idx = int(np.argmin(dist2))
    if float(dist2.flat[flat_idx]) > max_dist_deg**2:
        return None
    idx = np.unravel_index(flat_idx, lat_arr.shape)
    return (int(idx[0]), int(idx[1]))


def _extract_pixels_in_bbox(
    lat_arr: np.ndarray,
    lon_arr: np.ndarray,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> list[tuple[int, int]]:
    """Return (row, col) indices of all pixels whose coordinates fall inside the bbox."""
    mask = (lat_arr >= min_lat) & (lat_arr <= max_lat) & (lon_arr >= min_lon) & (lon_arr <= max_lon)
    rows, cols = np.where(mask)
    return list(zip(rows.tolist(), cols.tolist(), strict=True))


def _mineral_records_for_pixel(
    opendap_url: str,
    i: int,
    j: int,
    mineral_names: list[str],
    pixel_lat: float,
    pixel_lon: float,
    acq_date: str,
    gid: str,
    token: str,
) -> list[dict[str, Any]]:
    """Fetch spectral_abundance for a single pixel and return non-trace records."""
    n = len(mineral_names)
    # Step 2 — fetch only the single pixel [i:i][j:j] at all N mineral bands.
    # This request is ~1 KB regardless of scene size (files are 100–800 MB total).
    var_expr = f"/spectral_abundance[{i}:{i}][{j}:{j}][0:{n - 1}]"
    content = _fetch_opendap_nc4(opendap_url, var_expr, token)

    with h5py.File(io.BytesIO(content), "r") as hf:
        abund_ds = _get_dataset(hf, *_ABUNDANCE_PATHS)
        if abund_ds is None:
            return []
        abund = abund_ds[:].ravel()

    records: list[dict[str, Any]] = []
    for _k, (name, val) in enumerate(zip(mineral_names, abund, strict=False)):
        fval = float(val)
        if fval >= _ABUNDANCE_THRESHOLD and not np.isnan(fval):
            records.append(
                {
                    "mineral_name": name,
                    "abundance": round(fval, 4),
                    "units": "fractional (0–1)",
                    "latitude": round(float(pixel_lat), 6),
                    "longitude": round(float(pixel_lon), 6),
                    "acquisition_date": acq_date,
                    "granule_id": gid,
                }
            )
    return records


def _query_granule_point(
    opendap_url: str,
    query_lat: float,
    query_lon: float,
    acq_date: str,
    gid: str,
    token: str,
) -> list[dict[str, Any]]:
    """Query one EMIT granule for the nearest pixel to (query_lat, query_lon)."""
    # Step 1 — download lat, lon, mineral names
    var_expr1 = "/location/lat,/location/lon,/mineral_metadata/mineral_name"
    content1 = _fetch_opendap_nc4(opendap_url, var_expr1, token)

    with h5py.File(io.BytesIO(content1), "r") as hf:
        lat_ds = _get_dataset(hf, *_LAT_PATHS)
        lon_ds = _get_dataset(hf, *_LON_PATHS)
        nm_ds = _get_dataset(hf, *_MINERAL_NAME_PATHS)
        if lat_ds is None or lon_ds is None or nm_ds is None:
            return []
        lat_arr = lat_ds[:].astype(float)
        lon_arr = lon_ds[:].astype(float)
        mineral_names = _decode_mineral_names(nm_ds)

    pixel = _find_nearest_pixel(lat_arr, lon_arr, query_lat, query_lon)
    if pixel is None:
        return []

    i, j = pixel
    pixel_lat = float(lat_arr[i, j])
    pixel_lon = float(lon_arr[i, j])

    # Step 2 — download mineral abundance for this pixel
    return _mineral_records_for_pixel(
        opendap_url, i, j, mineral_names, pixel_lat, pixel_lon, acq_date, gid, token
    )


def _query_granule_bbox(
    opendap_url: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    acq_date: str,
    gid: str,
    token: str,
) -> list[dict[str, Any]]:
    """Query one EMIT granule for all pixels inside the bounding box.

    Fetches lat/lon/mineral-names in one request, identifies the matching
    pixels, then fetches a single rectangular OPeNDAP slice covering all of
    them — O(1) round-trips instead of O(N×M).
    """
    var_expr1 = "/location/lat,/location/lon,/mineral_metadata/mineral_name"
    content1 = _fetch_opendap_nc4(opendap_url, var_expr1, token)

    with h5py.File(io.BytesIO(content1), "r") as hf:
        lat_ds = _get_dataset(hf, *_LAT_PATHS)
        lon_ds = _get_dataset(hf, *_LON_PATHS)
        nm_ds = _get_dataset(hf, *_MINERAL_NAME_PATHS)
        if lat_ds is None or lon_ds is None or nm_ds is None:
            return []
        lat_arr = lat_ds[:].astype(float)
        lon_arr = lon_ds[:].astype(float)
        mineral_names = _decode_mineral_names(nm_ds)

    pixels = _extract_pixels_in_bbox(lat_arr, lon_arr, min_lat, max_lat, min_lon, max_lon)
    if not pixels:
        return []

    # Compute bounding rectangle of matched pixels and fetch it in one request.
    rows = [p[0] for p in pixels]
    cols = [p[1] for p in pixels]
    i_lo, i_hi = min(rows), max(rows)
    j_lo, j_hi = min(cols), max(cols)
    n = len(mineral_names)
    var_expr2 = f"/spectral_abundance[{i_lo}:{i_hi}][{j_lo}:{j_hi}][0:{n - 1}]"
    content2 = _fetch_opendap_nc4(opendap_url, var_expr2, token)

    with h5py.File(io.BytesIO(content2), "r") as hf:
        abund_ds = _get_dataset(hf, *_ABUNDANCE_PATHS)
        if abund_ds is None:
            return []
        abund = abund_ds[:]  # shape (i_hi-i_lo+1, j_hi-j_lo+1, n)

    records: list[dict[str, Any]] = []
    for i, j in pixels:
        ri, rj = i - i_lo, j - j_lo
        pixel_lat = float(lat_arr[i, j])
        pixel_lon = float(lon_arr[i, j])
        for name, val in zip(mineral_names, abund[ri, rj, :], strict=False):
            fval = float(val)
            if fval >= _ABUNDANCE_THRESHOLD and not np.isnan(fval):
                records.append(
                    {
                        "mineral_name": name,
                        "abundance": round(fval, 4),
                        "units": "fractional (0–1)",
                        "latitude": round(pixel_lat, 6),
                        "longitude": round(pixel_lon, 6),
                        "acquisition_date": acq_date,
                        "granule_id": gid,
                    }
                )
    return records


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
def emit_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Return EMIT L2B mineral spectral-abundance values at a point.

    Searches for EMIT scenes covering (latitude, longitude) within the given
    date range.  Each record is one detected mineral at one pixel.

    Requires ``EARTHDATA_TOKEN`` (free registration at
    https://urs.earthdata.nasa.gov/).  EMIT launched August 2022; queries
    before that date will return empty data.

    Args:
        latitude: WGS84 decimal latitude.
        longitude: WGS84 decimal longitude.
        start_date: Inclusive start, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end, ISO 8601 ``YYYY-MM-DD``.

    Returns:
        ``{"data": list[dict], "_meta": dict}`` — each record has
        ``mineral_name``, ``abundance`` (0–1 fraction), ``units``,
        ``latitude``, ``longitude``, ``acquisition_date``, ``granule_id``.
    """
    t0 = time.perf_counter()
    parse_date(start_date)
    parse_date(end_date)
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
    }
    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        return auth_missing_response(
            "emit",
            LICENSE_INFO,
            "EARTHDATA_TOKEN environment variable is not set. "
            "Register free at https://urs.earthdata.nasa.gov/ then generate "
            "a token under Profile → Generate Token.",
            query_params,
        )

    try:
        # Use a small bbox around the point so CMR spatial search works
        pad = 0.01
        granules = _cmr_search(
            longitude - pad,
            latitude - pad,
            longitude + pad,
            latitude + pad,
            start_date,
            end_date,
            token,
        )
        records: list[dict[str, Any]] = []
        for g in granules:
            url = _get_opendap_url(g)
            if not url:
                continue
            batch = _query_granule_point(
                url, latitude, longitude, _granule_date(g), _granule_id(g), token
            )
            records.extend(batch)
        latency = time.perf_counter() - t0
        return {
            "data": records,
            "_meta": build_meta(
                source="emit",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=True,
                success=True,
                variables=["spectral_abundance"],
                variable_info={"spectral_abundance": VARIABLE_INFO["spectral_abundance"]},
                error=(
                    "No EMIT granules found for this location and date range. "
                    "EMIT has sparse temporal coverage and does not observe the full globe daily."
                )
                if not records
                else None,
            ),
        }
    except ValueError as exc:
        latency = time.perf_counter() - t0
        err_str = str(exc)
        return {
            "data": [],
            "_meta": build_meta(
                source="emit",
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
def emit_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    limit: int = 500,
) -> dict[str, Any]:
    """Return EMIT L2B mineral spectral-abundance values within a bounding box.

    Args:
        min_lat: Southern boundary (WGS84 decimal degrees).
        max_lat: Northern boundary.
        min_lon: Western boundary.
        max_lon: Eastern boundary.
        start_date: Inclusive start, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end, ISO 8601 ``YYYY-MM-DD``.
        limit: Maximum number of records to return (default 500).
            ``_meta.capped`` is ``True`` when the cap was reached.

    Returns:
        ``{"data": list[dict], "_meta": dict}``
    """
    t0 = time.perf_counter()
    parse_date(start_date)
    parse_date(end_date)
    bbox = clamp_bbox(
        {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
    )
    query_params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
        **bbox,
    }

    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        return auth_missing_response(
            "emit",
            LICENSE_INFO,
            "EARTHDATA_TOKEN environment variable is not set. "
            "Register free at https://urs.earthdata.nasa.gov/ then generate "
            "a token under Profile → Generate Token.",
            query_params,
        )

    try:
        granules = _cmr_search(
            bbox["min_lon"],
            bbox["min_lat"],
            bbox["max_lon"],
            bbox["max_lat"],
            start_date,
            end_date,
            token,
        )
        records: list[dict[str, Any]] = []
        capped = False
        for g in granules:
            if len(records) >= limit:
                capped = True
                break
            url = _get_opendap_url(g)
            if not url:
                continue
            batch = _query_granule_bbox(
                url,
                bbox["min_lat"],
                bbox["max_lat"],
                bbox["min_lon"],
                bbox["max_lon"],
                _granule_date(g),
                _granule_id(g),
                token,
            )
            records.extend(batch)
        records = records[:limit]
        if not capped:
            capped = len(records) >= limit
        latency = time.perf_counter() - t0
        meta = build_meta(
            source="emit",
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info=LICENSE_INFO,
            auth_required=True,
            auth_present=True,
            success=True,
            variables=["spectral_abundance"],
            variable_info={"spectral_abundance": VARIABLE_INFO["spectral_abundance"]},
            error=("No EMIT granules found for this bbox and date range.") if not records else None,
        )
        meta["capped"] = capped
        return {"data": records, "_meta": meta}
    except ValueError as exc:
        latency = time.perf_counter() - t0
        err_str = str(exc)
        return {
            "data": [],
            "_meta": build_meta(
                source="emit",
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
