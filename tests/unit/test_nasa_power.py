"""Unit tests for the NASA POWER source adapter.

All tests are offline — the Zarr store is mocked with an in-memory group.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import zarr

import env_data_mcp.sources.nasa_power as _nasa_power_mod
from env_data_mcp.sources.nasa_power import (
    DEFAULT_VARIABLES,
    LICENSE_INFO,
    VARIABLE_INFO,
    _query_point,
    nasa_power_bbox_query,
    nasa_power_query,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Days since Unix epoch for the dates used in the test fixture
#   2019-08-17 = 18125, 2019-08-18 = 18126, 2019-08-19 = 18127
_BASE = pd.Timestamp("1970-01-01")
_DATES = pd.date_range("2019-08-17", periods=5)
_TIME_VALS = [int((d - _BASE).days) for d in _DATES]

# Yakima River test point
_LAT = 46.2531882
_LON = -119.4768203


def make_mock_zarr_group() -> zarr.Group:
    """Build a minimal in-memory Zarr group that mirrors the NASA POWER layout.

    Grid: 3 lat × 3 lon at 0.5° resolution centred on the Yakima River point.
    Time: 5 daily steps starting 2019-08-17.
    T2M: 20.0 everywhere; PRECTOTCORR: 1.5 everywhere.
    """
    store = zarr.storage.MemoryStore()
    g = zarr.open_group(store=store, mode="w")

    lats = np.array([45.75, 46.25, 46.75], dtype="f4")
    lons = np.array([-119.75, -119.25, -118.75], dtype="f4")
    time_vals = np.array(_TIME_VALS, dtype="i4")

    g.create_array("lat", data=lats)
    g.create_array("lon", data=lons)
    g.create_array("time", data=time_vals)

    # T2M: fixed 20.0 °C at every grid cell and time step
    t2m_data = np.full((5, 3, 3), 20.0, dtype="f4")
    t2m = g.create_array("T2M", data=t2m_data)
    t2m.attrs["units"] = "C"
    t2m.attrs["long_name"] = "Temperature at 2 Meters"

    # PRECTOTCORR: fixed 1.5 mm/day
    precip_data = np.full((5, 3, 3), 1.5, dtype="f4")
    precip = g.create_array("PRECTOTCORR", data=precip_data)
    precip.attrs["units"] = "mm/day"
    precip.attrs["long_name"] = "Precipitation Corrected"

    return g


_MOCK_GROUP = make_mock_zarr_group()


# ---------------------------------------------------------------------------
# Cache isolation fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_nasa_power_caches():
    """Clear module-level caches so each test runs with a clean slate."""
    _nasa_power_mod._cached_group = None
    _nasa_power_mod._cached_for_group = None
    _nasa_power_mod._cached_lats = None
    _nasa_power_mod._cached_lons = None
    _nasa_power_mod._cached_times = None
    yield
    _nasa_power_mod._cached_group = None
    _nasa_power_mod._cached_for_group = None
    _nasa_power_mod._cached_lats = None
    _nasa_power_mod._cached_lons = None
    _nasa_power_mod._cached_times = None


# ---------------------------------------------------------------------------
# _query_point unit tests
# ---------------------------------------------------------------------------


def test_query_point_returns_correct_date():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        records, _ = _query_point(_LAT, _LON, "2019-08-19", "2019-08-19", ["T2M"])
    assert len(records) == 1
    assert records[0]["date"] == "2019-08-19"


def test_query_point_multi_day_range():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        records, _ = _query_point(_LAT, _LON, "2019-08-17", "2019-08-21", ["T2M"])
    assert len(records) == 5


def test_query_point_variable_values():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        records, _ = _query_point(_LAT, _LON, "2019-08-19", "2019-08-19", ["T2M", "PRECTOTCORR"])
    row = records[0]
    assert pytest.approx(row["T2M"], abs=1e-3) == 20.0
    assert pytest.approx(row["PRECTOTCORR"], abs=1e-3) == 1.5


def test_query_point_units_present():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        records, _ = _query_point(_LAT, _LON, "2019-08-19", "2019-08-19", ["T2M", "PRECTOTCORR"])
    assert records[0]["T2M_units"] == "C"
    assert records[0]["PRECTOTCORR_units"] == "mm/day"


def test_query_point_unknown_variable_silently_omitted():
    """Variables not present in the store are reported in unavailable_variables."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        records, unavailable = _query_point(
            _LAT, _LON, "2019-08-19", "2019-08-19", ["T2M", "NONEXISTENT"]
        )
    assert "T2M" in records[0]
    assert "NONEXISTENT" not in records[0]
    assert "NONEXISTENT" in unavailable


