"""Unit tests for the NASA POWER source adapter.

All tests are offline — the Zarr store is mocked with an in-memory group.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import zarr
from pydantic import ValidationError

import env_data_mcp.sources.nasa_power as _nasa_power_mod
from env_data_mcp.sources.nasa_power import (
    DEFAULT_MERRA2_VARIABLES,
    DEFAULT_SYN1DEG_VARIABLES,
    DatasetType,
    MERRA2_INFO,
    SOURCE_INFO,
    SYN1DEG_INFO,
    TemporalResolution,
    ZarrStoreCache,
    _CLIM_EPOCH,
    _clim_date_label,
    _clim_time_mask,
    _get_coordinates,
    _get_variable_info,
    _query_bbox,
    _query_point,
    nasa_power_merra2_available_variables,
    nasa_power_merra2_bbox_query,
    nasa_power_merra2_query,
    nasa_power_syn1deg_available_variables,
    nasa_power_syn1deg_bbox_query,
    nasa_power_syn1deg_query,
)

# ---------------------------------------------------------------------------
# Mock Zarr groups
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

# Bbox that contains exactly the centre cell as interior and uses the outer
# cells as buffer: lats [45.75, 46.25✓, 46.75], lons [-119.75, -119.25✓, -118.75]
_BBOX_MIN_LAT = 46.1
_BBOX_MAX_LAT = 46.4
_BBOX_MIN_LON = -119.4
_BBOX_MAX_LON = -119.1


def _make_mock_group(variable_defs: dict[str, tuple[float, str, str]]) -> zarr.Group:
    """Build a minimal in-memory Zarr group mirroring the NASA POWER layout.

    Args:
        variable_defs: ``{name: (fill_value, units, long_name)}``
    Grid: 3 lat × 3 lon. Time: 5 daily steps starting 2019-08-17.
    """
    store = zarr.storage.MemoryStore()
    g = zarr.open_group(store=store, mode="w")

    g.create_array("lat", data=_LATS)
    g.create_array("lon", data=_LONS)
    time_arr = g.create_array("time", data=np.array(_TIME_VALS, dtype="i4"))
    time_arr.attrs["units"] = "days since 1970-01-01"

    for name, (fill, units, long_name) in variable_defs.items():
        arr = g.create_array(name, data=np.full((5, 3, 3), fill, dtype="f4"))
        arr.attrs["units"] = units
        arr.attrs["long_name"] = long_name

    return g


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
# Cache isolation fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_caches():
    """Clear module-level and per-store caches so each test starts clean."""
    _nasa_power_mod._zarr_cache.clear()
    for store in (_MOCK_MERRA2_STORE, _MOCK_SYN1DEG_STORE, _MOCK_CLIM_STORE):
        store._cached_dims_for_group = None
        store._lats = None
        store._lons = None
        store._times = None
        store._cached_variables_for_group = None
        store._variable_info = None
    yield
    _nasa_power_mod._zarr_cache.clear()


# ---------------------------------------------------------------------------
# _get_coordinates tests
# ---------------------------------------------------------------------------


def test_get_coordinates_shapes():
    lats, lons, times = _get_coordinates(_MOCK_MERRA2_STORE)
    assert len(lats) == 3
    assert len(lons) == 3
    assert len(times) == 5


def test_get_coordinates_correct_dates():
    _, _, times = _get_coordinates(_MOCK_MERRA2_STORE)
    assert times[0] == pd.Timestamp("2019-08-17")
    assert times[-1] == pd.Timestamp("2019-08-21")


def test_get_coordinates_cached():
    """Second call returns the same array objects (no re-read)."""
    lats1, lons1, times1 = _get_coordinates(_MOCK_MERRA2_STORE)
    lats2, lons2, times2 = _get_coordinates(_MOCK_MERRA2_STORE)
    assert lats1 is lats2
    assert lons1 is lons2
    assert times1 is times2


# ---------------------------------------------------------------------------
# _get_variable_info tests
# ---------------------------------------------------------------------------


def test_get_variable_info_keys():
    info = _get_variable_info(_MOCK_MERRA2_STORE)
    assert "T2M" in info
    assert "PRECTOTCORR" in info


def test_get_variable_info_structure():
    info = _get_variable_info(_MOCK_MERRA2_STORE)
    assert info["T2M"]["units"] == "C"
    assert info["T2M"]["long_name"] == "Temperature at 2 Meters"


def test_get_variable_info_cached():
    info1 = _get_variable_info(_MOCK_MERRA2_STORE)
    info2 = _get_variable_info(_MOCK_MERRA2_STORE)
    assert info1 is info2


def test_get_variable_info_syn1deg():
    info = _get_variable_info(_MOCK_SYN1DEG_STORE)
    assert "ALLSKY_SFC_SW_DWN" in info
    assert "ALLSKY_SFC_LW_DWN" in info
    assert info["ALLSKY_SFC_SW_DWN"]["units"] == "W/m^2"


# ---------------------------------------------------------------------------
# _query_point tests
# ---------------------------------------------------------------------------


def test_query_point_returns_correct_date():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        records, _ = _query_point(
            _LAT, _LON, "2019-08-19", "2019-08-19",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    assert len(records) == 1
    assert records[0]["date"] == "2019-08-19"


def test_query_point_multi_day_range():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        records, _ = _query_point(
            _LAT, _LON, "2019-08-17", "2019-08-21",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    assert len(records) == 5


def test_query_point_variable_values():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        records, _ = _query_point(
            _LAT, _LON, "2019-08-19", "2019-08-19",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M", "PRECTOTCORR"],
        )
    assert pytest.approx(records[0]["T2M"], abs=1e-3) == 20.0
    assert pytest.approx(records[0]["PRECTOTCORR"], abs=1e-3) == 1.5


def test_query_point_units_present():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        records, _ = _query_point(
            _LAT, _LON, "2019-08-19", "2019-08-19",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M", "PRECTOTCORR"],
        )
    assert records[0]["T2M_units"] == "C"
    assert records[0]["PRECTOTCORR_units"] == "mm/day"


def test_query_point_unavailable_variable():
    """Variables absent from the store appear in unavailable_variables, not in records."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        records, unavailable = _query_point(
            _LAT, _LON, "2019-08-19", "2019-08-19",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M", "NONEXISTENT"],
        )
    assert "T2M" in records[0]
    assert "NONEXISTENT" not in records[0]
    assert "NONEXISTENT" in unavailable


