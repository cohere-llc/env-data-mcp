"""NASA POWER MERRA-2 climate data adapter.

Data source: Anonymous S3 Zarr at ``s3://nasa-power/``
Coverage: Global, 1981–present, 0.5° grid, daily
Auth required: No
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
import zarr
from zarr.storage import FsspecStore

from env_data_mcp.helpers import bbox_centroid, build_meta, clamp_bbox, parse_date
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# Licence and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "Public domain (NASA/US Government). Citation requested.",
    "license_url": "https://power.larc.nasa.gov/docs/methodology/citations/",
    "citation": (
        "The Prediction Of Worldwide Energy Resources (POWER) Project is funded "
        "through the National Aeronautics and Space Administration (NASA) Applied "
        "Sciences Program within the Earth Science Division of the Science Mission "
        "Directorate. The POWER team could not have completed this task without "
        "both technical and scientific inputs from the following Earth Science "
        "Division teams: The Surface Radiation Budget (SRB) and the Clouds and the "
        "Earth's Radiant Energy System (CERES) projects at NASA LaRC and the Global "
        "Modeling and Assimilation Office at the NASA Goddard Space Flight Center. "
        "The data obtained through the POWER web services was made possible with "
        "collaboration from the NASA Langley Research Center (LaRC) Atmospheric "
        "Science Data Center (ASDC)."
    ),
}

DEFAULT_VARIABLES: list[str] = [
    "T2M",
    "T10M",
    "PRECTOTCORR",
    "ALLSKY_SFC_SW_DWN",
    "RH2M",
    "WS2M",
]

# Plain-language descriptions and expected units for every variable this
# adapter may return.  Included in _meta.variable_info on every response so
# callers never need to look up abbreviations in external documentation.
VARIABLE_INFO: dict[str, dict[str, str]] = {
    "T2M": {
        "description": "Air temperature at 2 meters above ground",
        "units": "°C",
        "valid_range": "-90 to 60",
    },
    "T10M": {
        "description": "Air temperature at 10 meters above ground",
        "units": "°C",
        "valid_range": "-90 to 60",
    },
    "PRECTOTCORR": {
        "description": "Bias-corrected total precipitation (liquid + frozen)",
        "units": "mm/day",
        "valid_range": "0 to ~2000 (annual monsoon extremes)",
    },
    "ALLSKY_SFC_SW_DWN": {
        "description": "All-sky downwelling shortwave radiation at the surface",
        "units": "MJ/m²/day",
        "valid_range": "0 to ~40",
    },
    "RH2M": {
        "description": "Relative humidity at 2 meters above ground",
        "units": "%",
        "valid_range": "0 to 100",
    },
    "WS2M": {
        "description": "Wind speed at 2 meters above ground",
        "units": "m/s",
        "valid_range": "0 to ~100 (tropical cyclone extremes)",
    },
}

_ZARR_URL = "s3://nasa-power/merra2/spatial/power_merra2_daily_spatial_utc.zarr"

# Module-level store cache — opened once per process, then reused.
_cached_group: zarr.Group | None = None

# Coordinate arrays cached alongside the group — loading lat/lon/time on every
# query would redundantly re-read the same zarr chunks from S3.  The cache is
# keyed on the group object's identity so a different group (e.g. a test mock)
# always triggers a fresh read.
_cached_for_group: zarr.Group | None = None
_cached_lats: np.ndarray | None = None
_cached_lons: np.ndarray | None = None
_cached_times: pd.DatetimeIndex | None = None


# ---------------------------------------------------------------------------
# Store access
# ---------------------------------------------------------------------------


def _open_store() -> zarr.Group:
    """Open (and cache) the NASA POWER Zarr store with an optional in-memory cache."""
    global _cached_group
    if _cached_group is not None:
        return _cached_group

    source = FsspecStore.from_url(
        _ZARR_URL,
        read_only=True,
        storage_options={"anon": True},
    )
    try:
        from zarr.experimental.cache_store import CacheStore
        from zarr.storage import MemoryStore

        mem = MemoryStore()
        store: Any = CacheStore(store=source, cache_store=mem, max_size=256 * 1024 * 1024)
    except ImportError:
        store = source  # no caching if experimental module not available

    _cached_group = zarr.open_group(store=store, mode="r")
    return _cached_group


def _get_coordinates(group: zarr.Group) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """Return (lats, lons, times) for *group*, loading them once and caching.

    The cache is keyed on group identity: a different group object (e.g. a test
    mock vs. the real S3 store) triggers a fresh read so the two never share
    cached coordinates.
    """
    global _cached_for_group, _cached_lats, _cached_lons, _cached_times
    if _cached_for_group is group:
        assert _cached_lats is not None
        assert _cached_lons is not None
        assert _cached_times is not None
        return _cached_lats, _cached_lons, _cached_times

    _cached_lats = np.asarray(group["lat"][:])  # type: ignore[arg-type]
    _cached_lons = np.asarray(group["lon"][:])  # type: ignore[arg-type]

    time_arr = group["time"]
    raw_times: np.ndarray = np.asarray(time_arr[:])  # type: ignore[arg-type]
    time_units: str = str(time_arr.attrs.get("units", ""))
    if time_units.startswith("days since "):
        origin = pd.Timestamp(time_units[len("days since ") :].split()[0])
        _cached_times = origin + pd.to_timedelta(raw_times.astype("int64"), unit="D")
    else:
        # Fallback for mocks / legacy stores that have no units attribute.
        _cached_times = pd.to_datetime(raw_times, unit="D")

    _cached_for_group = group
    return _cached_lats, _cached_lons, _cached_times


# ---------------------------------------------------------------------------
# Core query logic (sync, testable without MCP)
# ---------------------------------------------------------------------------


def _query_point(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    variables: list[str],
) -> list[dict[str, Any]]:
    """Extract time-series records for a single point from the Zarr store.

    Returns a list of dicts, one per day in the closed interval
    ``[start_date, end_date]``.  Each dict contains a ``date`` key plus
    ``{VAR}`` and ``{VAR}_units`` keys for every variable found in the store.
    """
    group = _open_store()

    lats, lons, times = _get_coordinates(group)

    lat_idx = int(np.abs(lats - lat).argmin())
    lon_idx = int(np.abs(lons - lon).argmin())

    time_mask: np.ndarray = (times >= pd.to_datetime(start_date)) & (
        times <= pd.to_datetime(end_date)
    )
    selected_times = times[time_mask]

    # Narrow the time dimension to only the requested range before fetching from S3.
    # arr[:, lat_idx, lon_idx] would pull the entire 40+ year series; slicing first
    # limits the read to only the chunks that overlap the date window.
    time_indices = np.where(time_mask)[0]
    if len(time_indices) == 0:
        return []
    t_start = int(time_indices[0])
    t_end = int(time_indices[-1]) + 1

    # Pre-fetch each variable's 1-D time series for the (lat_idx, lon_idx) cell.
    # zarr returns a numpy array for [i:j, i, j] slices.
    variable_data: dict[str, tuple[np.ndarray, str]] = {}
    for var in variables:
        if var in group:
            arr = group[var]
            series: np.ndarray = np.asarray(arr[t_start:t_end, lat_idx, lon_idx])  # type: ignore[index]
            units: str = str(arr.attrs.get("units", "unknown"))
            variable_data[var] = (series, units)

    records: list[dict[str, Any]] = []
    for i, t_val in enumerate(selected_times):
        row: dict[str, Any] = {"date": t_val.strftime("%Y-%m-%d")}
        for var, (values, units) in variable_data.items():
            row[var] = float(values[i])
            row[f"{var}_units"] = units
        records.append(row)

    return records


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def nasa_power_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    variables: list[str] | None = None,
    temporal_resolution: str = "daily",
) -> dict[str, Any]:
    """Query NASA POWER MERRA-2 climate data for a point location.

    Returns daily weather variables (temperature, precipitation, solar radiation,
    humidity, wind speed) from the NASA POWER dataset via anonymous S3/Zarr.
    Global coverage, 1981–present, 0.5° grid resolution.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        start_date: ISO 8601 date string, e.g. "2019-08-15".
        end_date: ISO 8601 date string, inclusive.
        variables: NASA POWER variable names. Defaults to T2M, T10M,
            PRECTOTCORR, ALLSKY_SFC_SW_DWN, RH2M, WS2M.
        temporal_resolution: Only "daily" is supported in this version.
    """
    if variables is None:
        variables = DEFAULT_VARIABLES

    parse_date(start_date)
    parse_date(end_date)

    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "temporal_resolution": temporal_resolution,
    }

    var_info = {k: VARIABLE_INFO[k] for k in variables if k in VARIABLE_INFO}
    t0 = time.perf_counter()
    try:
        records = _query_point(latitude, longitude, start_date, end_date, variables)
        latency = time.perf_counter() - t0
        return {
            "data": records,
            "_meta": build_meta(
                source="nasa_power",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                variables=variables,
                variable_info=var_info,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="nasa_power",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
                variables=variables,
                variable_info=var_info,
            ),
        }


@mcp.tool()
def nasa_power_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    variables: list[str] | None = None,
    temporal_resolution: str = "daily",
) -> dict[str, Any]:
    """Query NASA POWER MERRA-2 climate data for a bounding-box area.

    Uses the centroid of the bounding box to extract the nearest grid cell.
    Bounding boxes exceeding 10° in either dimension are clamped with a warning.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        start_date: ISO 8601 start date.
        end_date: ISO 8601 end date (inclusive).
        variables: NASA POWER variable names (defaults to standard set).
        temporal_resolution: "daily" (default).
    """
    bbox = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }
    bbox = clamp_bbox(bbox)
    clat, clon = bbox_centroid(bbox)

    if variables is None:
        variables = DEFAULT_VARIABLES

    parse_date(start_date)
    parse_date(end_date)

    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "centroid_lat": clat,
        "centroid_lon": clon,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "temporal_resolution": temporal_resolution,
    }

    var_info = {k: VARIABLE_INFO[k] for k in variables if k in VARIABLE_INFO}
    t0 = time.perf_counter()
    try:
        records = _query_point(clat, clon, start_date, end_date, variables)
        latency = time.perf_counter() - t0
        return {
            "data": records,
            "_meta": build_meta(
                source="nasa_power",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                variables=variables,
                variable_info=var_info,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="nasa_power",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
                variables=variables,
                variable_info=var_info,
            ),
        }
