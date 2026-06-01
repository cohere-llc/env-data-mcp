"""Core query logic for NASA POWER: climatology helpers and point/bbox data extraction."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from env_data_mcp.helpers import check_runtime

from ._client import _get_coordinates, _open_store
from .constants import DatasetType, TemporalResolution

# ---------------------------------------------------------------------------
# Climatology helpers
# ---------------------------------------------------------------------------

# Climatology time axis uses "days since 1970-01-01" with integer offsets 1–13.
# Offset 1 = January, 2 = February, …, 12 = December, 13 = Annual mean.
# All decoded timestamps therefore land in January 1970; month information
# is encoded in the *day* component: slot = (t - _CLIM_EPOCH).days  (1–13).
_CLIM_EPOCH = pd.Timestamp("1970-01-01")


def _clim_date_label(t_val: pd.Timestamp) -> str:
    """Human-readable date label for a climatology record.

    Returns ``"month-01"`` … ``"month-12"`` for monthly records and
    ``"annual"`` for the annual-mean record.
    """
    slot = (t_val - _CLIM_EPOCH).days
    return "annual" if slot > 12 else f"month-{slot:02d}"


def _clim_time_mask(
    times: pd.DatetimeIndex,
    start_date: str,
    end_date: str,
) -> np.ndarray:
    """Boolean mask selecting climatology time steps for a given date range.

    Rules:
    - The annual-mean record (slot 13) is **always** included.
    - If the date range spans at least 11 full month boundaries (i.e. covers
      12 distinct calendar months), all 12 monthly records are included.
    - Otherwise, months partially or fully covered by [start_date, end_date]
      are included.
    """
    slots = np.array([(t - _CLIM_EPOCH).days for t in times], dtype=int)
    annual_mask = slots > 12  # slot 13 = annual mean

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    month_span = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)

    if month_span >= 11:  # covers all 12 calendar months
        return np.ones(len(times), dtype=bool)

    sm, em = start_dt.month, end_dt.month
    monthly_mask = (slots >= sm) & (slots <= em) if sm <= em else (slots >= sm) | (slots <= em)

    return np.array(monthly_mask | annual_mask)


# ---------------------------------------------------------------------------
# Core query logic (sync, testable without MCP)
# ---------------------------------------------------------------------------


def _query_point(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    dataset_type: DatasetType,
    temporal_resolution: TemporalResolution,
    variables: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract time-series records for a single point from the Zarr store.

    Returns ``(groups, unavailable_variables)`` where ``groups`` is either an
    empty list (date range not in store) or a single-element list containing
    one ``GeometryGroup``-shaped dict with a GeoJSON ``Point`` geometry and
    the time-series ``records`` for the nearest grid cell.
    """
    store = _open_store(dataset_type, temporal_resolution)

    lats, lons, times = _get_coordinates(store)

    lat_idx = int(np.abs(lats - lat).argmin())
    lon_idx = int(np.abs(lons - lon).argmin())

    if temporal_resolution == TemporalResolution.CLIMATOLOGY:
        time_mask = _clim_time_mask(times, start_date, end_date)
    else:
        time_mask = (times >= pd.to_datetime(start_date)) & (
            times < pd.to_datetime(end_date) + pd.Timedelta(days=1)
        )
    selected_times = times[time_mask]

    # Narrow the time dimension to only the requested range before fetching from S3.
    # arr[:, lat_idx, lon_idx] would pull the entire 40+ year series; slicing first
    # limits the read to only the chunks that overlap the date window.
    time_indices = np.where(time_mask)[0]
    if len(time_indices) == 0:
        return [], []
    t_start = int(time_indices[0])
    t_end = int(time_indices[-1]) + 1

    # Pre-fetch each variable's 1-D time series for the (lat_idx, lon_idx) cell.
    variable_data: dict[str, tuple[np.ndarray, str]] = {}
    unavailable: list[str] = []
    for var in variables:
        if var in store._group:
            arr = store._group[var]
            series: np.ndarray = np.asarray(arr[t_start:t_end, lat_idx, lon_idx])  # type: ignore[index]
            units: str = str(arr.attrs.get("units", "unknown"))
            variable_data[var] = (series, units)
        else:
            unavailable.append(var)

    date_fmt = (
        "%Y-%m-%dT%H:%M:%S" if temporal_resolution == TemporalResolution.HOURLY else "%Y-%m-%d"
    )
    records: list[dict[str, Any]] = []
    for i, t_val in enumerate(selected_times):
        if temporal_resolution == TemporalResolution.CLIMATOLOGY:
            date_str = _clim_date_label(t_val)
        else:
            date_str = t_val.strftime(date_fmt)
        row: dict[str, Any] = {"date": date_str}
        for var, (values, units) in variable_data.items():
            row[var] = float(values[i])
            row[f"{var}_units"] = units
        records.append(row)

    snap_lat = float(lats[lat_idx])
    snap_lon = float(lons[lon_idx])
    return [
        {
            "geometry": {"type": "Point", "coordinates": [snap_lon, snap_lat]},
            "latitude": snap_lat,
            "longitude": snap_lon,
            "records": records,
        }
    ], unavailable


