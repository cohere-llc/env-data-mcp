"""Unit tests for the Sentinel 5-TROPOMI tools module.

All query functions are mocked via a ``unittest.mock.patch``; no network access required.
"""

from __future__ import annotations

from contextlib import contextmanager
from http import HTTPStatus
from unittest.mock import patch

import httpx
import pytest

from env_data_mcp.sources.tropomi.tools import (
    tropomi_available_variables,
    tropomi_bbox_query,
    tropomi_point_query,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_EXPECTED_VARIABLES: dict[str, dict[str, str]] = {
    "OFFL-foo": {
        "description": "foo with two underscores",
        "units": "foos",
        "variable_name": "foo__",
    },
    "NRTI-bar": {
        "description": "bar with four underscores",
        "units": "bars",
        "variable_name": "bar____",
    },
    "NRTI-baz_qux": {
        "description": "baz and qux with a whole lot of underscores",
        "units": "unknown",
        "variable_name": "baz___qux___________",
    },
}

_MOCK_VAR_INFO: dict[str, dict[str, str]] = {
    "OFFL-L2_O3": {"description": "Offline processed: Ozone", "units": "DU"},
    "OFFL-L2_NO2": {"description": "Offline processed: Nitrogen Dioxide", "units": "mol m-2"},
    "OFFL-L2_CO": {"description": "Offline processed: Carbon Monoxide", "units": "mol m-2"},
    "RPRO-L2_CO": {"description": "Reprocessed: Carbon Monoxide", "units": "mol m-2"},
}

_MOCK_GEO_POINT = {
    "geometry": {"type": "Point", "coordinates": [-116.49, 33.85]},
    "latitude": 33.85,
    "longitude": -116.49,
    "records": [{"date": "2024-01-03", "OFFL-L2_O3": 0.42}],
}

_MOCK_POINT_RESULT = [_MOCK_GEO_POINT]

_MOCK_BBOX_RESULT = [
    _MOCK_GEO_POINT,
    {
        "geometry": {"type": "Point", "coordinates": [-116.44, 33.90]},
        "latitude": 33.90,
        "longitude": -116.44,
        "records": [{"date": "2024-01-03", "OFFL-L2_O3": 0.38}],
    },
]

# A well-formed slow-query warning dict (as returned by helpers.check_runtime).
_SLOW_WARN = {
    "data": [],
    "_meta": {
        "source": "tropomi",
        "success": False,
        "slow_query_warning": True,
        "estimated_runtime_s": 100.0,
        "threshold_s": 72.0,
        "message": (
            "Estimated runtime 100.0s exceeds the 72.0s threshold."
            " Pass max_runtime_s=126 to allow this query to proceed."
        ),
        "geometries_returned": 0,
        "total_records_returned": 0,
        "latency_s": 0.0,
        "query_params": {},
        "auth_required": False,
        "auth_present": True,
        "license": "",
        "license_url": "",
        "citation": "",
        "citation_urls": [],
        "description": "",
        "description_url": "",
        "acknowledgements": "",
        "variables": [],
        "variable_info": {},
        "unavailable_variables": [],
        "error": (
            "Estimated runtime 100.0s exceeds the 72.0s threshold."
            " Pass max_runtime_s=126 to allow this query to proceed."
        ),
    },
}


def get_mock_http_error():
    request = httpx.Request("GET", "https://meeo-s5p.s3.amazonaws.com")
    response = httpx.Response(HTTPStatus.SERVICE_UNAVAILABLE, request=request)
    return httpx.HTTPStatusError(
        "503 Service Unavailable",
        request=request,
        response=response,
    )


@contextmanager
def _mock_point_query(data=_MOCK_POINT_RESULT, unavailable=None, substituted=None):
    """Patch get_variable_info and query_point for tropomi_point_query tests."""
    with (
        patch(
            "env_data_mcp.sources.tropomi.tools.get_variable_info",
            return_value=_MOCK_VAR_INFO,
        ),
        patch(
            "env_data_mcp.sources.tropomi.tools.query_point",
            return_value=(data, unavailable or [], substituted or {}),
        ),
    ):
        yield


@contextmanager
def _mock_bbox_query(data=_MOCK_BBOX_RESULT, unavailable=None, substituted=None):
    """Patch get_variable_info and query_bbox for tropomi_bbox_query tests."""
    with (
        patch(
            "env_data_mcp.sources.tropomi.tools.get_variable_info",
            return_value=_MOCK_VAR_INFO,
        ),
        patch(
            "env_data_mcp.sources.tropomi.tools.query_bbox",
            return_value=(data, unavailable or [], substituted or {}),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Available variables
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """Tests of the tropomi_available_variables mcp tool."""

    def test_returns_results(self):
        """Tests expected results are returned."""
        with patch(
            "env_data_mcp.sources.tropomi.tools.get_variable_info",
            return_value=_EXPECTED_VARIABLES,
        ):
            results = tropomi_available_variables()
        assert "data" in results
        assert len(results["data"]) == 3
        assert "_meta" in results
        assert "success" in results["_meta"]
        assert results["_meta"]["success"] is True
        assert results["_meta"]["geometries_returned"] == 0
        assert results["_meta"]["total_records_returned"] == 3

    def test_returns_error(self):
        """Tests that HTTP status errors are handled."""
        with patch(
            "env_data_mcp.sources.tropomi.tools.get_variable_info",
            side_effect=get_mock_http_error(),
        ):
            results = tropomi_available_variables()
        assert "data" in results
        assert results["data"] == {}
        assert "_meta" in results
        meta = results["_meta"]
        assert "success" in meta
        assert not meta["success"]
        assert "error" in meta
        assert "503" in meta["error"]


# ---------------------------------------------------------------------------
# tropomi_point_query
# ---------------------------------------------------------------------------


class TestTropomiQuery:
    """Tests of the tropomi_point_query mcp tool."""

    def test_returns_results(self):
        """Tests expected data and meta structure are returned on success."""
        with _mock_point_query():
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_O3"],
            )
        assert "data" in result
        assert "_meta" in result
        assert isinstance(result["data"], list)
        assert len(result["data"]) == 1
        group = result["data"][0]
        assert group["geometry"]["type"] == "Point"
        assert len(group["records"]) == 1

    def test_meta_fields(self):
        """Tests key fields in the _meta block."""
        with _mock_point_query():
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_O3"],
            )
        meta = result["_meta"]
        assert meta["source"] == "tropomi"
        assert meta["success"] is True
        assert meta["error"] is None
        assert meta["geometries_returned"] == 1
        assert meta["total_records_returned"] == 1
        assert meta["auth_required"] is False

    def test_echoes_query_params(self):
        """Tests that query_params in meta mirrors the tool arguments."""
        with _mock_point_query():
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_O3"],
            )
        qp = result["_meta"]["query_params"]
        assert qp["latitude"] == pytest.approx(33.84)
        assert qp["longitude"] == pytest.approx(-116.49)
        assert qp["start_date"] == "2024-01-03"
        assert qp["end_date"] == "2024-01-05"
        assert qp["variables"] == ["OFFL-L2_O3"]

    def test_variables_in_meta(self):
        """Tests that variables and variable_info appear in meta."""
        with _mock_point_query():
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_O3"],
            )
        meta = result["_meta"]
        assert meta["variables"] == ["OFFL-L2_O3"]
        assert "OFFL-L2_O3" in meta["variable_info"]
        assert meta["variable_info"]["OFFL-L2_O3"]["units"] == "DU"

    def test_unavailable_variables_in_meta(self):
        """Tests that unavailable variables returned by query_point appear in meta."""
        with _mock_point_query(data=[], unavailable=["OFFL-L2_NO2"]):
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_NO2"],
            )
        assert "OFFL-L2_NO2" in result["_meta"]["unavailable_variables"]

    def test_substituted_variables_in_meta(self):
        """Tests that a stream substitution from query_point appears in meta."""
        with _mock_point_query(substituted={"OFFL-L2_CO": "RPRO-L2_CO"}):
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_CO"],
            )
        assert result["_meta"]["substituted_variables"] == {"OFFL-L2_CO": "RPRO-L2_CO"}

    def test_substituted_variable_info_in_meta(self):
        """Tests the serving stream is described, since records are keyed by its name."""
        with _mock_point_query(substituted={"OFFL-L2_CO": "RPRO-L2_CO"}):
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_CO"],
            )
        variable_info = result["_meta"]["variable_info"]
        assert variable_info["RPRO-L2_CO"]["units"] == "mol m-2"
        assert "OFFL-L2_CO" in variable_info

    def test_substituted_variables_present_when_none_substituted(self):
        """Tests the key is always emitted, so the meta schema never varies."""
        with _mock_point_query():
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_CO"],
            )
        assert result["_meta"]["substituted_variables"] == {}

    def test_slow_query_warning(self):
        """Tests that a slow-query warning from check_runtime is passed through."""
        with (
            _mock_point_query(),
            patch(
                "env_data_mcp.sources.tropomi.tools.check_runtime",
                return_value=_SLOW_WARN,
            ),
        ):
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
            )
        meta = result["_meta"]
        assert meta["success"] is False
        assert meta["geometries_returned"] == 0
        assert meta["total_records_returned"] == 0
        assert result["data"] == []
        assert "exceeds" in meta["message"]

    def test_invalid_latitude_returns_error(self):
        """Tests that an out-of-range latitude produces an error response."""
        with _mock_point_query():
            result = tropomi_point_query(
                latitude=999.0,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
            )
        assert result["_meta"]["success"] is False
        assert result["_meta"]["error"] is not None

    def test_invalid_date_returns_error(self):
        """Tests that a non-ISO date string produces an error response."""
        with _mock_point_query():
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="January 3 2024",
                end_date="2024-01-05",
            )
        assert result["_meta"]["success"] is False
        assert result["_meta"]["error"] is not None

    def test_query_error_returns_error(self):
        """Tests that an exception from query_point produces an error response."""
        with (
            patch(
                "env_data_mcp.sources.tropomi.tools.get_variable_info",
                return_value=_MOCK_VAR_INFO,
            ),
            patch(
                "env_data_mcp.sources.tropomi.tools.query_point",
                side_effect=get_mock_http_error(),
            ),
        ):
            result = tropomi_point_query(
                latitude=33.84,
                longitude=-116.49,
                start_date="2024-01-03",
                end_date="2024-01-05",
            )
        assert result["_meta"]["success"] is False
        assert "503" in result["_meta"]["error"]
        assert result["data"] == []