def test_query_point_out_of_range_returns_empty():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        records, _ = _query_point(
            _LAT, _LON, "1960-01-01", "1960-01-03",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    assert records == []


def test_query_point_syn1deg_variable():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        records, _ = _query_point(
            _LAT, _LON, "2019-08-19", "2019-08-19",
            DatasetType.SYN1DEG, TemporalResolution.DAILY, ["ALLSKY_SFC_SW_DWN"],
        )
    assert pytest.approx(records[0]["ALLSKY_SFC_SW_DWN"], abs=0.1) == 210.0


# ---------------------------------------------------------------------------
# _query_bbox tests
#
# Mock grid: lats=[45.75, 46.25, 46.75], lons=[-119.75, -119.25, -118.75]
# _BBOX_* selects 46.25 / -119.25 as the single interior cell; the four
# surrounding cells are buffer.  Total = 3×3 = 9 grid-point dicts.
# ---------------------------------------------------------------------------


def test_query_bbox_returns_all_grid_points():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        results, _ = _query_bbox(
            _BBOX_MIN_LAT, _BBOX_MAX_LAT, _BBOX_MIN_LON, _BBOX_MAX_LON,
            "2019-08-17", "2019-08-21",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    assert len(results) == 9


def test_query_bbox_result_structure():
    """Each grid-point dict must have latitude, longitude, in_bbox, and records."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        results, _ = _query_bbox(
            _BBOX_MIN_LAT, _BBOX_MAX_LAT, _BBOX_MIN_LON, _BBOX_MAX_LON,
            "2019-08-17", "2019-08-17",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    for pt in results:
        assert "latitude" in pt
        assert "longitude" in pt
        assert "in_bbox" in pt
        assert isinstance(pt["records"], list)


def test_query_bbox_in_bbox_flag():
    """Only the centre cell (46.25, -119.25) should have in_bbox=True."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        results, _ = _query_bbox(
            _BBOX_MIN_LAT, _BBOX_MAX_LAT, _BBOX_MIN_LON, _BBOX_MAX_LON,
            "2019-08-17", "2019-08-17",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    interior = [pt for pt in results if pt["in_bbox"]]
    buffer_pts = [pt for pt in results if not pt["in_bbox"]]
    assert len(interior) == 1
    assert pytest.approx(interior[0]["latitude"], abs=0.01) == 46.25
    assert pytest.approx(interior[0]["longitude"], abs=0.01) == -119.25
    assert len(buffer_pts) == 8


def test_query_bbox_records_per_grid_point():
    """Each grid-point dict contains one record per day in the date range."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        results, _ = _query_bbox(
            _BBOX_MIN_LAT, _BBOX_MAX_LAT, _BBOX_MIN_LON, _BBOX_MAX_LON,
            "2019-08-17", "2019-08-21",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    for pt in results:
        assert len(pt["records"]) == 5


def test_query_bbox_record_fields():
    """Each record has date, variable value, and units."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        results, _ = _query_bbox(
            _BBOX_MIN_LAT, _BBOX_MAX_LAT, _BBOX_MIN_LON, _BBOX_MAX_LON,
            "2019-08-17", "2019-08-17",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    rec = results[0]["records"][0]
    assert rec["date"] == "2019-08-17"
    assert pytest.approx(rec["T2M"], abs=1e-3) == 20.0
    assert rec["T2M_units"] == "C"


def test_query_bbox_unavailable_variable():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        results, unavailable = _query_bbox(
            _BBOX_MIN_LAT, _BBOX_MAX_LAT, _BBOX_MIN_LON, _BBOX_MAX_LON,
            "2019-08-17", "2019-08-17",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M", "NONEXISTENT"],
        )
    assert "NONEXISTENT" in unavailable
    for pt in results:
        assert "NONEXISTENT" not in pt["records"][0]


def test_query_bbox_out_of_range_returns_empty():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        results, _ = _query_bbox(
            _BBOX_MIN_LAT, _BBOX_MAX_LAT, _BBOX_MIN_LON, _BBOX_MAX_LON,
            "1960-01-01", "1960-01-03",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    assert results == []


def test_query_bbox_all_cells_interior_when_bbox_covers_full_grid():
    """When the bbox exactly covers the full mock grid, all 9 cells are in_bbox."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        results, _ = _query_bbox(
            45.75, 46.75, -119.75, -118.75,
            "2019-08-17", "2019-08-17",
            DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
        )
    assert len(results) == 9
    assert all(pt["in_bbox"] for pt in results)


# ---------------------------------------------------------------------------
# nasa_power_merra2_query tool tests
# ---------------------------------------------------------------------------


def test_merra2_query_success_structure():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    assert "data" in result
    assert "_meta" in result
    assert isinstance(result["data"], list)
    assert len(result["data"]) == 1


def test_merra2_query_meta_fields():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    meta = result["_meta"]
    assert meta["source"] == "nasa_power"
    assert meta["success"] is True
    assert meta["error"] is None
    assert meta["rows_returned"] == 1
    assert meta["auth_required"] is False
    assert meta["license"] == SOURCE_INFO["license"]


def test_merra2_query_echoes_query_params():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-21",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == _LAT
    assert qp["longitude"] == _LON
    assert qp["start_date"] == "2019-08-19"
    assert qp["end_date"] == "2019-08-21"
    assert qp["temporal_resolution"] == "daily"  # enum serialised to string


def test_merra2_query_default_variables():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
        )
    assert result["_meta"]["variables"] == DEFAULT_MERRA2_VARIABLES


def test_merra2_query_invalid_date_returns_error():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="not-a-date", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_merra2_query_empty_date_range():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2000-01-01", end_date="2000-01-01",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["rows_returned"] == 0


def test_merra2_query_variable_info_in_meta():
    """variable_info is populated from Zarr array attrs for each requested variable."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M", "PRECTOTCORR"],
        )
    info = result["_meta"]["variable_info"]
    assert "T2M" in info
    assert "PRECTOTCORR" in info
    assert info["T2M"]["units"] == "C"
    assert info["T2M"]["long_name"] == "Temperature at 2 Meters"


def test_merra2_query_variable_info_only_requested_vars():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    info = result["_meta"]["variable_info"]
    assert "T2M" in info
    assert "PRECTOTCORR" not in info


def test_merra2_query_unavailable_variable_reported():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M", "NONEXISTENT"],
        )
    assert "NONEXISTENT" in result["_meta"]["unavailable_variables"]