def _query_bbox(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    dataset_type: DatasetType,
    temporal_resolution: TemporalResolution,
    variables: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract time-series records for a bounding box from the Zarr store.

    Returns one ``GeometryGroup``-shaped dict per grid cell — cells both inside
    the bbox and the nearest buffer cell outside each edge — with a GeoJSON
    ``Point`` geometry and a ``records`` list of time-series dicts.  The extra
    ``in_bbox`` field indicates whether the cell falls strictly inside the
    requested bbox (useful for interpolation workflows).
    """
    store = _open_store(dataset_type, temporal_resolution)

    lats, lons, times = _get_coordinates(store)

    # lats and lons are sorted ascending in the MERRA-2/SYN1deg stores.
    # Indices of the first cell >= min_lat and last cell <= max_lat.
    first_lat = int(np.searchsorted(lats, min_lat, side="left"))
    last_lat = int(np.searchsorted(lats, max_lat, side="right"))

    # Expand by one buffer cell on each side, clamped to valid range.
    lat_start = max(0, first_lat - 1)
    lat_end = min(len(lats), last_lat + 1)

    first_lon = int(np.searchsorted(lons, min_lon, side="left"))
    last_lon = int(np.searchsorted(lons, max_lon, side="right"))

    lon_start = max(0, first_lon - 1)
    lon_end = min(len(lons), last_lon + 1)

    if temporal_resolution == TemporalResolution.CLIMATOLOGY:
        time_mask = _clim_time_mask(times, start_date, end_date)
    else:
        time_mask = (times >= pd.to_datetime(start_date)) & (
            times < pd.to_datetime(end_date) + pd.Timedelta(days=1)
        )
    selected_times = times[time_mask]

    # Narrow the time dimension to only the requested range before fetching from S3.
    time_indices = np.where(time_mask)[0]
    if len(time_indices) == 0:
        return [], []
    t_start = int(time_indices[0])
    t_end = int(time_indices[-1]) + 1

    variable_data: dict[str, tuple[np.ndarray, str]] = {}
    unavailable: list[str] = []
    for var in variables:
        if var in store._group:
            arr = store._group[var]
            # Resulting shape is (time, lat, lon) for the selected box + buffer
            data = np.asarray(arr[t_start:t_end, lat_start:lat_end, lon_start:lon_end])  # type: ignore[index]
            units: str = str(arr.attrs.get("units", "unknown"))
            variable_data[var] = (data, units)
        else:
            unavailable.append(var)

    date_fmt = (
        "%Y-%m-%dT%H:%M:%S" if temporal_resolution == TemporalResolution.HOURLY else "%Y-%m-%d"
    )
    results: list[dict[str, Any]] = []
    for i_lat, lat_idx in enumerate(range(lat_start, lat_end)):
        for i_lon, lon_idx in enumerate(range(lon_start, lon_end)):
            pt_lat = float(lats[lat_idx])
            pt_lon = float(lons[lon_idx])
            row: dict[str, Any] = {
                "geometry": {"type": "Point", "coordinates": [pt_lon, pt_lat]},
                "latitude": pt_lat,
                "longitude": pt_lon,
                "in_bbox": bool(
                    (min_lat <= lats[lat_idx] <= max_lat) and (min_lon <= lons[lon_idx] <= max_lon)
                ),
                "records": [],
            }
            for i_time, t_val in enumerate(selected_times):
                if temporal_resolution == TemporalResolution.CLIMATOLOGY:
                    date_str = _clim_date_label(t_val)
                else:
                    date_str = t_val.strftime(date_fmt)
                record: dict[str, Any] = {"date": date_str}
                for var, (values, units) in variable_data.items():
                    record[var] = float(values[i_time, i_lat, i_lon])
                    record[f"{var}_units"] = units
                row["records"].append(record)
            results.append(row)

    return results, unavailable


# ---------------------------------------------------------------------------
# Runtime estimation
# ---------------------------------------------------------------------------


def _estimate_query_runtime_s(
    n_days: int,
    temporal_resolution: TemporalResolution,
    n_param: int,
    area_deg2: float,
    max_runtime_s: float,
) -> dict[str, Any] | None:
    """Rough heuristic to estimate query runtime in seconds based on query size."""

    # The parameterization is based on daily resolution, so scale n_days accordingly
    # for other temporal resolutions.
    n_time_steps: int
    if temporal_resolution == TemporalResolution.HOURLY:
        n_time_steps = n_days * 24
    elif temporal_resolution == TemporalResolution.DAILY:
        n_time_steps = n_days
    elif temporal_resolution == TemporalResolution.MONTHLY:
        n_time_steps = 0 if n_days <= 0 else (n_days + 29) // 30
    elif temporal_resolution == TemporalResolution.ANNUAL:
        n_time_steps = 0 if n_days <= 0 else (n_days + 364) // 365
    elif temporal_resolution == TemporalResolution.CLIMATOLOGY:
        n_time_steps = 13  # 12 months + annual mean

    return check_runtime(
        source="nasa_power",
        n_days=n_time_steps,
        area_deg2=area_deg2,
        max_runtime_s=max_runtime_s,
        scale_factor=n_param,
    )
