"""Unit tests for env_data_mcp.sources.nasa_emit.tools."""

from __future__ import annotations

import re

import pytest

from env_data_mcp.sources.nasa_emit._constants import CMR_GANULES_URL
from env_data_mcp.sources.nasa_emit.tools import (
    _get_token,
    nasa_emit_bbox_query,
    nasa_emit_point_query,
)

from .conftest import _EMPTY_CMR_RESPONSE, _GRANULE_ID, _LAT, _LON, _TOKEN

# ---------------------------------------------------------------------------
# _get_token
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_set_token")
def test_get_token_available():
    token, error = _get_token({"foo": 12})
    assert token == _TOKEN
    assert error is None


@pytest.mark.usefixtures("_unset_token")
def test_get_token_unavailable():
    token, error = _get_token({"foo": 12})
    assert token == ""
    assert error is not None
    assert error["data"] == []
    assert error["_meta"]["query_params"] == {"foo": 12}
    assert error["_meta"]["auth_required"] is True
    assert error["_meta"]["auth_present"] is False
    assert error["_meta"]["success"] is False
    assert "EARTHDATA_TOKEN" in error["_meta"]["error"]


# ---------------------------------------------------------------------------
# nasa_emit_point_query
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_point_query_mock", "_set_token")
def test_nasa_emit_point_query():
    result = nasa_emit_point_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2023-08-01",
        end_date="2023-08-31",
        max_runtime_s=500,
    )
    assert len(result["data"]) == 1
    assert result["data"][0]["geometry"]["type"] == "Point"
    assert result["data"][0]["geometry"]["coordinates"] == [_LON, _LAT]
    assert result["data"][0]["latitude"] == _LAT
    assert result["data"][0]["longitude"] == _LON
    assert len(result["data"][0]["records"]) == 1
    assert result["data"][0]["records"][0]["granule_id"] == _GRANULE_ID
    assert result["_meta"]["source"] == "nasa_emit"
    assert result["_meta"]["geometries_returned"] == 1
    assert result["_meta"]["total_records_returned"] == 1
    assert result["_meta"]["auth_required"] is True
    assert result["_meta"]["auth_present"] is True
    assert result["_meta"]["success"] is True


@pytest.mark.usefixtures("_set_token")
def test_nasa_emit_point_query_no_granules(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(rf"^{re.escape(CMR_GANULES_URL)}.*"),
        json=_EMPTY_CMR_RESPONSE,
    )
    result = nasa_emit_point_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2023-08-01",
        end_date="2023-08-31",
        max_runtime_s=500,
    )
    assert result["data"] == []
    assert result["_meta"]["success"] is True
    assert result["_meta"]["geometries_returned"] == 0
    assert result["_meta"]["total_records_returned"] == 0


@pytest.mark.usefixtures("_unset_token")
def test_nasa_emit_point_query_no_auth():
    result = nasa_emit_point_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2023-08-01",
        end_date="2023-08-31",
    )
    assert result["data"] == []
    assert result["_meta"]["success"] is False
    assert "EARTHDATA_TOKEN" in result["_meta"]["error"]


# ---------------------------------------------------------------------------
# nasa_emit_bbox_query
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_bbox_query_mock", "_set_token")
def test_nasa_emit_bbox_query():
    result = nasa_emit_bbox_query(
        min_lat=_LAT - 1.0,
        max_lat=_LAT + 1.0,
        min_lon=_LON - 1.0,
        max_lon=_LON + 1.0,
        start_date="2023-08-01",
        end_date="2023-08-31",
        max_runtime_s=500,
    )
    assert len(result["data"]) == 3
    assert result["_meta"]["source"] == "nasa_emit"
    assert result["_meta"]["geometries_returned"] == 3
    assert result["_meta"]["total_records_returned"] == 3
    assert result["_meta"]["auth_required"] is True
    assert result["_meta"]["auth_present"] is True
    assert result["_meta"]["success"] is True


@pytest.mark.usefixtures("_set_token")
def test_nasa_emit_bbox_query_no_granules(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(rf"^{re.escape(CMR_GANULES_URL)}.*"),
        json=_EMPTY_CMR_RESPONSE,
    )
    result = nasa_emit_bbox_query(
        min_lat=_LAT - 1.0,
        max_lat=_LAT + 1.0,
        min_lon=_LON - 1.0,
        max_lon=_LON + 1.0,
        start_date="2023-08-01",
        end_date="2023-08-31",
        max_runtime_s=500,
    )
    assert result["data"] == []
    assert result["_meta"]["success"] is True
    assert result["_meta"]["geometries_returned"] == 0


@pytest.mark.usefixtures("_unset_token")
def test_nasa_emit_bbox_query_no_auth():
    result = nasa_emit_bbox_query(
        min_lat=_LAT - 1.0,
        max_lat=_LAT + 1.0,
        min_lon=_LON - 1.0,
        max_lon=_LON + 1.0,
        start_date="2023-08-01",
        end_date="2023-08-31",
    )
    assert result["data"] == []
    assert result["_meta"]["success"] is False
    assert "EARTHDATA_TOKEN" in result["_meta"]["error"]