def test_merra2_query_t2m_physical_range():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    t2m = result["data"][0]["T2M"]
    assert -90.0 <= t2m <= 60.0, f"T2M={t2m} outside physical range"


def test_merra2_query_precipitation_nonnegative():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-17", end_date="2019-08-21",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["PRECTOTCORR"],
        )
    for row in result["data"]:
        assert row["PRECTOTCORR"] >= 0.0, f"Negative precipitation: {row['PRECTOTCORR']}"


# ---------------------------------------------------------------------------
# nasa_power_syn1deg_query tool tests
# ---------------------------------------------------------------------------


def test_syn1deg_query_success_structure():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1


def test_syn1deg_query_meta_license():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert result["_meta"]["license"] == SOURCE_INFO["license"]


def test_syn1deg_query_default_variables():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
        )
    assert result["_meta"]["variables"] == DEFAULT_SYN1DEG_VARIABLES


def test_syn1deg_query_temporal_resolution_serialised():
    """temporal_resolution must appear as a plain string in query_params."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.MONTHLY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert result["_meta"]["query_params"]["temporal_resolution"] == "monthly"


def test_syn1deg_query_variable_values():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert pytest.approx(result["data"][0]["ALLSKY_SFC_SW_DWN"], abs=0.1) == 210.0


def test_syn1deg_query_variable_info_in_meta():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_query(
            latitude=_LAT, longitude=_LON,
            start_date="2019-08-19", end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    info = result["_meta"]["variable_info"]
    assert "ALLSKY_SFC_SW_DWN" in info
    assert info["ALLSKY_SFC_SW_DWN"]["units"] == "W/m^2"


# ---------------------------------------------------------------------------
# nasa_power_merra2_bbox_query tool tests
# ---------------------------------------------------------------------------


def test_merra2_bbox_query_returns_grid_points():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT, max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON, max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17", end_date="2019-08-21",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 9


def test_merra2_bbox_query_grid_point_structure():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT, max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON, max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17", end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    for pt in result["data"]:
        assert "latitude" in pt
        assert "longitude" in pt
        assert "in_bbox" in pt
        assert "records" in pt


def test_merra2_bbox_query_in_bbox_flag():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT, max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON, max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17", end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    interior = [pt for pt in result["data"] if pt["in_bbox"]]
    assert len(interior) == 1
    assert pytest.approx(interior[0]["latitude"], abs=0.01) == 46.25
    assert pytest.approx(interior[0]["longitude"], abs=0.01) == -119.25


def test_merra2_bbox_query_echoes_query_params():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT, max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON, max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17", end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    qp = result["_meta"]["query_params"]
    assert qp["min_lat"] == _BBOX_MIN_LAT
    assert qp["max_lat"] == _BBOX_MAX_LAT
    assert qp["temporal_resolution"] == "daily"


def test_merra2_bbox_query_invalid_bbox_raises():
    """Swapped min/max lat triggers BboxInput validation before any data access."""
    with pytest.raises(ValidationError):
        nasa_power_merra2_bbox_query(
            min_lat=47.0, max_lat=45.0,  # swapped — must fail
            min_lon=_BBOX_MIN_LON, max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17", end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
        )


# ---------------------------------------------------------------------------
# nasa_power_syn1deg_bbox_query tool tests
# ---------------------------------------------------------------------------


def test_syn1deg_bbox_query_returns_grid_points():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT, max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON, max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17", end_date="2019-08-21",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 9


def test_syn1deg_bbox_query_in_bbox_and_buffer():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT, max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON, max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17", end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    interior = [pt for pt in result["data"] if pt["in_bbox"]]
    buffer_pts = [pt for pt in result["data"] if not pt["in_bbox"]]
    assert len(interior) == 1
    assert len(buffer_pts) == 8


def test_syn1deg_bbox_query_variable_info():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT, max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON, max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17", end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert "ALLSKY_SFC_SW_DWN" in result["_meta"]["variable_info"]


def test_syn1deg_bbox_query_echoes_temporal_resolution():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT, max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON, max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17", end_date="2019-08-17",
            temporal_resolution=TemporalResolution.MONTHLY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert result["_meta"]["query_params"]["temporal_resolution"] == "monthly"


# ---------------------------------------------------------------------------
# available_variables tool tests
# ---------------------------------------------------------------------------


def test_merra2_available_variables_returns_dict():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
        result = nasa_power_merra2_available_variables()
    assert "T2M" in result
    assert "units" in result["T2M"]
    assert "long_name" in result["T2M"]


def test_syn1deg_available_variables_returns_dict():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_SYN1DEG_STORE):
        result = nasa_power_syn1deg_available_variables()
    assert "ALLSKY_SFC_SW_DWN" in result
    assert "units" in result["ALLSKY_SFC_SW_DWN"]


# ---------------------------------------------------------------------------
# HOURLY time-decode unit tests
# ---------------------------------------------------------------------------
# Helper to build compact hourly mock stores (24 h of 2019-08-19, 1 lat × 1 lon)

_EPOCH = pd.Timestamp("1970-01-01")
_HOURLY_DATE = "2019-08-19"
_HOURS_SINCE_EPOCH = int((pd.Timestamp(_HOURLY_DATE) - _EPOCH).total_seconds() // 3600)
# = 435024 for 2019-08-19 00:00 UTC
_HOURLY_VALS_H = list(range(_HOURS_SINCE_EPOCH, _HOURS_SINCE_EPOCH + 24))  # 24 integers
_HOURLY_VALS_D = [_HOURS_SINCE_EPOCH / 24 + h / 24 for h in range(24)]     # 24 fractional days


def _make_hourly_group(time_vals, units: str) -> zarr.Group:
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


_MOCK_HOURLY_H_GROUP = _make_hourly_group(_HOURLY_VALS_H, f"hours since 1970-01-01")
_MOCK_HOURLY_D_GROUP = _make_hourly_group(_HOURLY_VALS_D, f"days since 1970-01-01")
_MOCK_HOURLY_H_STORE = ZarrStoreCache(_MOCK_HOURLY_H_GROUP)
_MOCK_HOURLY_D_STORE = ZarrStoreCache(_MOCK_HOURLY_D_GROUP)


class TestHourlyTimeDecode:
    """_get_coordinates must produce 24 distinct hourly timestamps for both encodings."""

    def test_hours_since_returns_24_times(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_H_STORE)
        assert len(times) == 24

    def test_hours_since_first_timestamp(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_H_STORE)
        assert times[0] == pd.Timestamp("2019-08-19 00:00:00")

    def test_hours_since_last_timestamp(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_H_STORE)
        assert times[-1] == pd.Timestamp("2019-08-19 23:00:00")

    def test_hours_since_all_distinct(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_H_STORE)
        assert len(set(times)) == 24

    def test_fractional_days_returns_24_times(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_D_STORE)
        assert len(times) == 24

    def test_fractional_days_first_timestamp(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_D_STORE)
        assert times[0] == pd.Timestamp("2019-08-19 00:00:00")

    def test_fractional_days_last_timestamp(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_D_STORE)
        # fractional-day encoding has ~100ns float imprecision; check within 1 ms
        assert abs(times[-1] - pd.Timestamp("2019-08-19 23:00:00")) < pd.Timedelta("1ms")

    def test_fractional_days_all_distinct(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_D_STORE)
        assert len(set(times)) == 24


class TestHourlyQueryPoint:
    """_query_point must return 24 records for a single-day hourly query."""

    def test_single_day_returns_24_records(self):
        with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_HOURLY_H_STORE):
            records, _ = _query_point(
                46.25, -119.25,
                _HOURLY_DATE, _HOURLY_DATE,
                DatasetType.MERRA2, TemporalResolution.HOURLY, ["T2M"],
            )
        assert len(records) == 24

    def test_single_day_dates_are_distinct(self):
        with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_HOURLY_H_STORE):
            records, _ = _query_point(
                46.25, -119.25,
                _HOURLY_DATE, _HOURLY_DATE,
                DatasetType.MERRA2, TemporalResolution.HOURLY, ["T2M"],
            )
        dates = [r["date"] for r in records]
        assert len(set(dates)) == 24, "Hourly dates must include time component"

    def test_date_format_is_iso_datetime(self):
        with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_HOURLY_H_STORE):
            records, _ = _query_point(
                46.25, -119.25,
                _HOURLY_DATE, _HOURLY_DATE,
                DatasetType.MERRA2, TemporalResolution.HOURLY, ["T2M"],
            )
        assert records[0]["date"] == "2019-08-19T00:00:00"
        assert records[23]["date"] == "2019-08-19T23:00:00"

    def test_daily_date_format_unchanged(self):
        """Non-HOURLY resolutions still use %Y-%m-%d format."""
        with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_MERRA2_STORE):
            records, _ = _query_point(
                _LAT, _LON,
                "2019-08-19", "2019-08-19",
                DatasetType.MERRA2, TemporalResolution.DAILY, ["T2M"],
            )
        assert records[0]["date"] == "2019-08-19"


class TestHourlyQueryBbox:
    """_query_bbox must return 24 records per grid point for a single-day hourly query."""

    def test_single_day_returns_24_records_per_point(self):
        with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_HOURLY_H_STORE):
            results, _ = _query_bbox(
                46.0, 46.5, -119.5, -119.0,
                _HOURLY_DATE, _HOURLY_DATE,
                DatasetType.MERRA2, TemporalResolution.HOURLY, ["T2M"],
            )
        assert len(results) == 1  # 1×1 grid
        assert len(results[0]["records"]) == 24

    def test_bbox_record_date_format_is_iso_datetime(self):
        with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_HOURLY_H_STORE):
            results, _ = _query_bbox(
                46.0, 46.5, -119.5, -119.0,
                _HOURLY_DATE, _HOURLY_DATE,
                DatasetType.MERRA2, TemporalResolution.HOURLY, ["T2M"],
            )
        recs = results[0]["records"]
        assert recs[0]["date"] == "2019-08-19T00:00:00"
        assert recs[23]["date"] == "2019-08-19T23:00:00"


# ---------------------------------------------------------------------------
# Climatology helpers — pure unit tests (no I/O)
# ---------------------------------------------------------------------------

# 13-step climatology time axis: days since 1970-01-01 with values 1-13
# where 1-12 = month index (Jan=1..Dec=12) and 13 = annual mean.
_CLIM_TIME_VALS = list(range(1, 14))
_CLIM_TIMES = _CLIM_EPOCH + pd.to_timedelta(
    np.array(_CLIM_TIME_VALS, dtype="f4"), unit="D"
)


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


class TestClimDateLabel:
    """_clim_date_label returns human-readable labels for climatology slots."""

    def test_january(self):
        t = pd.Timestamp("1970-01-02")  # day=2 → slot 1 = January
        assert _clim_date_label(t) == "month-01"

    def test_december(self):
        t = pd.Timestamp("1970-01-13")  # day=13 → slot 12 = December
        assert _clim_date_label(t) == "month-12"

    def test_annual(self):
        t = pd.Timestamp("1970-01-14")  # day=14 → slot 13 = annual
        assert _clim_date_label(t) == "annual"

    def test_all_monthly_slots(self):
        for slot in range(1, 13):
            t = pd.Timestamp("1970-01-01") + pd.Timedelta(days=slot)
            assert _clim_date_label(t) == f"month-{slot:02d}"


class TestClimTimeMask:
    """_clim_time_mask filters climatology time steps by month range."""

    def test_full_year_includes_all_13(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2019-01-01", "2019-12-31")
        assert mask.sum() == 13

    def test_single_month_returns_month_plus_annual(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2019-08-01", "2019-08-31")
        assert mask.sum() == 2
        # August slot is index 7 (slot 8 - 1)
        assert mask[7]  # slot 8 = August
        assert mask[12]  # slot 13 = annual

    def test_summer_range_returns_3_months_plus_annual(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2019-06-01", "2019-08-31")
        assert mask.sum() == 4
        assert mask[5]   # slot 6 = June
        assert mask[6]   # slot 7 = July
        assert mask[7]   # slot 8 = August
        assert mask[12]  # slot 13 = annual

    def test_annual_slot_always_included(self):
        # Even a 1-day range must include the annual mean
        mask = _clim_time_mask(_CLIM_TIMES, "2019-03-15", "2019-03-15")
        assert mask[12]  # slot 13 = annual

    def test_partial_month_coverage_includes_boundary_months(self):
        # Starts mid-August, ends mid-September → both August and September included
        mask = _clim_time_mask(_CLIM_TIMES, "2019-08-15", "2019-09-10")
        assert mask.sum() == 3  # months 8, 9 + annual
        assert mask[7]   # August
        assert mask[8]   # September
        assert mask[12]  # annual

    def test_cross_year_wrap(self):
        # Nov 2019 → Feb 2020: months 11, 12, 1, 2 + annual
        mask = _clim_time_mask(_CLIM_TIMES, "2019-11-01", "2020-02-28")
        assert mask.sum() == 5
        assert mask[0]   # January
        assert mask[1]   # February
        assert mask[10]  # November
        assert mask[11]  # December
        assert mask[12]  # annual

    def test_multi_year_includes_all(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2018-06-01", "2020-08-31")
        assert mask.sum() == 13


class TestClimatologyQueryPoint:
    """_query_point returns correctly filtered + labelled records for CLIMATOLOGY."""

    def _query(self, start: str, end: str) -> list[dict]:
        with patch(
            "env_data_mcp.sources.nasa_power._open_store",
            return_value=_MOCK_CLIM_STORE,
        ):
            records, unavail = _query_point(
                _LAT, _LON, start, end,
                DatasetType.MERRA2, TemporalResolution.CLIMATOLOGY, ["T2M"],
            )
        assert unavail == []
        return records

    def test_full_year_returns_13_records(self):
        records = self._query("2019-01-01", "2019-12-31")
        assert len(records) == 13

    def test_single_month_returns_2_records(self):
        records = self._query("2019-08-01", "2019-08-31")
        assert len(records) == 2

    def test_date_labels_are_human_readable(self):
        records = self._query("2019-01-01", "2019-12-31")
        dates = {r["date"] for r in records}
        assert dates == {f"month-{m:02d}" for m in range(1, 13)} | {"annual"}

    def test_single_month_label(self):
        records = self._query("2019-08-01", "2019-08-31")
        dates = {r["date"] for r in records}
        assert dates == {"month-08", "annual"}

    def test_summer_range_returns_4_records(self):
        records = self._query("2019-06-01", "2019-08-31")
        assert len(records) == 4
        dates = {r["date"] for r in records}
        assert "month-06" in dates
        assert "month-07" in dates
        assert "month-08" in dates
        assert "annual" in dates


class TestClimatologyQueryBbox:
    """_query_bbox returns correctly filtered records for CLIMATOLOGY."""

    def _query(self, start: str, end: str) -> list[dict]:
        with patch(
            "env_data_mcp.sources.nasa_power._open_store",
            return_value=_MOCK_CLIM_STORE,
        ):
            results, unavail = _query_bbox(
                _BBOX_MIN_LAT, _BBOX_MAX_LAT, _BBOX_MIN_LON, _BBOX_MAX_LON,
                start, end,
                DatasetType.MERRA2, TemporalResolution.CLIMATOLOGY, ["T2M"],
            )
        assert unavail == []
        return results

    def test_full_year_returns_13_records_per_point(self):
        results = self._query("2019-01-01", "2019-12-31")
        for pt in results:
            assert len(pt["records"]) == 13

    def test_single_month_returns_2_records_per_point(self):
        results = self._query("2019-08-01", "2019-08-31")
        for pt in results:
            assert len(pt["records"]) == 2

    def test_date_labels_in_bbox_records(self):
        results = self._query("2019-01-01", "2019-12-31")
        interior = next(r for r in results if r["in_bbox"])
        dates = {rec["date"] for rec in interior["records"]}
        assert dates == {f"month-{m:02d}" for m in range(1, 13)} | {"annual"}
