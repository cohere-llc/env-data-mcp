"""Unit tests for ssurgo_area_summary_* tools (Type 2)."""

from __future__ import annotations

import pytest

from env_data_mcp.models import AvailableVariablesResponse, GroupedGeometryResponse
from env_data_mcp.sources.ssurgo import (
    LICENSE_INFO,
    ssurgo_area_summary_available_variables,
    ssurgo_area_summary_bbox_query,
    ssurgo_area_summary_query,
)
from env_data_mcp.sources.ssurgo.constants import _QueryType

from .conftest import (
    _LAT,
    _LON,
    _MAX_LAT,
    _MAX_LON,
    _MIN_LAT,
    _MIN_LON,
    _SDA_URL,
    AREA_SUMMARY_XML,
    EMPTY_XML,
    add_schema_responses,
)


def test_area_summary_available_variables_returns_variables_key(httpx_mock):
    add_schema_responses(httpx_mock, _QueryType.AREA_SUMMARY)
    result = ssurgo_area_summary_available_variables()
    AvailableVariablesResponse.model_validate(result)
    assert "data" in result
    assert "_meta" in result


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_area_summary_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_area_summary_available_variables()
    assert result["_meta"]["success"] is False
    assert result["data"] == {}


def test_area_summary_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    GroupedGeometryResponse.model_validate(result)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1


def test_area_summary_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    meta = result["_meta"]
    assert meta["source"] == "ssurgo"
    assert meta["success"] is True
    assert meta["auth_required"] is False


def test_area_summary_query_license_fields(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["license"] == LICENSE_INFO["license"]
    assert result["_meta"]["license_url"] == LICENSE_INFO["license_url"]


def test_area_summary_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert qp["longitude"] == pytest.approx(_LON)
    assert "variables" in qp


def test_area_summary_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=EMPTY_XML)
    result = ssurgo_area_summary_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] is None


def test_area_summary_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_area_summary_query_variable_info_in_meta(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    assert "variable_info" in result["_meta"]


def test_area_summary_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=AREA_SUMMARY_XML)
    result = ssurgo_area_summary_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)
    assert qp["max_lon"] == pytest.approx(_MAX_LON)


def test_area_summary_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=AREA_SUMMARY_XML)
    result = ssurgo_area_summary_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    GroupedGeometryResponse.model_validate(result)
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1