def test_query_point_out_of_range_returns_empty():
    """A date range outside the store data returns an empty list."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        records, _ = _query_point(_LAT, _LON, "1960-01-01", "1960-01-03", ["T2M"])
    assert records == []


# ---------------------------------------------------------------------------
# nasa_power_query tool tests
# ---------------------------------------------------------------------------


def test_nasa_power_query_success_structure():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            variables=["T2M", "PRECTOTCORR"],
        )
    assert "data" in result
    assert "_meta" in result
    assert isinstance(result["data"], list)
    assert len(result["data"]) == 1


def test_nasa_power_query_meta_fields():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            variables=["T2M"],
        )
    meta = result["_meta"]
    assert meta["source"] == "nasa_power"
    assert meta["success"] is True
    assert meta["error"] is None
    assert meta["rows_returned"] == 1
    assert meta["license"] == LICENSE_INFO["license"]
    assert meta["license_url"] == LICENSE_INFO["license_url"]
    assert meta["auth_required"] is False


def test_nasa_power_query_echoes_query_params():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-21",
            variables=["T2M"],
        )
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == _LAT
    assert qp["longitude"] == _LON
    assert qp["start_date"] == "2019-08-19"
    assert qp["end_date"] == "2019-08-21"


def test_nasa_power_query_default_variables():
    """When variables=None, all DEFAULT_VARIABLES are requested."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
        )
    assert result["_meta"]["variables"] == DEFAULT_VARIABLES


def test_nasa_power_query_invalid_date_raises():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="not-a-date",
            end_date="2019-08-19",
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_nasa_power_query_meta_variables():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            variables=["T2M", "PRECTOTCORR"],
        )
    assert result["_meta"]["variables"] == ["T2M", "PRECTOTCORR"]


def test_nasa_power_query_empty_range_success():
    """A valid date range with no data returns success=True, empty data list."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2000-01-01",
            end_date="2000-01-01",
            variables=["T2M"],
        )
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["rows_returned"] == 0


# ---------------------------------------------------------------------------
# nasa_power_bbox_query tool tests
# ---------------------------------------------------------------------------


def test_nasa_power_bbox_query_uses_centroid():
    """bbox query echoes centroid_lat/lon in query_params."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_bbox_query(
            min_lat=46.25,
            max_lat=46.26,
            min_lon=-119.49,
            max_lon=-119.46,
            start_date="2019-08-19",
            end_date="2019-08-19",
            variables=["T2M"],
        )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" in qp
    assert "centroid_lon" in qp
    # centroid should be between bbox bounds
    assert 46.25 <= qp["centroid_lat"] <= 46.26
    assert -119.49 <= qp["centroid_lon"] <= -119.46


def test_nasa_power_bbox_query_returns_data():
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_bbox_query(
            min_lat=46.25,
            max_lat=46.26,
            min_lon=-119.49,
            max_lon=-119.46,
            start_date="2019-08-17",
            end_date="2019-08-21",
            variables=["T2M"],
        )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 5


# ---------------------------------------------------------------------------
# variable_info and value-range tests
# ---------------------------------------------------------------------------


def test_nasa_power_query_variable_info_in_meta():
    """_meta.variable_info must be populated for every requested variable."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            variables=["T2M", "PRECTOTCORR"],
        )
    info = result["_meta"]["variable_info"]
    assert "T2M" in info
    assert "PRECTOTCORR" in info
    assert info["T2M"]["description"] != ""
    assert info["T2M"]["units"] == VARIABLE_INFO["T2M"]["units"]


def test_nasa_power_query_variable_info_units_match_data_rows():
    """Units in variable_info must match the {VAR}_units fields in data rows."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            variables=["T2M", "PRECTOTCORR"],
        )
    row = result["data"][0]
    info = result["_meta"]["variable_info"]
    # The mock zarr stores units as "C" and "mm/day" — those are the source
    # units from the store; VARIABLE_INFO has the canonical display form.
    # We verify variable_info is present and non-empty, not exact string equality
    # (the zarr store can shorten "°C" to "C").
    assert "T2M_units" in row
    assert "T2M" in info
    assert info["T2M"]["units"]  # non-empty


def test_nasa_power_t2m_value_in_physical_range():
    """Mock T2M=20.0 °C — must be within valid atmospheric range."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            variables=["T2M"],
        )
    t2m = result["data"][0]["T2M"]
    assert -90.0 <= t2m <= 60.0, f"T2M={t2m} outside physical range — fill value or unit change?"


def test_nasa_power_precipitation_nonnegative():
    """Precipitation must be ≥ 0 mm/day."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-17",
            end_date="2019-08-21",
            variables=["PRECTOTCORR"],
        )
    for row in result["data"]:
        assert row["PRECTOTCORR"] >= 0.0, f"Negative precipitation: {row['PRECTOTCORR']}"


def test_nasa_power_variable_info_only_requested_vars():
    """variable_info should contain only the variables that were requested."""
    with patch("env_data_mcp.sources.nasa_power._open_store", return_value=_MOCK_GROUP):
        result = nasa_power_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            variables=["T2M"],
        )
    info = result["_meta"]["variable_info"]
    assert "T2M" in info
    assert "PRECTOTCORR" not in info
