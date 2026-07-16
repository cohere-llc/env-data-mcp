"""Unit tests for ssurgo_soil_profile_* tools (Type 1)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field, ValidationError

from env_data_mcp.models import GroupedGeometryResponse
from env_data_mcp.sources.ssurgo import (
    LICENSE_INFO,
    ssurgo_soil_profile_available_variables,
    ssurgo_soil_profile_bbox_query,
    ssurgo_soil_profile_query,
)
from env_data_mcp.sources.ssurgo._client import _VARIABLE_INFO_CACHE
from env_data_mcp.sources.ssurgo.constants import _QueryType
from env_data_mcp.sources.ssurgo.tools import _bbox_query, _point_query

from .conftest import (
    _LAT,
    _LON,
    _MAX_LAT,
    _MAX_LON,
    _MIN_LAT,
    _MIN_LON,
    _SDA_URL,
    EMPTY_XML,
    YAKIMA_XML,
    add_schema_responses,
)


def test_soil_profile_available_variables_returns_variables_key(httpx_mock):
    add_schema_responses(httpx_mock, _QueryType.SOIL_PROFILE)
    result = ssurgo_soil_profile_available_variables()
    assert "data" in result
    assert "variables" not in result


def test_soil_profile_available_variables_entry_structure(httpx_mock):
    add_schema_responses(httpx_mock, _QueryType.SOIL_PROFILE)
    result = ssurgo_soil_profile_available_variables()
    assert "sandtotal_r" in result["data"]
    assert all("description" in e for e in result["data"].values())


def test_soil_profile_available_variables_meta_success(httpx_mock):
    add_schema_responses(httpx_mock, _QueryType.SOIL_PROFILE)
    result = ssurgo_soil_profile_available_variables()
    assert result["_meta"]["success"] is True
    assert result["_meta"]["geometries_returned"] == 0
    assert result["_meta"]["total_records_returned"] > 0


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_soil_profile_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_profile_available_variables()
    assert result["_meta"]["success"] is False
    assert result["data"] == {}


def test_soil_profile_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    GroupedGeometryResponse.model_validate(result)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1
    assert len(result["data"][0]["records"]) == 2
    group = result["data"][0]
    assert "mukey" in group
    assert "muname" in group


def test_soil_profile_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    meta = result["_meta"]
    assert meta["source"] == "ssurgo"
    assert meta["success"] is True
    assert meta["error"] is None
    assert meta["geometries_returned"] == 1
    assert meta["total_records_returned"] == 2
    assert meta["auth_required"] is False


def test_soil_profile_query_license_fields(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["license"] == LICENSE_INFO["license"]
    assert result["_meta"]["license_url"] == LICENSE_INFO["license_url"]


def test_soil_profile_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert qp["longitude"] == pytest.approx(_LON)
    assert "variables" in qp


def test_soil_profile_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=EMPTY_XML)
    result = ssurgo_soil_profile_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] is None


def test_soil_profile_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_soil_profile_query_variable_info_in_meta(httpx_mock):
    _VARIABLE_INFO_CACHE[_QueryType.SOIL_PROFILE] = {
        "sandtotal_r": {"table": "chorizon", "label": "Sand Total", "units": "%"},
    }
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    info = result["_meta"]["variable_info"]
    assert "sandtotal_r" in info
    assert info["sandtotal_r"]["description"] == "Sand Total"
    assert info["sandtotal_r"]["units"] == "%"
    assert "table" not in info["sandtotal_r"]


def test_soil_profile_query_sand_in_valid_range(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    for group in result["data"]:
        for row in group["records"]:
            sand = float(row["sandtotal_r"])
            assert 0.0 <= sand <= 100.0, f"sandtotal_r={sand} outside 0-100%"


def test_soil_profile_query_ph_in_valid_range(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    for group in result["data"]:
        for row in group["records"]:
            ph = float(row["ph1to1h2o_r"])
            assert 2.0 <= ph <= 11.0, f"ph1to1h2o_r={ph} outside 2-11"


def test_soil_profile_query_bulk_density_in_valid_range(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    for group in result["data"]:
        for row in group["records"]:
            bd = float(row["dbthirdbar_r"])
            assert 0.5 <= bd <= 2.0, f"dbthirdbar_r={bd} outside 0.5-2.0 g/cm3"


def test_soil_profile_query_custom_variables(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON, variables=["mukey", "awc_r"])
    assert result["_meta"]["success"] is True
    assert result["_meta"]["query_params"]["variables"] == ["mukey", "awc_r"]


def test_soil_profile_query_invalid_variable_returns_error():
    result = ssurgo_soil_profile_query(
        latitude=_LAT, longitude=_LON, variables=["mukey; DROP TABLE mapunit"]
    )
    assert result["_meta"]["success"] is False
    assert "Invalid variable name" in result["_meta"]["error"]


def test_soil_profile_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert "centroid_lon" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)
    assert qp["max_lon"] == pytest.approx(_MAX_LON)


def test_soil_profile_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    result = ssurgo_soil_profile_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    GroupedGeometryResponse.model_validate(result)
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1


# ---------------------------------------------------------------------------
# Edge-case / error paths (cover previously uncovered lines)
# ---------------------------------------------------------------------------


def test_soil_profile_query_runtime_guard_returns_slow_query_warning():
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON, max_runtime_s=0)
    assert result["_meta"]["success"] is False
    assert result["_meta"].get("slow_query_warning") is True


def test_soil_profile_query_non_finite_lat_raises_value_error():
    with pytest.raises(ValueError, match="finite"):
        ssurgo_soil_profile_query(latitude=float("nan"), longitude=_LON)


def test_soil_profile_query_out_of_range_lat_returns_error_response():
    result = ssurgo_soil_profile_query(latitude=95.0, longitude=_LON)
    assert result["_meta"]["success"] is False
    assert result["data"] == []
    assert "less than or equal to 90" in result["_meta"]["error"]


def test_soil_profile_bbox_query_runtime_guard_returns_slow_query_warning():
    result = ssurgo_soil_profile_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON, max_runtime_s=0
    )
    assert result["_meta"]["success"] is False
    assert result["_meta"].get("slow_query_warning") is True


def test_soil_profile_bbox_query_invalid_bbox_returns_error_response():
    result = ssurgo_soil_profile_bbox_query(
        min_lat=_MAX_LAT,
        max_lat=_MIN_LAT,
        min_lon=_MIN_LON,
        max_lon=_MAX_LON,
    )
    assert result["_meta"]["success"] is False
    assert result["data"] == []
    assert "min_lat" in result["_meta"]["error"]


def test_soil_profile_bbox_query_invalid_variable_returns_error():
    result = ssurgo_soil_profile_bbox_query(
        min_lat=_MIN_LAT,
        max_lat=_MAX_LAT,
        min_lon=_MIN_LON,
        max_lon=_MAX_LON,
        variables=["mukey; DROP TABLE mapunit"],
    )
    assert result["_meta"]["success"] is False
    assert "Invalid variable name" in result["_meta"]["error"]


def test_soil_profile_bbox_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_profile_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_point_query_pointinput_validationerror_branch_is_covered(monkeypatch):
    class _FailingPointModel(BaseModel):
        latitude: float = Field(le=90.0)

    def _raise_validation_error(**_kwargs):
        try:
            _FailingPointModel(latitude=91.0)
        except ValidationError as exc:
            raise exc

    monkeypatch.setattr("env_data_mcp.sources.ssurgo.tools.PointInput", _raise_validation_error)
    result = _point_query(
        latitude=46.0,
        longitude=-119.0,
        variables=["mukey"],
        sql_builder=lambda _wkt, _vars: "SELECT 1",
        max_runtime_s=None,
        query_type=_QueryType.SOIL_PROFILE,
    )
    assert result["_meta"]["success"] is False
    assert result["data"] == []


def test_bbox_query_bboxinput_validationerror_branch_is_covered(monkeypatch):
    class _FailingBboxModel(BaseModel):
        min_lat: float = Field(le=0.0)

    def _raise_validation_error(**_kwargs):
        try:
            _FailingBboxModel(min_lat=1.0)
        except ValidationError as exc:
            raise exc

    monkeypatch.setattr("env_data_mcp.sources.ssurgo.tools.BboxInput", _raise_validation_error)
    result = _bbox_query(
        min_lat=46.0,
        max_lat=46.5,
        min_lon=-120.0,
        max_lon=-119.5,
        variables=["mukey"],
        sql_builder=lambda _wkt, _vars: "SELECT 1",
        max_runtime_s=None,
        query_type=_QueryType.SOIL_PROFILE,
    )
    assert result["_meta"]["success"] is False
    assert result["data"] == []


def test_soil_profile_query_all_unknown_variables_returns_empty():
    _VARIABLE_INFO_CACHE[_QueryType.SOIL_PROFILE] = {
        "sandtotal_r": {"table": "chorizon", "label": "Sand Total", "units": "%"},
    }
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON, variables=["not_a_real_col"])
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert "not_a_real_col" in result["_meta"]["unavailable_variables"]
    assert result["_meta"]["variable_info"] == {}


def test_soil_profile_bbox_query_all_unknown_variables_returns_empty():
    _VARIABLE_INFO_CACHE[_QueryType.SOIL_PROFILE] = {
        "sandtotal_r": {"table": "chorizon", "label": "Sand Total", "units": "%"},
    }
    result = ssurgo_soil_profile_bbox_query(
        min_lat=_MIN_LAT,
        max_lat=_MAX_LAT,
        min_lon=_MIN_LON,
        max_lon=_MAX_LON,
        variables=["not_a_real_col"],
    )
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert "not_a_real_col" in result["_meta"]["unavailable_variables"]
    assert result["_meta"]["variable_info"] == {}
