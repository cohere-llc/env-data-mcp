"""Query functions for the NASA EMIT adapter."""

from __future__ import annotations

import io
import re
from http import HTTPStatus
from typing import Any

import h5py
import httpx
import numpy as np

from ._constants import (
    CMR_GANULES_URL,
    COLLECTION_SHORT_NAME,
    FILL_MINERAL_ID,
    GROUP_VARS,
    LAT_PATHS,
    LON_PATHS,
    MINERAL_NAME_PATHS,
    PAGE_SIZE,
    QUERY_ARGS,
    VERSION,
    Granule,
)


def query_point(
    *,
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    token: str,
) -> list[dict[str, Any]]:
    # Use a small bbox around the point for CMR spatial search
    pad = 0.01  # deg
    granules = _query_granules(
        min_lat=latitude - pad,
        max_lat=latitude + pad,
        min_lon=longitude - pad,
        max_lon=longitude + pad,
        start_date=start_date,
        end_date=end_date,
        token=token,
    )
    records: list[dict[str, Any]] = []
    for g in granules:
        if not g.nc4_link:
            raise ValueError(f"Missing NetCDF URL for granule {g.id}")
        try:
            batch = _query_granule_point(
                granule=g,
                latitude=latitude,
                longitude=longitude,
                token=token,
            )
        except httpx.HTTPStatusError:
            # Some CMR-indexed granules aren't resolvable via OPeNDAP (reprocessed/removed).
            continue
        records.extend(batch)
    return records


def query_bbox(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    token: str,
) -> list[dict[str, Any]]:
    granules = _query_granules(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        start_date=start_date,
        end_date=end_date,
        token=token,
    )
    records: list[dict[str, Any]] = []
    for g in granules:
        if not g.nc4_link:
            raise ValueError(f"Missing NetCDF URL for granule {g.id}")
        try:
            batch = _query_granule_bbox(
                granule=g,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
                token=token,
            )
        except httpx.HTTPStatusError:
            # Some CMR-indexed granules aren't resolvable via OPeNDAP (reprocessed/removed).
            continue
        records.extend(batch)
    return records


# ---------------------------------------------------------------------------
# auth helper
# ---------------------------------------------------------------------------


def _build_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# granule helpers
# ---------------------------------------------------------------------------


def _query_granules(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    token: str,
) -> list[Granule]:
    """Return all EMIT L2B granules whose spatial footprint overlaps the bbox."""
    params = {
        "short_name": COLLECTION_SHORT_NAME,
        "version": VERSION,
        "bounding_box": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "temporal[]": f"{start_date}T00:00:00Z,{end_date}T23:59:59Z",
        "page_size": PAGE_SIZE,
        "sort_key": "start_date",
    }
    header = _build_headers(token=token)
    all_granules: list[Granule] = []
    search_after: str | None = None

    while True:
        req_headers = dict(header)
        if search_after is not None:
            req_headers["CMR-Search-After"] = search_after

        resp = httpx.get(
            url=CMR_GANULES_URL,
            params=params,
            headers=req_headers,
            timeout=30.0,
            follow_redirects=True,
        )
        if resp.status_code == HTTPStatus.UNAUTHORIZED:
            raise ValueError(
                "EarthData token rejected (HTTP 401). Token may be expired. "
                "Regenerate at https://urs.earthdata.nasa.gov/ > Profile > Generate Token "
                "and update EARTHDATA_TOKEN environment variable."
            )
        resp.raise_for_status()
        entries = resp.json().get("feed", {}).get("entry", [])
        granules = _parse_granules(entries)
        all_granules.extend(granules)

        search_after = resp.headers.get("CMR-Search-After")
        if not search_after or len(entries) < PAGE_SIZE:
            break

    return all_granules


def _parse_granules(raw: list[dict[str, Any]]) -> list[Granule]:
    return [
        Granule(
            id=g.get("producer_granule_id") or g.get("title", ""),
            date=_parse_granule_date(g.get("time_start", "")),
            nc4_link=_parse_granule_url(g.get("links", [])),
        )
        for g in raw
    ]


