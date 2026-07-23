"""Unit tests for ssurgo_parent_material_* tools (Type 7)."""

from __future__ import annotations

import pytest

from env_data_mcp.models import AvailableVariablesResponse, GroupedGeometryResponse
from env_data_mcp.sources.ssurgo import (
    ssurgo_parent_material_available_variables,
    ssurgo_parent_material_bbox_query,
    ssurgo_parent_material_point_query,
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
    PARENT_MAT_XML,
)

# ---------------------------------------------------------------------------
# available_variables
# ---------------------------------------------------------------------------


def test_parent_material_available_variables_returns_variables_key(httpx_mock):
    result = ssurgo_parent_material_available_variables()
    AvailableVariablesResponse.model_validate(result)
    assert "data" in result
    assert "_meta" in result


# ---------------------------------------------------------------------------
# point query
# ---------------------------------------------------------------------------


def test_parent_material_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=PARENT_MAT_XML)
    result = ssurgo_parent_material_point_query(latitude=_LAT, longitude=_LON)
    GroupedGeometryResponse.model_validate(result)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1


def test_parent_material_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=PARENT_MAT_XML)
    result = ssurgo_parent_material_point_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["source"] == "ssurgo"
    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is False


def test_parent_material_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=PARENT_MAT_XML)
    result = ssurgo_parent_material_point_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert "variables" in qp


def test_parent_material_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=EMPTY_XML)
    result = ssurgo_parent_material_point_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] is None


def test_parent_material_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_parent_material_point_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_parent_material_query_variable_info_in_meta(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=PARENT_MAT_XML)
    result = ssurgo_parent_material_point_query(latitude=_LAT, longitude=_LON)
    assert "variable_info" in result["_meta"]


# ---------------------------------------------------------------------------
# bbox query
# ---------------------------------------------------------------------------


def test_parent_material_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=PARENT_MAT_XML)
    result = ssurgo_parent_material_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)


def test_parent_material_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=PARENT_MAT_XML)
    result = ssurgo_parent_material_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    GroupedGeometryResponse.model_validate(result)
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1
