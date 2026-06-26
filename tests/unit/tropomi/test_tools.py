"""Unit tests for the Sentinel 5-TROPOMI tools module.

All query functions are mocked via a ``unittest.mock.patch``; no network access required.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx

from env_data_mcp.sources.tropomi.tools import tropomi_available_variables

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


def get_mock_http_error():
    request = httpx.Request("GET", "https://meeo-s5p.s3.amazonaws.com")
    response = httpx.Response(503, request=request)
    return httpx.HTTPStatusError(
        "503 Service Unavailable",
        request=request,
        response=response,
    )


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
        assert "rows_returned" in results["_meta"]
        assert results["_meta"]["rows_returned"] == 3

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