# ---------------------------------------------------------------------------
# tropomi_bbox_query
# ---------------------------------------------------------------------------


class TestTropomiBboxQuery:
    """Tests of the tropomi_bbox_query mcp tool."""

    def test_returns_results(self):
        """Tests expected data and meta structure are returned on success."""
        with _mock_bbox_query():
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_O3"],
            )
        assert "data" in result
        assert "_meta" in result
        assert isinstance(result["data"], list)
        assert len(result["data"]) == 2
        for group in result["data"]:
            assert group["geometry"]["type"] == "Point"
            assert len(group["records"]) == 1

    def test_meta_fields(self):
        """Tests key fields in the _meta block."""
        with _mock_bbox_query():
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_O3"],
            )
        meta = result["_meta"]
        assert meta["source"] == "tropomi"
        assert meta["success"] is True
        assert meta["error"] is None
        assert meta["geometries_returned"] == 2
        assert meta["total_records_returned"] == 2
        assert meta["auth_required"] is False

    def test_echoes_query_params(self):
        """Tests that query_params in meta mirrors the tool arguments."""
        with _mock_bbox_query():
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_O3"],
            )
        qp = result["_meta"]["query_params"]
        assert qp["min_lat"] == pytest.approx(33.5)
        assert qp["max_lat"] == pytest.approx(34.5)
        assert qp["min_lon"] == pytest.approx(-117.0)
        assert qp["max_lon"] == pytest.approx(-116.0)
        assert qp["start_date"] == "2024-01-03"
        assert qp["end_date"] == "2024-01-05"
        assert qp["variables"] == ["OFFL-L2_O3"]

    def test_variables_in_meta(self):
        """Tests that variables and variable_info appear in meta."""
        with _mock_bbox_query():
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_O3"],
            )
        meta = result["_meta"]
        assert meta["variables"] == ["OFFL-L2_O3"]
        assert "OFFL-L2_O3" in meta["variable_info"]
        assert meta["variable_info"]["OFFL-L2_O3"]["units"] == "DU"

    def test_unavailable_variables_in_meta(self):
        """Tests that unavailable variables returned by query_bbox appear in meta."""
        with _mock_bbox_query(data=[], unavailable=["OFFL-L2_NO2"]):
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_NO2"],
            )
        assert "OFFL-L2_NO2" in result["_meta"]["unavailable_variables"]

    def test_substituted_variables_in_meta(self):
        """Tests that a stream substitution from query_bbox appears in meta."""
        with _mock_bbox_query(substituted={"OFFL-L2_CO": "RPRO-L2_CO"}):
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_CO"],
            )
        assert result["_meta"]["substituted_variables"] == {"OFFL-L2_CO": "RPRO-L2_CO"}

    def test_substituted_variable_info_in_meta(self):
        """Tests the serving stream is described, since records are keyed by its name."""
        with _mock_bbox_query(substituted={"OFFL-L2_CO": "RPRO-L2_CO"}):
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_CO"],
            )
        variable_info = result["_meta"]["variable_info"]
        assert variable_info["RPRO-L2_CO"]["units"] == "mol m-2"
        assert "OFFL-L2_CO" in variable_info

    def test_substituted_variables_present_when_none_substituted(self):
        """Tests the key is always emitted, so the meta schema never varies."""
        with _mock_bbox_query():
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
                variables=["OFFL-L2_CO"],
            )
        assert result["_meta"]["substituted_variables"] == {}

    def test_slow_query_warning(self):
        """Tests that a slow-query warning from check_runtime is passed through."""
        with (
            _mock_bbox_query(),
            patch(
                "env_data_mcp.sources.tropomi.tools.check_runtime",
                return_value=_SLOW_WARN,
            ),
        ):
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
            )
        meta = result["_meta"]
        assert meta["success"] is False
        assert meta["geometries_returned"] == 0
        assert meta["total_records_returned"] == 0
        assert result["data"] == []
        assert "exceeds" in meta["message"]

    def test_invalid_bbox_returns_error(self):
        """Tests that min_lat > max_lat produces an error response."""
        with _mock_bbox_query():
            result = tropomi_bbox_query(
                min_lat=35.0,
                max_lat=33.0,  # inverted
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
            )
        assert result["_meta"]["success"] is False
        assert result["_meta"]["error"] is not None

    def test_invalid_date_returns_error(self):
        """Tests that a non-ISO date string produces an error response."""
        with _mock_bbox_query():
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="January 3 2024",
                end_date="2024-01-05",
            )
        assert result["_meta"]["success"] is False
        assert result["_meta"]["error"] is not None

    def test_query_error_returns_error(self):
        """Tests that an exception from query_bbox produces an error response."""
        with (
            patch(
                "env_data_mcp.sources.tropomi.tools.get_variable_info",
                return_value=_MOCK_VAR_INFO,
            ),
            patch(
                "env_data_mcp.sources.tropomi.tools.query_bbox",
                side_effect=get_mock_http_error(),
            ),
        ):
            result = tropomi_bbox_query(
                min_lat=33.5,
                max_lat=34.5,
                min_lon=-117.0,
                max_lon=-116.0,
                start_date="2024-01-03",
                end_date="2024-01-05",
            )
        assert result["_meta"]["success"] is False
        assert "503" in result["_meta"]["error"]
        assert result["data"] == []
