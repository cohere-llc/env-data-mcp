"""Integration tests for the GBIF source adapter (live REST access).

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests call the real GBIF REST service and require network access.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest

from env_data_mcp.sources.gbif_new._client import _get_variable_info
from env_data_mcp.sources.gbif_new.constants import _DEFAULT_VARIABLES, _QueryType
from env_data_mcp.sources.gbif_new.tools import gbif_occurrence_available_variables

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

_GBIF_HEALTH = "https://api.gbif.org/v1/occurrence/search"

HTTP_SUCCESS = 200


@pytest.fixture(scope="module", autouse=True)
def _require_gbif_available():
    """Skip all tests if the GBIF API is unreachable."""
    try:
        r = httpx.get(_GBIF_HEALTH, params={"limit": 1}, timeout=10)
        if r.status_code != HTTP_SUCCESS:
            pytest.skip(f"GBIF API returned HTTP {r.status_code}")
    except Exception as e:
        pytest.skip(f"GBIF API not reachable: {e}")


# ---------------------------------------------------------------------------
# Per-dataset parameter table
# ---------------------------------------------------------------------------


@dataclass
class _DatasetCase:
    label: str
    avail_fn: Callable
    default_vars: list[str]
    primary_var: str


_DATASET_CASES = [
    pytest.param(
        _DatasetCase(
            label="occurrence",
            avail_fn=gbif_occurrence_available_variables,
            default_vars=_DEFAULT_VARIABLES[_QueryType.OCCURRENCE],
            primary_var="scientificName",
        ),
        id="occurrence",
    ),
]

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=_DATASET_CASES)
def dc(request) -> _DatasetCase:
    return request.param


# ---------------------------------------------------------------------------
# Schema query and parsing checks
# ---------------------------------------------------------------------------


def test_gbif_result_schema_injest():
    """Ensure every GBIF query type has available variables with descriptions."""
    for query_type in _QueryType:
        var_info = _get_variable_info(query_type)
        assert len(var_info) > 0, f"No variable info returned for GBIF query {query_type}"
        for var, info in var_info.items():
            assert "description" in info, (
                f"Missing description for GBIF {query_type} variable {var}"
            )
        for var in _DEFAULT_VARIABLES[query_type]:
            assert var in var_info, (
                f"Missing default variable {var} in available variables for GBIF {query_type}"
            )


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """available_variables tool returns expected results."""

    def test_returns_nonempty_dict(self, dc: _DatasetCase):
        var_info = dc.avail_fn()
        assert isinstance(var_info, dict)
        assert len(var_info) > 0

    def test_primary_var_present(self, dc: _DatasetCase):
        var_info = dc.avail_fn()
        assert dc.primary_var in var_info["data"], (
            f"{dc.label}: {dc.primary_var} missing from available variables"
            " - upstream schema change?"
        )

    def test_primary_var_has_description(self, dc: _DatasetCase):
        var_info = dc.avail_fn()
        entry = var_info["data"][dc.primary_var]
        assert "units" in entry
        assert "description" in entry
        assert len(entry["description"]) > 0

    def test_all_default_vars_present(self, dc: _DatasetCase):
        var_info = dc.avail_fn()
        missing = [v for v in dc.default_vars if v not in var_info["data"]]
        assert not missing, f"{dc.label}: default variables absent from available set: {missing}"
