"""NASA POWER MERRA-2 and CERES SYN1deg data adapter.

Data source: Anonymous S3 Zarr at ``s3://nasa-power/``
Coverage: Global, 1980–present
Auth required: No

Future improvements:
- Could add datasets beyond MERRA-2 and SYN1deg:
| Prefix | Dataset | What it is |
|---|---|---|
|merra2|MERRA-2|NASA's flagship reanalysis, surface and upper-air variables, 1980–present.|
|flashflux|CERES FLASHFlux|Near-real-time solar radiation (~5–7 day latency)|
|geosit|GEOS-IT|Near-real-time meteorology; appended to MERRA-2's end (~2 day latency)|
|gwm|Global Water Model|Groundwater/hydrology|
|imerg|IMERG|High-res precipitation (0.1°, ~3.5 month latency for final run)|
|srb|SRB Release 4-IP|Legacy surface radiation budget (1984–2000 only)|
|syn1deg|CERES SYN1deg|Solar radiation at 1° grid (2001–present)|

"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
import zarr
from zarr.storage import FsspecStore

from env_data_mcp.helpers import bbox_area_deg2, build_meta, check_runtime, parse_date
from env_data_mcp.models import BboxInput
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# Types and constants
# ---------------------------------------------------------------------------
DEFAULT_MERRA2_VARIABLES = [
    "T2M",  # 2-meter air temperature
    "T2M_MAX",  # Daily maximum 2-meter air temperature
    "T2M_MIN",  # Daily minimum 2-meter air temperature
    "PRECTOTCORR",  # Total gauge-corrected precipitation
    "GWETROOT",  # Root-zone soil moisture
    "TSOIL1",  # Near-surface soil temperature
    "RH2M",  # 2-meter relative humidity
    "WS10M",  # 10-meter wind speed
]

DEFAULT_SYN1DEG_VARIABLES = [
    "ALLSKY_SFC_PAR_TOT",  # All-sky surface photosynthetically active radiation
    "ALLSKY_SFC_PAR_DIFF",  # All-sky surface photosynthetically active radiation diffuse fraction
    "ALLSKY_SFC_SW_DWN",  # All-sky surface downward shortwave radiation
    "ALLSKY_SFC_LW_DWN",  # All-sky surface downward longwave radiation
    "CLRSKY_SFC_PAR_TOT",  # Clear-sky surface photosynthetically active radiation
]


class DatasetType(Enum):
    MERRA2 = "merra2"
    SYN1DEG = "syn1deg"


class TemporalResolution(Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"
    ANNUAL = "annual"
    CLIMATOLOGY = "climatology"


# ---------------------------------------------------------------------------
# Licence and metadata
# ---------------------------------------------------------------------------

SOURCE_INFO: dict[str, str | list[str]] = {
    "license": (
        "There are no restrictions on the use, access, and/or download of data "
        "from the NASA POWER Project. We request that you cite the NASA POWER "
        "Project when using the data provided from NASA POWER Project. Public "
        "domain (NASA/US Government). Citation requested."
    ),
    "citation": (
        "NASA Prediction of Worldwide Energy Resources (POWER) was accessed on "
        "DATE from https://registry.opendata.aws/nasa-power. "
    ),
    "citation_urls": [
        "https://nasa-power.s3.amazonaws.com/CITATION.cff",
        "https://power.larc.nasa.gov/docs/methodology/citations/",
    ],
    "acknowledgments": (
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
    "description_url": "https://registry.opendata.aws/nasa-power/",
}

MERRA2_INFO: dict[str, str] = {
    "description": (
        "The Modern-Era Retrospective analysis for Research and Applications, "
        "Version 2 (MERRA-2) provides data beginning in 1980. It was introduced "
        "to replace the original MERRA dataset because of the advances made in "
        "the assimilation system that enable assimilation of modern hyperspectral "
        "radiance and microwave observations, along with GPS-Radio Occultation "
        "datasets. It also uses NASA's ozone profile observations that began in "
        "late 2004. Additional advances in both the GEOS model and the GSI "
        "assimilation system are included in MERRA-2. Spatial resolution remains "
        "about the same (about 50 km in the latitudinal direction) as in MERRA. "
        "Along with the enhancements in the meteorological assimilation, MERRA-2 "
        "takes some significant steps towards GMAO’s target of an Earth System "
        "reanalysis. MERRA-2 is the first long-term global reanalysis to assimilate "
        "space-based observations of aerosols and represent their interactions "
        "with other physical processes in the climate system. MERRA-2 includes a "
        "representation of ice sheets over (say) Greenland and Antarctica."
    ),
}

SYN1DEG_INFO: dict[str, str] = {
    "description": (
        "The CERES SYN1deg product provides global gridded estimates of surface "
        "radiation budget components at 1° resolution, derived from the CERES "
        "instrument's measurements of reflected solar and emitted thermal radiation. "
        "It includes variables such as all-sky and clear-sky downward shortwave "
        "and longwave radiation, which are critical for understanding Earth's energy "
        "balance and climate. The dataset covers the period from 2001 to the present, "
        "with updates typically released within a few months of data acquisition."
    ),
}

# ----------------------------------------------------------------------------
# Store URLs
# ----------------------------------------------------------------------------

_ZARR_URLS = {
    DatasetType.MERRA2: {
        TemporalResolution.HOURLY: "s3://nasa-power/merra2/spatial/power_merra2_hourly_spatial_utc.zarr",
        TemporalResolution.DAILY: "s3://nasa-power/merra2/spatial/power_merra2_daily_spatial_utc.zarr",
        TemporalResolution.MONTHLY: "s3://nasa-power/merra2/spatial/power_merra2_monthly_spatial_utc.zarr",
        TemporalResolution.ANNUAL: "s3://nasa-power/merra2/spatial/power_merra2_annual_spatial_utc.zarr",
        TemporalResolution.CLIMATOLOGY: "s3://nasa-power/merra2/spatial/power_merra2_climatology_spatial_utc.zarr",
    },
    DatasetType.SYN1DEG: {
        TemporalResolution.HOURLY: "s3://nasa-power/syn1deg/spatial/power_syn1deg_hourly_spatial_utc.zarr",
        TemporalResolution.DAILY: "s3://nasa-power/syn1deg/spatial/power_syn1deg_daily_spatial_utc.zarr",
        TemporalResolution.MONTHLY: "s3://nasa-power/syn1deg/spatial/power_syn1deg_monthly_spatial_utc.zarr",
        TemporalResolution.ANNUAL: "s3://nasa-power/syn1deg/spatial/power_syn1deg_annual_spatial_utc.zarr",
        TemporalResolution.CLIMATOLOGY: "s3://nasa-power/syn1deg/spatial/power_syn1deg_climatology_spatial_utc.zarr",
    },
}

# ----------------------------------------------------------------------------
# Module-level cache for opened Zarr stores and coordinate arrays.
# ----------------------------------------------------------------------------


class ZarrStoreCache:
    """Cache for opened Zarr stores and their coordinate arrays."""

    def __init__(self, group: zarr.Group) -> None:
        self._group: zarr.Group = group
        self._cached_dims_for_group: zarr.Group | None = None
        self._lats: np.ndarray | None = None
        self._lons: np.ndarray | None = None
        self._times: pd.DatetimeIndex | None = None
        self._cached_variables_for_group: zarr.Group | None = None
        self._variable_info: dict[str, dict[str, str]] | None = None


# Module level cache for each Zarr store, keyed by temporal resolution and dataset type
# (MERRA-2 vs SYN1deg).
_zarr_cache: dict[tuple[DatasetType, TemporalResolution], ZarrStoreCache] = {}


def _clear_store_cache() -> None:
    """Evict all cached Zarr stores. Useful in benchmarks to force fresh opens."""
    global _zarr_cache
    _zarr_cache.clear()


# ---------------------------------------------------------------------------
# Store access
# ---------------------------------------------------------------------------


def _open_store(
    dataset_type: DatasetType, temporal_resolution: TemporalResolution
) -> ZarrStoreCache:
    """Open (and cache) the NASA POWER Zarr store with an optional in-memory cache."""
    global _zarr_cache
    cache_key = (dataset_type, temporal_resolution)
    if cache_key in _zarr_cache:
        return _zarr_cache[cache_key]

    source = FsspecStore.from_url(
        _ZARR_URLS[dataset_type][temporal_resolution],
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

    _zarr_cache[(dataset_type, temporal_resolution)] = ZarrStoreCache(
        zarr.open_group(store=store, mode="r")
    )
    return _zarr_cache[(dataset_type, temporal_resolution)]


def _get_coordinates(store: ZarrStoreCache) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """Return (lats, lons, times) for *group*, loading them once and caching.

    The cache is keyed on group identity: a different group object (e.g. a test
    mock vs. the real S3 store) triggers a fresh read so the two never share
    cached coordinates.
    """
    if store._cached_dims_for_group is store._group:
        assert store._lats is not None
        assert store._lons is not None
        assert store._times is not None
        return store._lats, store._lons, store._times

    store._lats = np.asarray(store._group["lat"][:])  # type: ignore[arg-type]
    store._lons = np.asarray(store._group["lon"][:])  # type: ignore[arg-type]

    time_arr = store._group["time"]
    raw_times: np.ndarray = np.asarray(time_arr[:])  # type: ignore[arg-type]
    time_units: str = str(time_arr.attrs.get("units", ""))
    if time_units.startswith("days since "):
        origin = pd.Timestamp(time_units[len("days since ") :].split()[0])
        store._times = origin + pd.to_timedelta(raw_times.astype(float), unit="D")
    elif time_units.startswith("hours since "):
        origin = pd.Timestamp(time_units[len("hours since ") :].split()[0])
        store._times = origin + pd.to_timedelta(raw_times.astype(float), unit="h")
    else:
        # Fallback for mocks / legacy stores that have no units attribute.
        store._times = pd.to_datetime(raw_times.astype(float), unit="D")

    store._cached_dims_for_group = store._group
    return store._lats, store._lons, store._times


def _get_variable_info(store: ZarrStoreCache) -> dict[str, dict[str, str]]:
    """Return a dict of variable metadata for data variables in the group."""
    if store._cached_variables_for_group is store._group:
        assert store._variable_info is not None
        return store._variable_info

    coordinate_keys = {"lat", "lon", "time"}
    info: dict[str, dict[str, str]] = {}
    for var in store._group.array_keys():
        if var in coordinate_keys:
            continue
        arr = store._group[var]
        info[var] = {
            "long_name": str(arr.attrs.get("long_name", "")),
            "units": str(arr.attrs.get("units", "")),
        }
    store._variable_info = info
    store._cached_variables_for_group = store._group
    return store._variable_info


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

    Returns ``(records, unavailable_variables)`` where ``records`` is a list of
    dicts, one per day in the closed interval ``[start_date, end_date]``, and
    ``unavailable_variables`` is the list of requested variable names that were
    not found in the store.
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
    # zarr returns a numpy array for [i:j, i, j] slices.
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

    return records, unavailable


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
    Returns data for all points within the bounding box, as well as the nearest points
    outside the box in each direction (if they exist) to allow for interpolation at the edges.
    """
    store = _open_store(dataset_type, temporal_resolution)

    lats, lons, times = _get_coordinates(store)

    # lats and lons are sorted ascending in the MERRA-2/SYN1deg stores
    # Indices of the first cell >= min_lat and last cell <= max_lat
    first_lat = int(np.searchsorted(lats, min_lat, side="left"))
    last_lat = int(np.searchsorted(lats, max_lat, side="right"))

    # Expand by one buffer cell on each side, clamped to valid range
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
            row: dict[str, Any] = {
                "latitude": float(lats[lat_idx]),
                "longitude": float(lons[lon_idx]),
                "in_bbox": (min_lat <= lats[lat_idx] <= max_lat)
                and (min_lon <= lons[lon_idx] <= max_lon),
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
        n_time_steps = n_days // 30
    elif temporal_resolution == TemporalResolution.ANNUAL:
        n_time_steps = n_days // 365
    elif temporal_resolution == TemporalResolution.CLIMATOLOGY:
        n_time_steps = 1  # Climatology is typically a single time step per variable

    return check_runtime(
        source="nasa_power",
        n_days=n_time_steps,
        area_deg2=area_deg2,
        max_runtime_s=max_runtime_s,
        scale_factor=n_param,
    )


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def nasa_power_merra2_available_variables() -> dict[str, dict[str, str]]:
    """Return a list of available NASA POWER MERRA-2 variables with descriptions and units."""
    store = _open_store(DatasetType.MERRA2, TemporalResolution.DAILY)
    return _get_variable_info(store)


@mcp.tool()
def nasa_power_syn1deg_available_variables() -> dict[str, dict[str, str]]:
    """Return a list of available NASA POWER SYN1deg variables with descriptions and units."""
    store = _open_store(DatasetType.SYN1DEG, TemporalResolution.DAILY)
    return _get_variable_info(store)


@mcp.tool()
def nasa_power_merra2_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    temporal_resolution: TemporalResolution,
    variables: list[str] = DEFAULT_MERRA2_VARIABLES,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA POWER MERRA-2 climate data for a point location.

    Returns daily weather variables (temperature, precipitation, solar radiation,
    humidity, wind speed) from the NASA POWER dataset via anonymous S3/Zarr.
    Global coverage, 1980–present.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        start_date: ISO 8601 date string, e.g. "2019-08-15".
        end_date: ISO 8601 date string, inclusive.
        temporal_resolution: "hourly", "daily", "monthly", "annual", or "climatology".
        variables: NASA POWER variable names. Use nasa_power_merra2_available_variables()
            tool to get a list of valid variable names. Defaults to a standard set of commonly
            used variables.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """

    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "temporal_resolution": temporal_resolution.value,
        "max_runtime_s": max_runtime_s,
    }
    full_var_info = _get_variable_info(_open_store(DatasetType.MERRA2, temporal_resolution))
    var_info = {k: full_var_info[k] for k in variables if k in full_var_info}

    t0 = time.perf_counter()
    try:
        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        if warn := _estimate_query_runtime_s(
            n_days, temporal_resolution, len(variables), area_deg2=0.0, max_runtime_s=max_runtime_s
        ):
            return warn
        records, unavailable = _query_point(
            latitude,
            longitude,
            start_date,
            end_date,
            DatasetType.MERRA2,
            temporal_resolution,
            variables,
        )
        latency = time.perf_counter() - t0
        return {
            "data": records,
            "_meta": build_meta(
                source="nasa_power",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=SOURCE_INFO | MERRA2_INFO,
                variables=variables,
                variable_info=var_info,
                unavailable_variables=unavailable if unavailable else None,
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
                license_info=SOURCE_INFO | MERRA2_INFO,
                success=False,
                error=str(exc),
                variables=variables,
                variable_info=var_info,
            ),
        }


@mcp.tool()
def nasa_power_syn1deg_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    temporal_resolution: TemporalResolution,
    variables: list[str] = DEFAULT_SYN1DEG_VARIABLES,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA POWER SYN1deg surface radiation data for a point location.

    Returns daily surface radiation variables (shortwave and longwave, all-sky and clear-sky) from
    the NASA POWER dataset via anonymous S3/Zarr. Global coverage, 2001–present.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        start_date: ISO 8601 date string, e.g. "2019-08-15".
        end_date: ISO 8601 date string, inclusive.
        temporal_resolution: Temporal resolution of the data (e.g., daily, monthly).
        variables: NASA POWER SYN1deg variable names. Use nasa_power_syn1deg_available_variables()
            tool to get a list of valid variable names. Defaults to a standard set of commonly used
            surface radiation variables.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "temporal_resolution": temporal_resolution.value,
        "variables": variables,
        "max_runtime_s": max_runtime_s,
    }
    full_var_info = _get_variable_info(_open_store(DatasetType.SYN1DEG, temporal_resolution))
    var_info = {k: full_var_info[k] for k in variables if k in full_var_info}

    t0 = time.perf_counter()
    try:
        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        if warn := _estimate_query_runtime_s(
            n_days, temporal_resolution, len(variables), area_deg2=0.0, max_runtime_s=max_runtime_s
        ):
            return warn
        records, unavailable = _query_point(
            latitude,
            longitude,
            start_date,
            end_date,
            DatasetType.SYN1DEG,
            temporal_resolution,
            variables,
        )
        latency = time.perf_counter() - t0
        return {
            "data": records,
            "_meta": build_meta(
                source="nasa_power",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=SOURCE_INFO | SYN1DEG_INFO,
                variables=variables,
                variable_info=var_info,
                unavailable_variables=unavailable if unavailable else None,
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
                license_info=SOURCE_INFO | SYN1DEG_INFO,
                success=False,
                error=str(exc),
                variables=variables,
                variable_info=var_info,
            ),
        }


@mcp.tool()
def nasa_power_merra2_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    temporal_resolution: TemporalResolution,
    variables: list[str] = DEFAULT_MERRA2_VARIABLES,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA POWER MERRA-2 climate data for a bounding-box area.

    Returns values for points within the bounding box, as well as the nearest points outside
    the box in each direction (if they exist) to allow for interpolation at the edges.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        start_date: ISO 8601 start date.
        end_date: ISO 8601 end date (inclusive).
        temporal_resolution: Temporal resolution of the data (e.g., daily, monthly).
        variables: NASA POWER MERRA-2 variable names (defaults to standard set). Use
            nasa_power_merra2_available_variables() tool to get a list of valid variable names.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    bbox = BboxInput(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )  # validation and ordering checks

    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "temporal_resolution": temporal_resolution.value,
        "max_runtime_s": max_runtime_s,
    }

    full_var_info = _get_variable_info(_open_store(DatasetType.MERRA2, temporal_resolution))
    var_info = {k: full_var_info[k] for k in variables if k in full_var_info}
    t0 = time.perf_counter()
    try:
        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        if warn := _estimate_query_runtime_s(
            n_days,
            temporal_resolution,
            len(variables),
            area_deg2=bbox_area_deg2(bbox.model_dump()),
            max_runtime_s=max_runtime_s,
        ):
            return warn
        records, unavailable = _query_bbox(
            min_lat,
            max_lat,
            min_lon,
            max_lon,
            start_date,
            end_date,
            DatasetType.MERRA2,
            temporal_resolution,
            variables,
        )
        latency = time.perf_counter() - t0
        return {
            "data": records,
            "_meta": build_meta(
                source="nasa_power",
                query_params=query_params,
                rows_returned=sum(len(r["records"]) for r in records),
                latency_s=latency,
                license_info=SOURCE_INFO | MERRA2_INFO,
                variables=variables,
                variable_info=var_info,
                unavailable_variables=unavailable if unavailable else None,
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
                license_info=SOURCE_INFO | MERRA2_INFO,
                success=False,
                error=str(exc),
                variables=variables,
                variable_info=var_info,
            ),
        }


@mcp.tool()
def nasa_power_syn1deg_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    temporal_resolution: TemporalResolution,
    variables: list[str] = DEFAULT_SYN1DEG_VARIABLES,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA POWER SYN1deg surface radiation data for a bounding-box area.

    Returns values for points within the bounding box, as well as the nearest points outside
    the box in each direction (if they exist) to allow for interpolation at the edges.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        start_date: ISO 8601 start date.
        end_date: ISO 8601 end date (inclusive).
        temporal_resolution: Temporal resolution of the data (e.g., daily, monthly).
        variables: NASA POWER SYN1deg variable names (defaults to standard set). Use
            nasa_power_syn1deg_available_variables() tool to get a list of valid variable names.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    bbox = BboxInput(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )  # validation and ordering checks

    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "temporal_resolution": temporal_resolution.value,
        "max_runtime_s": max_runtime_s,
    }

    full_var_info = _get_variable_info(_open_store(DatasetType.SYN1DEG, temporal_resolution))
    var_info = {k: full_var_info[k] for k in variables if k in full_var_info}
    t0 = time.perf_counter()
    try:
        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        if warn := _estimate_query_runtime_s(
            n_days,
            temporal_resolution,
            len(variables),
            area_deg2=bbox_area_deg2(bbox.model_dump()),
            max_runtime_s=max_runtime_s,
        ):
            return warn
        records, unavailable = _query_bbox(
            min_lat,
            max_lat,
            min_lon,
            max_lon,
            start_date,
            end_date,
            DatasetType.SYN1DEG,
            temporal_resolution,
            variables,
        )
        latency = time.perf_counter() - t0
        return {
            "data": records,
            "_meta": build_meta(
                source="nasa_power",
                query_params=query_params,
                rows_returned=sum(len(r["records"]) for r in records),
                latency_s=latency,
                license_info=SOURCE_INFO | SYN1DEG_INFO,
                variables=variables,
                variable_info=var_info,
                unavailable_variables=unavailable if unavailable else None,
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
                license_info=SOURCE_INFO | SYN1DEG_INFO,
                success=False,
                error=str(exc),
                variables=variables,
                variable_info=var_info,
            ),
        }
