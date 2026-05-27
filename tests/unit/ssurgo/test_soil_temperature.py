"""Unit tests for ssurgo_soil_temperature_* tools (Type 8)."""

from __future__ import annotations

import pytest

from env_data_mcp.models import AvailableVariablesResponse, GroupedGeometryResponse
from env_data_mcp.sources.ssurgo import (
    _NO_COVERAGE_MSG,
    ssurgo_soil_temperature_available_variables,
    ssurgo_soil_temperature_bbox_query,
    ssurgo_soil_temperature_query,
)
from env_data_mcp.sources.ssurgo.constants import (
    DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    _QueryType,
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
    SOIL_TEMP_XML,
    add_schema_responses,
)

# ---------------------------------------------------------------------------
# available_variables
# ---------------------------------------------------------------------------


def test_soil_temperature_available_variables_structure(httpx_mock):
    add_schema_responses(httpx_mock, _QueryType.SOIL_TEMPERATURE)
    result = ssurgo_soil_temperature_available_variables()
    AvailableVariablesResponse.model_validate(result)
    assert "data" in result
    assert "_meta" in result


def test_soil_temperature_available_variables_meta_query_type(httpx_mock):
    add_schema_responses(httpx_mock, _QueryType.SOIL_TEMPERATURE)
    result = ssurgo_soil_temperature_available_variables()
    assert result["_meta"]["query_params"]["query_type"] == "soil_temperature"


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_soil_temperature_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_temperature_available_variables()
    assert result["_meta"]["success"] is False
    assert result["data"] == {}


# ---------------------------------------------------------------------------
# point query
# ---------------------------------------------------------------------------


def test_soil_temperature_query_default_variables_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    GroupedGeometryResponse.model_validate(result)
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1


def test_soil_temperature_query_row_fields(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    group = result["data"][0]
    assert group["mukey"] == "2764208"
    row = group["records"][0]
    assert row["compname"] == "Ritzville"
    assert row["month"] == "January"
    assert row["soitempdept_r"] == "25"
    assert row["soitempmm"] == "2.5"


def test_soil_temperature_query_meta_query_type(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["query_params"]["query_type"] == "soil_temperature"


def test_soil_temperature_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert "variables" in qp


def test_soil_temperature_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=EMPTY_XML)
    result = ssurgo_soil_temperature_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_soil_temperature_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_soil_temperature_query_variable_info_in_meta(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    assert "variable_info" in result["_meta"]


def test_soil_temperature_default_variables_contains_expected():
    assert "month" in DEFAULT_SOIL_TEMPERATURE_VARIABLES
    assert "soitempmm" in DEFAULT_SOIL_TEMPERATURE_VARIABLES


# ---------------------------------------------------------------------------
# bbox query
# ---------------------------------------------------------------------------


def test_soil_temperature_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)


def test_soil_temperature_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    GroupedGeometryResponse.model_validate(result)
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1
