"""Shared fixtures and mock Zarr stores for NASA POWER unit tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import zarr
import zarr.storage

import env_data_mcp.sources.nasa_power._client as _client_mod
import env_data_mcp.sources.nasa_power._var_cache as _var_cache_mod
from env_data_mcp.sources.nasa_power._client import ZarrStoreCache
from env_data_mcp.sources.nasa_power.constants import DatasetType, TemporalResolution

# ---------------------------------------------------------------------------
# Grid constants shared across test modules
# ---------------------------------------------------------------------------

# Days since 1970-01-01 for 2019-08-17 through 2019-08-21
_BASE = pd.Timestamp("1970-01-01")
_DATES = pd.date_range("2019-08-17", periods=5)
_TIME_VALS = [int((d - _BASE).days) for d in _DATES]

# Yakima River test point — falls in the centre cell of the 3×3 mock grid
_LAT = 46.2531882
_LON = -119.4768203

# Mock grid: 3 lat × 3 lon at 0.5° (MERRA-2-like) resolution
_LATS = np.array([45.75, 46.25, 46.75], dtype="f4")
_LONS = np.array([-119.75, -119.25, -118.75], dtype="f4")

# Bbox that contains exactly the centre cell as interior; outer cells are buffer.
_BBOX_MIN_LAT = 46.1
_BBOX_MAX_LAT = 46.4
_BBOX_MIN_LON = -119.4
_BBOX_MAX_LON = -119.1

# ---------------------------------------------------------------------------
# Mock group factory
# ---------------------------------------------------------------------------


def _make_mock_group(variable_defs: dict[str, tuple[float, str, str]]) -> zarr.Group:
    """Build a minimal in-memory Zarr group mirroring the NASA POWER layout.

    Args:
        variable_defs: ``{name: (fill_value, units, description)}``

    Grid: 3 lat × 3 lon.  Time: 5 daily steps starting 2019-08-17.
    """
    store = zarr.storage.MemoryStore()
    g = zarr.open_group(store=store, mode="w")

    g.create_array("lat", data=_LATS)
    g.create_array("lon", data=_LONS)
    time_arr = g.create_array("time", data=np.array(_TIME_VALS, dtype="i4"))
    time_arr.attrs["units"] = "days since 1970-01-01"

    for name, (fill, units, description) in variable_defs.items():
        arr = g.create_array(name, data=np.full((5, 3, 3), fill, dtype="f4"))
        arr.attrs["units"] = units
        arr.attrs["long_name"] = description

    return g


# ---------------------------------------------------------------------------
# Module-level mock stores
# ---------------------------------------------------------------------------

_MOCK_MERRA2_GROUP = _make_mock_group(
    {
        "T2M": (20.0, "C", "Temperature at 2 Meters"),
        "T2M_MAX": (26.0, "C", "Temperature at 2 Meters Maximum"),
        "T2M_MIN": (14.0, "C", "Temperature at 2 Meters Minimum"),
        "PRECTOTCORR": (1.5, "mm/day", "Precipitation Corrected"),
        "RH2M": (65.0, "%", "Relative Humidity at 2 Meters"),
        "GWETROOT": (0.45, "1", "Root Zone Soil Wetness"),
        "TSOIL1": (22.0, "C", "Soil Temperatures Layer 1"),
    }
)

_MOCK_SYN1DEG_GROUP = _make_mock_group(
    {
        "ALLSKY_SFC_PAR_TOT": (105.0, "W/m^2", "All Sky Surface Total PAR"),
        "ALLSKY_SFC_PAR_DIFF": (40.0, "W/m^2", "All Sky Surface Diffuse PAR"),
        "ALLSKY_SFC_SW_DWN": (210.0, "W/m^2", "All Sky Surface Shortwave Downward Irradiance"),
        "ALLSKY_SFC_LW_DWN": (350.0, "W/m^2", "All Sky Surface Longwave Downward Irradiance"),
        "CLRSKY_SFC_PAR_TOT": (120.0, "W/m^2", "Clear Sky Surface Total PAR"),
    }
)

_MOCK_MERRA2_STORE = ZarrStoreCache(_MOCK_MERRA2_GROUP)
_MOCK_SYN1DEG_STORE = ZarrStoreCache(_MOCK_SYN1DEG_GROUP)

# ---------------------------------------------------------------------------
# Climatology mock store (13-step time axis: slots 1–13)
# ---------------------------------------------------------------------------

_CLIM_TIME_VALS = list(range(1, 14))


def _make_clim_group() -> zarr.Group:
    """Build a minimal in-memory Zarr group with CLIMATOLOGY time encoding."""
    mem = zarr.storage.MemoryStore()
    g = zarr.open_group(store=mem, mode="w")
    g.create_array("lat", data=_LATS)
    g.create_array("lon", data=_LONS)
    t_arr = g.create_array("time", data=np.array(_CLIM_TIME_VALS, dtype="i4"))
    t_arr.attrs["units"] = "days since 1970-01-01"
    arr = g.create_array(
        "T2M",
        data=np.arange(13 * 3 * 3, dtype="f4").reshape(13, 3, 3),
    )
    arr.attrs["units"] = "C"
    arr.attrs["long_name"] = "Temperature at 2 Meters"
    return g


_MOCK_CLIM_STORE = ZarrStoreCache(_make_clim_group())

# ---------------------------------------------------------------------------
# Hourly mock stores (24 h of 2019-08-19, 1 lat × 1 lon)
# ---------------------------------------------------------------------------

_EPOCH = pd.Timestamp("1970-01-01")
_HOURLY_DATE = "2019-08-19"
_HOURS_SINCE_EPOCH = int((pd.Timestamp(_HOURLY_DATE) - _EPOCH).total_seconds() // 3600)
_HOURLY_VALS_H = list(range(_HOURS_SINCE_EPOCH, _HOURS_SINCE_EPOCH + 24))
_HOURLY_VALS_D = [_HOURS_SINCE_EPOCH / 24 + h / 24 for h in range(24)]


def _make_hourly_group(time_vals: list, units: str) -> zarr.Group:
    """Build a 24-timestep, 1×1-grid in-memory Zarr group with the given time encoding."""
    store = zarr.storage.MemoryStore()
    g = zarr.open_group(store=store, mode="w")
    g.create_array("lat", data=np.array([46.25], dtype="f4"))
    g.create_array("lon", data=np.array([-119.25], dtype="f4"))
    t_arr = g.create_array("time", data=np.array(time_vals))
    t_arr.attrs["units"] = units
    v_arr = g.create_array("T2M", data=np.arange(24, dtype="f4").reshape(24, 1, 1))
    v_arr.attrs["units"] = "C"
    v_arr.attrs["long_name"] = "Temperature at 2 Meters"
    return g


_MOCK_HOURLY_H_GROUP = _make_hourly_group(_HOURLY_VALS_H, "hours since 1970-01-01")
_MOCK_HOURLY_D_GROUP = _make_hourly_group(_HOURLY_VALS_D, "days since 1970-01-01")
_MOCK_HOURLY_H_STORE = ZarrStoreCache(_MOCK_HOURLY_H_GROUP)
_MOCK_HOURLY_D_STORE = ZarrStoreCache(_MOCK_HOURLY_D_GROUP)

# ---------------------------------------------------------------------------
# Cache isolation fixture
# ---------------------------------------------------------------------------

_ALL_MOCK_STORES = (
    _MOCK_MERRA2_STORE,
    _MOCK_SYN1DEG_STORE,
    _MOCK_CLIM_STORE,
    _MOCK_HOURLY_H_STORE,
    _MOCK_HOURLY_D_STORE,
)


def _seed_mock_variable_info() -> None:
    """Populate the disk-backed cache with variables from the mock stores.

    Every (DatasetType, TemporalResolution) pair used by the tools is seeded
    so calls to ``_var_cache._get_variable_info`` return mock metadata without
    reading the shipped ``variables.json``.
    """
    merra2_info = _var_cache_mod._variable_info_from_group(_MOCK_MERRA2_GROUP)
    syn1deg_info = _var_cache_mod._variable_info_from_group(_MOCK_SYN1DEG_GROUP)
    for tr in TemporalResolution:
        _var_cache_mod._VARIABLE_INFO_CACHE[(DatasetType.MERRA2, tr)] = merra2_info
        _var_cache_mod._VARIABLE_INFO_CACHE[(DatasetType.SYN1DEG, tr)] = syn1deg_info


@pytest.fixture(autouse=True)
def _reset_caches():
    """Clear module-level and per-store caches so each test starts clean."""
    _client_mod._zarr_cache.clear()
    for store in _ALL_MOCK_STORES:
        store._cached_dims_for_group = None
        store._lats = None
        store._lons = None
        store._times = None
    _var_cache_mod._VARIABLE_INFO_CACHE.clear()
    _seed_mock_variable_info()
    yield
    _client_mod._zarr_cache.clear()
    _var_cache_mod._VARIABLE_INFO_CACHE.clear()
