"""Integration tests for the Sentinel 5-TROPOMI source adapter (live AWS access).

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests query the real AWS S3 bucket for TROPOMI data and require network access.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from env_data_mcp.sources.tropomi.constants import _PRODUCT_TYPES, DEFAULT_VARIABLES
from env_data_mcp.sources.tropomi.tools import tropomi_available_variables

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

_AWS_TROPOMI_HEALTH = "https://meeo-s5p.s3.amazonaws.com"


@pytest.fixture(scope="module", autouse=True)
def _require_tropomi_available():
    """Skip all tests if the TROPOMI S3 bucket is not accessible."""
    try:
        r = httpx.get(_AWS_TROPOMI_HEALTH, timeout=10)
        r.raise_for_status()
    except Exception as e:
        pytest.skip(f"TROPOMI AWS S3 bucket not reachable: {e}")


# ---------------------------------------------------------------------------
# Available variables tool tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def var_info() -> dict[str, Any]:
    return tropomi_available_variables()


class TestAvailableVariables:
    """tropomi_available_variables() tool tests."""

    def test_returns_dict_with_data(self, var_info: dict[str, Any]):
        """Test returns data."""
        assert isinstance(var_info, dict)
        assert "data" in var_info
        assert len(var_info["data"]) > 0
        for _, val in var_info["data"].items():
            assert "description" in val
            assert len(val["description"]) > 0
            assert "units" in val
            assert len(val["units"]) > 0

    def test_contains_known_methane_variable(self, var_info: dict[str, Any]):
        """Test results include known variable info."""
        data = var_info["data"]
        assert "OFFL-L2_CH4" in data
        ch4_info = data["OFFL-L2_CH4"]
        assert "description" in ch4_info
        assert any(word in ch4_info["description"].lower() for word in ["methane", "ch4"])
        assert "offline" in ch4_info["description"].lower()
        assert "units" in ch4_info
        assert ch4_info["units"] == "ppb"

    @pytest.mark.parametrize("var", DEFAULT_VARIABLES)
    def test_contains_default_variables(self, var_info: dict[str, Any], var: str):
        """Test results include all default variables."""
        data = var_info["data"]
        assert var in data

    def test_includes_non_default_variables(self, var_info: dict[str, Any]):
        """Test results include more than just the default variables."""
        assert len(var_info["data"]) > len(DEFAULT_VARIABLES)

    def test_contains_expected_metadata(self, var_info: dict[str, Any]):
        """Test metadata is complete and correct."""
        assert "_meta" in var_info
        meta = var_info["_meta"]
        assert "source" in meta
        assert meta["source"] == "tropomi"
        assert "success" in meta
        assert meta["success"] is True
        assert "rows_returned" in meta
        assert meta["rows_returned"] == len(var_info["data"])
        assert len(meta.get("license")) > 0 or len(meta.get("license_url")) > 0

    def test_contains_product_type(self, var_info: dict[str, Any]):
        """Test variable descriptions include the product type."""
        for key, val in var_info["data"].items():
            parts = key.split("-")
            assert len(parts) >= 2
            assert parts[0] in _PRODUCT_TYPES
            assert _PRODUCT_TYPES[parts[0]] in val["description"]
