"""Unit tests for env_data_mcp.sources.soilgrids._client.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from owslib.coverage.wcs100 import WebCoverageService_1_0_0

from env_data_mcp.sources.soilgrids_new._client import get_client, get_specific_variable_info


def _get_mock_contents() -> WebCoverageService_1_0_0:
    # spec makes isinstance(mock, WebCoverageService_1_0_0) evaluate True.
    mock = MagicMock(spec=WebCoverageService_1_0_0)
    mock.contents = {
        "bdod_15-30cm_mean": {},
        "bdod_30-60cm_Q0.5": {},
    }
    return mock


# ---------------------------------------------------------------------------
# get_client
# ---------------------------------------------------------------------------


def test_get_client():
    """Tests that get_client returns a client."""
    with (
        patch("env_data_mcp.sources.soilgrids_new._client._clients", {}),
        patch(
            "env_data_mcp.sources.soilgrids_new._client.WebCoverageService",
            return_value=_get_mock_contents(),
        ),
    ):
        client = get_client("bdod")
    assert client is not None


# ---------------------------------------------------------------------------
# _get_base_variable_list
# ---------------------------------------------------------------------------


def test_get_specific_variable_info():
    """Tests that get_specifc_variable_info returns results."""
    with patch(
        "env_data_mcp.sources.soilgrids_new._client.WebCoverageService",
        return_value=_get_mock_contents(),
    ):
        var_info = get_specific_variable_info("bdod")
    assert len(var_info) > 0
    assert "bdod_15-30cm_mean" in var_info
    assert var_info["bdod_15-30cm_mean"] == ("15-30cm", "mean")
    assert "bdod_30-60cm_Q0.5" in var_info
    assert var_info["bdod_30-60cm_Q0.5"] == ("30-60cm", "median")