def _parse_granule_date(raw: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else raw[:10]


def _parse_granule_url(raw: list[dict[str, Any]]) -> str:
    for link in raw:
        rel = link.get("rel", "")
        href = link.get("href", "")
        if "opendap" in rel.lower() or "opendap" in href.lower():
            # Hyrax requires an explicit ".nc4" suffix to return a subsettable netCDF4/HDF5
            # response; the bare granule href returns an HTML landing page instead.
            base = re.sub(r"\.(dap|nc4|dmr|dds|das)$", "", href)
            return f"{base}.nc4"
    raise ValueError("Missing URL for granule data file")


def _fetch_nc4_file(base_url: str, var_expr: str, token: str) -> bytes:
    url = f"{base_url}?{var_expr}"
    resp = httpx.get(url, headers=_build_headers(token), timeout=120.0, follow_redirects=True)
    if resp.status_code == HTTPStatus.UNAUTHORIZED:
        raise ValueError(
            "EarthData token rejected (HTTP 401). Token may be expired. "
            "Regenerate at https://urs.earthdata.nasa.gov/ > Profile > Generate Token "
            "and update EARTHDATA_TOKEN environment variable."
        )
    resp.raise_for_status()
    return resp.content


def _get_dataset(hf: h5py.File, *paths: str) -> h5py.Dataset:
    """Try a sequence of HDF5 paths and return the first one that resolves."""
    for p in paths:
        try:
            obj = hf[p]
            if isinstance(obj, h5py.Dataset):
                return obj
        except KeyError:
            continue
    raise ValueError(f"No HDF5 dataset found in {paths}")


def _decode_mineral_names(ds: h5py.Dataset) -> list[str]:
    raw = ds[:]
    if raw.ndim == 2 and raw.dtype.kind == "S" and raw.dtype.itemsize == 1:
        # Fixed-width char matrix: one row of individual single-byte cells per name.
        names: list[str] = []
        for row in raw:
            joined = b"".join(row.tolist())
            names.append(joined.split(b"\x00")[0].decode("utf-8", errors="replace").strip())
        return names
    names = []
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
) -> tuple[int, int]:
    dist2 = (lat_arr - query_lat) ** 2 + (lon_arr - query_lon) ** 2
    flat_idx = int(np.argmin(dist2))
    idx = np.unravel_index(flat_idx, lat_arr.shape)
    return (int(idx[0]), int(idx[1]))


