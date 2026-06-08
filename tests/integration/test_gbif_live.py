"""Integration tests for the GBIF source adapter (live REST access).

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests call the real GBIF REST service and require network access.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest

from env_data_mcp.sources.gbif._query import _get_variable_info
from env_data_mcp.sources.gbif.constants import _DEFAULT_VARIABLES, _QueryType
from env_data_mcp.sources.gbif.tools import (
    gbif_occurrence_available_variables,
    gbif_occurrence_query,
)

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


def test_gbif_result_schema_ingest():
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


# ---------------------------------------------------------------------------
# Test coordinates — Yakima Valley, WA
# ---------------------------------------------------------------------------

_LAT = 46.2531882
_LON = -119.4768203


@pytest.mark.integration
def test_gbif_occurrences_live_returns_success():
    result = gbif_occurrence_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=1000,
        max_runtime_s=9999,
    )
    assert result["_meta"]["success"] is True
    assert result["_meta"]["source"] == "gbif"


@pytest.mark.integration
def test_gbif_occurrences_live_meta_fields():
    result = gbif_occurrence_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=1000,
        max_runtime_s=9999,
    )
    meta = result["_meta"]
    assert meta["auth_required"] is False
    assert meta["latency_s"] > 0
    assert meta["rows_returned"] > 10
    assert meta["rows_returned"] <= 1000
    assert meta["license"] != ""


@pytest.mark.integration
def test_gbif_occurrences_live_license_populated():
    result = gbif_occurrence_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=1000,
        max_runtime_s=9999,
    )
    # License must be non-empty whether records exist or not.
    assert result["_meta"]["license"] != ""


@pytest.mark.integration
def test_gbif_occurrences_live_record_schema():
    result = gbif_occurrence_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=1000,
        max_runtime_s=9999,
    )
    if result["data"]:
        rec = result["data"][0]["records"][0]
        assert "decimalLatitude" in rec, "GBIF Parquet: decimalLatitude column renamed or removed"
        assert "decimalLongitude" in rec, "GBIF Parquet: decimalLongitude column renamed or removed"
        assert "eventDate" in rec, "GBIF Parquet: eventDate column renamed or removed"
        assert "species" in rec or "scientificName" in rec, (
            "GBIF Parquet: neither 'species' nor 'scientificName' present — schema may have changed"
        )


# ---------------------------------------------------------------------------
# Schema stability assertions
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_gbif_schema_lat_lon_physical_range():
    result = gbif_occurrence_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=100,
        max_runtime_s=9999,
    )
    for rec in result["data"]:
        lat = rec["records"][0].get("decimalLatitude")
        lon = rec["records"][0].get("decimalLongitude")
        if lat is not None:
            assert -90.0 <= lat <= 90.0, (
                f"GBIF: decimalLatitude={lat} outside physical range — fill value or unit change?"
            )
        if lon is not None:
            assert -180.0 <= lon <= 180.0, f"GBIF: decimalLongitude={lon} outside physical range"


@pytest.mark.integration
def test_gbif_schema_variable_info_present():
    result = gbif_occurrence_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=100,
        max_runtime_s=9999,
    )
    meta = result["_meta"]
    assert "variable_info" in meta, "GBIF: _meta.variable_info missing"
    vi = meta["variable_info"]
    assert "decimalLatitude" in vi, "GBIF: variable_info missing decimalLatitude entry"
    assert "units" in vi["decimalLatitude"], (
        "GBIF: variable_info['decimalLatitude'] missing 'units'"
    )


@pytest.mark.integration
def test_gbif_schema_license_present():
    result = gbif_occurrence_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=100,
        max_runtime_s=9999,
    )
    meta = result["_meta"]
    assert meta["license"] != "", "GBIF: _meta.license is empty"
    assert "latitude" in meta["query_params"], "GBIF: query_params missing latitude"
