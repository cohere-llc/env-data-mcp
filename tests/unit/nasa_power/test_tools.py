"""Unit tests for env_data_mcp.sources.nasa_power.tools."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from env_data_mcp.sources.nasa_power._constants import (
    DEFAULT_MERRA2_VARIABLES,
    DEFAULT_SYN1DEG_VARIABLES,
    SOURCE_INFO,
    TemporalResolution,
)
from env_data_mcp.sources.nasa_power.tools import (
    nasa_power_merra2_available_variables,
    nasa_power_merra2_bbox_query,
    nasa_power_merra2_point_query,
    nasa_power_syn1deg_available_variables,
    nasa_power_syn1deg_bbox_query,
    nasa_power_syn1deg_point_query,
)

from .conftest import (
    _BBOX_MAX_LAT,
    _BBOX_MAX_LON,
    _BBOX_MIN_LAT,
    _BBOX_MIN_LON,
    _LAT,
    _LON,
    _MOCK_MERRA2_STORE,
    _MOCK_SYN1DEG_STORE,
)

# ---------------------------------------------------------------------------
# Patch helpers: tools.py imports open_store from ._client directly, and
# _query.py does too, so both lookup paths must be patched for tool tests.
# ---------------------------------------------------------------------------

_PATCH_QUERY = "env_data_mcp.sources.nasa_power._query.open_store"
_PATCH_TOOLS = "env_data_mcp.sources.nasa_power._client.open_store"


@contextmanager
def _use_merra2():
    with (
        patch(_PATCH_QUERY, return_value=_MOCK_MERRA2_STORE),
        patch(_PATCH_TOOLS, return_value=_MOCK_MERRA2_STORE),
    ):
        yield


@contextmanager
def _use_syn1deg():
    with (
        patch(_PATCH_QUERY, return_value=_MOCK_SYN1DEG_STORE),
        patch(_PATCH_TOOLS, return_value=_MOCK_SYN1DEG_STORE),
    ):
        yield


# ---------------------------------------------------------------------------
# nasa_power_merra2_point_query tool tests
# ---------------------------------------------------------------------------


def test_merra2_query_success_structure():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    assert "data" in result
    assert "_meta" in result
    assert isinstance(result["data"], list)
    # One group (the snapped grid cell) with geometry and records
    assert len(result["data"]) == 1
    group = result["data"][0]
    assert "geometry" in group
    assert group["geometry"]["type"] == "Point"
    assert "records" in group
    assert len(group["records"]) == 1


def test_merra2_query_meta_fields():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    meta = result["_meta"]
    assert meta["source"] == "nasa_power"
    assert meta["success"] is True
    assert meta["error"] is None
    assert meta["geometries_returned"] == 1
    assert meta["total_records_returned"] == 1
    assert meta["auth_required"] is False
    assert meta["license"] == SOURCE_INFO["license"]


def test_merra2_query_echoes_query_params():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-21",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == _LAT
    assert qp["longitude"] == _LON
    assert qp["start_date"] == "2019-08-19"
    assert qp["end_date"] == "2019-08-21"
    assert qp["temporal_resolution"] == "daily"


def test_merra2_query_default_variables():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
        )
    assert result["_meta"]["variables"] == DEFAULT_MERRA2_VARIABLES


def test_merra2_query_invalid_date_returns_error():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="not-a-date",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_merra2_query_empty_date_range():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2000-01-01",
            end_date="2000-01-01",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["geometries_returned"] == 0
    assert result["_meta"]["total_records_returned"] == 0


def test_merra2_query_variable_info_in_meta():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M", "PRECTOTCORR"],
        )
    info = result["_meta"]["variable_info"]
    assert "T2M" in info
    assert "PRECTOTCORR" in info
    assert info["T2M"]["units"] == "C"
    assert info["T2M"]["description"] == "Temperature at 2 Meters"


def test_merra2_query_variable_info_only_requested_vars():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    info = result["_meta"]["variable_info"]
    assert "T2M" in info
    assert "PRECTOTCORR" not in info


def test_merra2_query_unavailable_variable_reported():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M", "NONEXISTENT"],
        )
    assert "NONEXISTENT" in result["_meta"]["unavailable_variables"]


def test_merra2_query_t2m_physical_range():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    t2m = result["data"][0]["records"][0]["T2M"]
    assert -90.0 <= t2m <= 60.0, f"T2M={t2m} outside physical range"


def test_merra2_query_precipitation_nonnegative():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-17",
            end_date="2019-08-21",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["PRECTOTCORR"],
        )
    for row in result["data"][0]["records"]:
        assert row["PRECTOTCORR"] >= 0.0, f"Negative precipitation: {row['PRECTOTCORR']}"


def test_merra2_query_slow_query_warning():
    with _use_merra2():
        result = nasa_power_merra2_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-17",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            max_runtime_s=0.0,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"].get("slow_query_warning") is True


# ---------------------------------------------------------------------------
# nasa_power_syn1deg_point_query tool tests
# ---------------------------------------------------------------------------


def test_syn1deg_query_success_structure():
    with _use_syn1deg():
        result = nasa_power_syn1deg_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1
    assert "geometry" in result["data"][0]
    assert "records" in result["data"][0]


def test_syn1deg_query_meta_license():
    with _use_syn1deg():
        result = nasa_power_syn1deg_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert result["_meta"]["license"] == SOURCE_INFO["license"]


def test_syn1deg_query_default_variables():
    with _use_syn1deg():
        result = nasa_power_syn1deg_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
        )
    assert result["_meta"]["variables"] == DEFAULT_SYN1DEG_VARIABLES


def test_syn1deg_query_temporal_resolution_serialised():
    with _use_syn1deg():
        result = nasa_power_syn1deg_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.MONTHLY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert result["_meta"]["query_params"]["temporal_resolution"] == "monthly"


def test_syn1deg_query_variable_values():
    with _use_syn1deg():
        result = nasa_power_syn1deg_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert pytest.approx(result["data"][0]["records"][0]["ALLSKY_SFC_SW_DWN"], abs=0.1) == 210.0


def test_syn1deg_query_variable_info_in_meta():
    with _use_syn1deg():
        result = nasa_power_syn1deg_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    info = result["_meta"]["variable_info"]
    assert "ALLSKY_SFC_SW_DWN" in info
    assert info["ALLSKY_SFC_SW_DWN"]["units"] == "W/m^2"


def test_syn1deg_query_invalid_date_returns_error():
    with _use_syn1deg():
        result = nasa_power_syn1deg_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="not-a-date",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_syn1deg_query_slow_query_warning():
    with _use_syn1deg():
        result = nasa_power_syn1deg_point_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-17",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            max_runtime_s=0.0,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"].get("slow_query_warning") is True


# ---------------------------------------------------------------------------
# nasa_power_merra2_bbox_query tool tests
# ---------------------------------------------------------------------------


def test_merra2_bbox_query_returns_grid_points():
    with _use_merra2():
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-21",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 9


def test_merra2_bbox_query_grid_point_structure():
    with _use_merra2():
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    for pt in result["data"]:
        assert "geometry" in pt
        assert pt["geometry"]["type"] == "Point"
        assert "latitude" in pt
        assert "longitude" in pt
        assert "in_bbox" in pt
        assert "records" in pt


def test_merra2_bbox_query_in_bbox_flag():
    with _use_merra2():
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["T2M"],
        )
    interior = [pt for pt in result["data"] if pt["in_bbox"]]
    assert len(interior) == 1
    assert pytest.approx(interior[0]["latitude"], abs=0.01) == 46.25
    assert pytest.approx(interior[0]["longitude"], abs=0.01) == -119.25


def test_merra2_bbox_query_echoes_query_params():
    with _use_merra2():
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-17",
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
            min_lat=47.0,
            max_lat=45.0,  # swapped — must fail
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
        )


def test_merra2_bbox_query_invalid_date_returns_error():
    with _use_merra2():
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="not-a-date",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_merra2_bbox_query_slow_query_warning():
    with _use_merra2():
        result = nasa_power_merra2_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            max_runtime_s=0.0,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"].get("slow_query_warning") is True


# ---------------------------------------------------------------------------
# nasa_power_syn1deg_bbox_query tool tests
# ---------------------------------------------------------------------------


def test_syn1deg_bbox_query_returns_grid_points():
    with _use_syn1deg():
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-21",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 9


def test_syn1deg_bbox_query_in_bbox_and_buffer():
    with _use_syn1deg():
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    interior = [pt for pt in result["data"] if pt["in_bbox"]]
    buffer_pts = [pt for pt in result["data"] if not pt["in_bbox"]]
    assert len(interior) == 1
    assert len(buffer_pts) == 8


def test_syn1deg_bbox_query_variable_info():
    with _use_syn1deg():
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-17",
            temporal_resolution=TemporalResolution.DAILY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert "ALLSKY_SFC_SW_DWN" in result["_meta"]["variable_info"]


def test_syn1deg_bbox_query_echoes_temporal_resolution():
    with _use_syn1deg():
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-17",
            temporal_resolution=TemporalResolution.MONTHLY,
            variables=["ALLSKY_SFC_SW_DWN"],
        )
    assert result["_meta"]["query_params"]["temporal_resolution"] == "monthly"


def test_syn1deg_bbox_query_invalid_date_returns_error():
    with _use_syn1deg():
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="not-a-date",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_syn1deg_bbox_query_slow_query_warning():
    with _use_syn1deg():
        result = nasa_power_syn1deg_bbox_query(
            min_lat=_BBOX_MIN_LAT,
            max_lat=_BBOX_MAX_LAT,
            min_lon=_BBOX_MIN_LON,
            max_lon=_BBOX_MAX_LON,
            start_date="2019-08-17",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            max_runtime_s=0.0,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"].get("slow_query_warning") is True


# ---------------------------------------------------------------------------
# available_variables tool tests
# ---------------------------------------------------------------------------


def test_merra2_available_variables_returns_dict():
    result = nasa_power_merra2_available_variables()
    assert "T2M" in result["data"]
    assert "units" in result["data"]["T2M"]
    assert "description" in result["data"]["T2M"]


def test_syn1deg_available_variables_returns_dict():
    result = nasa_power_syn1deg_available_variables()
    assert "ALLSKY_SFC_SW_DWN" in result["data"]
    assert "units" in result["data"]["ALLSKY_SFC_SW_DWN"]
    assert "description" in result["data"]["ALLSKY_SFC_SW_DWN"]