def _extract_pixels_in_bbox(
    *,
    lat_arr: np.ndarray,
    lon_arr: np.ndarray,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> list[tuple[int, int]]:
    mask = (lat_arr >= min_lat) & (lat_arr <= max_lat) & (lon_arr >= min_lon) & (lon_arr <= max_lon)
    (
        rows,
        cols,
    ) = np.where(mask)
    return list(zip(rows.tolist(), cols.tolist(), strict=True))


def _group_var_expr(i_lo: int, i_hi: int, j_lo: int, j_hi: int) -> str:
    """Build a constraint expression requesting group_1/group_2 mineral_id + band_depth.

    The Hyrax HTTP front end rejects literal '[' / ']' in the request line, so the
    array-slice brackets are percent-encoded.
    """
    dims = f"%5B{i_lo}:{i_hi}%5D%5B{j_lo}:{j_hi}%5D"
    return ",".join(f"{var}{dims}" for var in GROUP_VARS)


def _is_valid_detection(mineral_id: int, band_depth: float, n_minerals: int) -> bool:
    return mineral_id != FILL_MINERAL_ID and band_depth > 0.0 and 0 <= mineral_id < n_minerals


def _build_pixel_record(
    mineral_names: list[str],
    group_1_id: int,
    group_1_depth: float,
    group_2_id: int,
    group_2_depth: float,
    granule: Granule,
) -> dict[str, Any] | None:
    """Build one datetime record for a pixel; None if neither group has a positive detection.

    ``mineral_id == FILL_MINERAL_ID`` marks off-swath/masked pixels. Within the
    swath, a non-detection is reported as ``mineral_id == 0`` with
    ``band_depth == 0.0`` (~82% of pixels in a typical scene) rather than the
    fill value, so a positive band depth is required to treat a match as real.
    """
    record: dict[str, Any] = {"datetime": granule.date, "granule_id": granule.id}
    has_data = False
    if _is_valid_detection(group_1_id, group_1_depth, len(mineral_names)):
        record["group_1_mineral_name"] = mineral_names[group_1_id]
        record["group_1_band_depth"] = float(group_1_depth)
        record["group_1_band_depth_units"] = "unitless"
        has_data = True
    if _is_valid_detection(group_2_id, group_2_depth, len(mineral_names)):
        record["group_2_mineral_name"] = mineral_names[group_2_id]
        record["group_2_band_depth"] = float(group_2_depth)
        record["group_2_band_depth_units"] = "unitless"
        has_data = True
    return record if has_data else None


def _query_granule_point(
    *,
    granule: Granule,
    latitude: float,
    longitude: float,
    token: str,
) -> list[dict[str, Any]]:
    nc4_bytes = _fetch_nc4_file(granule.nc4_link, QUERY_ARGS, token)

    with h5py.File(io.BytesIO(nc4_bytes), "r") as hf:
        lat_ds = _get_dataset(hf, *LAT_PATHS)
        lon_ds = _get_dataset(hf, *LON_PATHS)
        mineral_ds = _get_dataset(hf, *MINERAL_NAME_PATHS)
        lat_arr = lat_ds[:].astype(float)
        lon_arr = lon_ds[:].astype(float)
        mineral_names = _decode_mineral_names(mineral_ds)

    i, j = _find_nearest_pixel(lat_arr, lon_arr, latitude, longitude)
    pixel_lat = float(lat_arr[i, j])
    pixel_lon = float(lon_arr[i, j])

    group_bytes = _fetch_nc4_file(granule.nc4_link, _group_var_expr(i, i, j, j), token)
    with h5py.File(io.BytesIO(group_bytes), "r") as hf:
        g1_id = int(_get_dataset(hf, GROUP_VARS[0])[0, 0])
        g1_bd = float(_get_dataset(hf, GROUP_VARS[1])[0, 0])
        g2_id = int(_get_dataset(hf, GROUP_VARS[2])[0, 0])
        g2_bd = float(_get_dataset(hf, GROUP_VARS[3])[0, 0])

    record = _build_pixel_record(mineral_names, g1_id, g1_bd, g2_id, g2_bd, granule)
    if record is None:
        return []
    return [
        {
            "geometry": {"type": "Point", "coordinates": [pixel_lon, pixel_lat]},
            "latitude": pixel_lat,
            "longitude": pixel_lon,
            "records": [record],
        }
    ]


def _query_granule_bbox(
    *,
    granule: Granule,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    token: str,
) -> list[dict[str, Any]]:
    nc4_bytes = _fetch_nc4_file(granule.nc4_link, QUERY_ARGS, token)

    with h5py.File(io.BytesIO(nc4_bytes), "r") as hf:
        lat_ds = _get_dataset(hf, *LAT_PATHS)
        lon_ds = _get_dataset(hf, *LON_PATHS)
        mineral_ds = _get_dataset(hf, *MINERAL_NAME_PATHS)
        lat_arr = lat_ds[:].astype(float)
        lon_arr = lon_ds[:].astype(float)
        mineral_names = _decode_mineral_names(mineral_ds)

    pixels = _extract_pixels_in_bbox(
        lat_arr=lat_arr,
        lon_arr=lon_arr,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )
    if not pixels:
        return []

    rows = [p[0] for p in pixels]
    cols = [p[1] for p in pixels]
    i_lo, i_hi = min(rows), max(rows)
    j_lo, j_hi = min(cols), max(cols)

    group_bytes = _fetch_nc4_file(granule.nc4_link, _group_var_expr(i_lo, i_hi, j_lo, j_hi), token)
    with h5py.File(io.BytesIO(group_bytes), "r") as hf:
        g1_id_arr = _get_dataset(hf, GROUP_VARS[0])[:]
        g1_bd_arr = _get_dataset(hf, GROUP_VARS[1])[:]
        g2_id_arr = _get_dataset(hf, GROUP_VARS[2])[:]
        g2_bd_arr = _get_dataset(hf, GROUP_VARS[3])[:]

    groups: list[dict[str, Any]] = []
    for i, j in pixels:
        ri, rj = i - i_lo, j - j_lo
        record = _build_pixel_record(
            mineral_names,
            int(g1_id_arr[ri, rj]),
            float(g1_bd_arr[ri, rj]),
            int(g2_id_arr[ri, rj]),
            float(g2_bd_arr[ri, rj]),
            granule,
        )
        if record is None:
            continue
        groups.append(
            {
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(lon_arr[i, j]), float(lat_arr[i, j])],
                },
                "latitude": float(lat_arr[i, j]),
                "longitude": float(lon_arr[i, j]),
                "records": [record],
            }
        )
    return groups
