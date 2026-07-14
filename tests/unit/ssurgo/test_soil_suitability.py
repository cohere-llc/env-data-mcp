"""Unit tests for ssurgo_soil_suitability_* tools (Type 5)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field, ValidationError

from env_data_mcp.models import GroupedGeometryResponse, SuitabilityRulesResponse
from env_data_mcp.sources.ssurgo import (
    _NO_COVERAGE_MSG,
    ssurgo_soil_suitability_available_rule_names,
    ssurgo_soil_suitability_bbox_query,
    ssurgo_soil_suitability_query,
)

from .conftest import (
    _LAT,
    _LON,
    _MAX_LAT,
    _MAX_LON,
    _MIN_LAT,
    _MIN_LON,
    _SDA_URL,
    EMPTY_XML,
    RULES_XML,
    SUITABILITY_XML,
)


def test_soil_suitability_available_variables_returns_rule_names(httpx_mock):
    """available_variables for suitability returns flat 'rule_names' list, not 'variables'."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=RULES_XML)
    result = ssurgo_soil_suitability_available_rule_names()
    SuitabilityRulesResponse.model_validate(result)
    assert "data" in result
    assert "variables" not in result
    assert "_meta" in result
    assert len(result["data"]) == 3
    assert "ENG - Dwellings Without Basements" in result["data"]


def test_soil_suitability_available_variables_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=RULES_XML)
    result = ssurgo_soil_suitability_available_rule_names()
    assert result["_meta"]["success"] is True
    assert result["_meta"]["geometries_returned"] == 0
    assert result["_meta"]["total_records_returned"] == 3


def test_soil_suitability_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_suitability_available_rule_names()
    assert result["_meta"]["success"] is False
    assert result["data"] == []


def test_soil_suitability_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SUITABILITY_XML)
    result = ssurgo_soil_suitability_query(latitude=_LAT, longitude=_LON)
    GroupedGeometryResponse.model_validate(result)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1
    assert len(result["data"][0]["records"]) == 2


def test_soil_suitability_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SUITABILITY_XML)
    result = ssurgo_soil_suitability_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["source"] == "ssurgo"
    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is False


def test_soil_suitability_query_uses_rule_names_param(httpx_mock):
    """rule_names must be echoed in query_params (not 'variables')."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SUITABILITY_XML)
    custom_rules = ["ENG - Dwellings Without Basements"]
    result = ssurgo_soil_suitability_query(latitude=_LAT, longitude=_LON, rule_names=custom_rules)
    qp = result["_meta"]["query_params"]
    assert "rule_names" in qp
    assert "variables" not in qp
    assert qp["rule_names"] == custom_rules


def test_soil_suitability_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=EMPTY_XML)
    result = ssurgo_soil_suitability_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_soil_suitability_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_suitability_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_soil_suitability_query_invalid_rule_name_returns_error():
    """A rule name containing control characters must be rejected."""
    result = ssurgo_soil_suitability_query(
        latitude=_LAT,
        longitude=_LON,
        rule_names=["ENG - Dwellings\x00; DROP TABLE component"],
    )
    assert result["_meta"]["success"] is False
    assert "Invalid rule name" in result["_meta"]["error"]


def test_soil_suitability_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SUITABILITY_XML)
    result = ssurgo_soil_suitability_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)


def test_soil_suitability_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SUITABILITY_XML)
    result = ssurgo_soil_suitability_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    GroupedGeometryResponse.model_validate(result)
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1


# ---------------------------------------------------------------------------
# Edge-case / error paths (cover previously uncovered lines)
# ---------------------------------------------------------------------------


def test_soil_suitability_query_runtime_guard_returns_slow_query_warning():
    result = ssurgo_soil_suitability_query(latitude=_LAT, longitude=_LON, max_runtime_s=0)
    assert result["_meta"]["success"] is False
    assert result["_meta"].get("slow_query_warning") is True


def test_soil_suitability_query_non_finite_lat_raises_value_error():
    with pytest.raises(ValueError, match="finite"):
        ssurgo_soil_suitability_query(latitude=float("inf"), longitude=_LON)


def test_soil_suitability_query_out_of_range_lat_returns_error_response():
    result = ssurgo_soil_suitability_query(latitude=-95.0, longitude=_LON)
    assert result["_meta"]["success"] is False
    assert result["data"] == []
    assert "greater than or equal to -90" in result["_meta"]["error"]


def test_soil_suitability_bbox_query_runtime_guard_returns_slow_query_warning():
    result = ssurgo_soil_suitability_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON, max_runtime_s=0
    )
    assert result["_meta"]["success"] is False
    assert result["_meta"].get("slow_query_warning") is True


def test_soil_suitability_bbox_query_invalid_bbox_returns_error_response():
    result = ssurgo_soil_suitability_bbox_query(
        min_lat=_MIN_LAT,
        max_lat=_MAX_LAT,
        min_lon=_MAX_LON,
        max_lon=_MIN_LON,
    )
    assert result["_meta"]["success"] is False
    assert result["data"] == []
    assert "min_lon" in result["_meta"]["error"]


def test_soil_suitability_bbox_query_invalid_rule_name_returns_error():
    result = ssurgo_soil_suitability_bbox_query(
        min_lat=_MIN_LAT,
        max_lat=_MAX_LAT,
        min_lon=_MIN_LON,
        max_lon=_MAX_LON,
        rule_names=["ENG - Dwellings\x00; DROP TABLE component"],
    )
    assert result["_meta"]["success"] is False
    assert "Invalid rule name" in result["_meta"]["error"]


def test_soil_suitability_bbox_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_suitability_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_soil_suitability_query_pointinput_validationerror_branch_is_covered(monkeypatch):
    class _FailingPointModel(BaseModel):
        latitude: float = Field(le=90.0)

    def _raise_validation_error(**_kwargs):
        try:
            _FailingPointModel(latitude=91.0)
        except ValidationError as exc:
            raise exc

    monkeypatch.setattr("env_data_mcp.sources.ssurgo.tools.PointInput", _raise_validation_error)
    result = ssurgo_soil_suitability_query(latitude=46.0, longitude=-119.0)
    assert result["_meta"]["success"] is False
    assert result["data"] == []


def test_soil_suitability_bbox_query_bboxinput_validationerror_branch_is_covered(monkeypatch):
    class _FailingBboxModel(BaseModel):
        min_lat: float = Field(le=0.0)

    def _raise_validation_error(**_kwargs):
        try:
            _FailingBboxModel(min_lat=1.0)
        except ValidationError as exc:
            raise exc

    monkeypatch.setattr("env_data_mcp.sources.ssurgo.tools.BboxInput", _raise_validation_error)
    result = ssurgo_soil_suitability_bbox_query(
        min_lat=46.0,
        max_lat=46.5,
        min_lon=-120.0,
        max_lon=-119.5,
    )
    assert result["_meta"]["success"] is False
    assert result["data"] == []
