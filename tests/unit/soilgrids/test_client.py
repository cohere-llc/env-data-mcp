"""Unit tests for env_data_mcp.sources.soilgrids._client.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from owslib.coverage.wcs100 import WebCoverageService_1_0_0
from owslib.coverage.wcs110 import WebCoverageService_1_1_0

from env_data_mcp.sources.soilgrids._client import get_client


def _get_mock_contents(contents: dict[str, Any] | None = None) -> WebCoverageService_1_0_0:
    # spec makes isinstance(mock, WebCoverageService_1_0_0) evaluate True.
    mock = MagicMock(spec=WebCoverageService_1_0_0)
    mock.contents = contents or {
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
        patch("env_data_mcp.sources.soilgrids._client._clients", {}),
        patch(
            "env_data_mcp.sources.soilgrids._client.WebCoverageService",
            return_value=_get_mock_contents(),
        ),
    ):
        client = get_client("bdod")
    assert client is not None


def test_get_client_throws_type_error():
    """Tests that a type error is thrown from get_client if the wrong WCS is returned."""
    with (
        patch("env_data_mcp.sources.soilgrids._client._clients", {}),
        patch(
            "env_data_mcp.sources.soilgrids._client.WebCoverageService",
            return_value=MagicMock(spec=WebCoverageService_1_1_0),
        ),
        pytest.raises(TypeError, match="Expected WCS 1.0.0"),
    ):
        _ = get_client("bdod")


def test_get_client_uses_cache():
    """Tests that the global cache of clients is used when populated."""
    mock_client = MagicMock()

    def mock_web_coverage_service(type_name: str, version: str) -> MagicMock:
        pytest.fail("WebCoverageService() called instead of cache being used.")

    with (
        patch("env_data_mcp.sources.soilgrids._client._clients", {"bdod": mock_client}),
        patch(
            "env_data_mcp.sources.soilgrids._client.WebCoverageService",
            side_effect=mock_web_coverage_service,
        ),
    ):
        client = get_client("bdod")
    assert client is mock_client
