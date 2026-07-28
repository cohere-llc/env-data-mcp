"""Integration tests for the GBIF source adapter (live REST access).

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests call the real GBIF REST service and require network access.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest

from env_data_mcp.sources.gbif.constants import _DEFAULT_VARIABLES, _QueryType
from env_data_mcp.sources.gbif.tools import (
    gbif_occurrence_available_variables,
    gbif_occurrence_bbox_query,
    gbif_occurrence_point_query,
)

from .common import (
    NH_RURAL,
    AdapterSpec,
    DataExpectation,
    assert_grouped_geometry_response_valid,
    assert_meta_success,
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
# Adapter-specific validate hooks — called by test_common_live.py after common
# assertions, and directly by adapter-specific tests
# ---------------------------------------------------------------------------


def _validate_gbif_point_result(result: dict) -> None:
    """GBIF-specific assertions for a point query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "gbif"
    assert result["_meta"]["auth_required"] is False


def _validate_gbif_bbox_result(result: dict) -> None:
    """GBIF-specific assertions for a bbox query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "gbif"
    assert result["_meta"]["auth_required"] is False


# ---------------------------------------------------------------------------
# GBIF AdapterSpec — exported for adapter_specs.py
# ---------------------------------------------------------------------------

OCCURRENCE_SPEC = AdapterSpec(
    name="gbif_occurrence",
    available_variables=gbif_occurrence_available_variables,
    point_query=gbif_occurrence_point_query,
    bbox_query=gbif_occurrence_bbox_query,
    supports_date_range=True,
    primary_variable="scientificName",
    default_variables=_DEFAULT_VARIABLES[_QueryType.OCCURRENCE],
    max_runtime_s=120.0,
    data_expectations={
        "sh_rural": DataExpectation(
            has_data=False, notes="Remote Patagonia: no occurrence data in standard window"
        ),
        "sh_midlat": DataExpectation(
            has_data=False, notes="Patagonia: no occurrence data in standard window"
        ),
        "sh_polar": DataExpectation(
            has_data=False, notes="Antarctic coast: no occurrence data in standard window"
        ),
        "nh_polar": DataExpectation(
            has_data=False, notes="Artic: no occurrence data in standard window"
        ),
        "ocean": DataExpectation(
            has_data=False, notes="Open Atlantic: no occurrence data in standard window"
        ),
        "equatorial": DataExpectation(
            has_data=False, notes="Open Atlantic: no occurrence data in standard window"
        ),
    },
    extra_point_kwargs={"radius_km": 5.0},
    extra_bbox_kwargs={},
    use_small_bboxes=True,
    validate_point_result=_validate_gbif_point_result,
    validate_bbox_result=_validate_gbif_bbox_result,
)


# ---------------------------------------------------------------------------
# Adapter-specific dataset parameter table
# ---------------------------------------------------------------------------


@dataclass
class _DatasetCase:
    spec: AdapterSpec
    custom_var: str  # non-default column for custom-variable round-trip tests


_DATASET_CASES = [
    pytest.param(
        _DatasetCase(
            spec=OCCURRENCE_SPEC,
            custom_var="publishingCountry",
        ),
        id="occurrence",
    ),
]

# Wide date window used by count- and schema-stability fixtures that need substantial data.
_WIDE_START = "2010-01-01"
_WIDE_END = "2021-12-31"
# Allow the runtime gate to pass for wide-window queries (4000+ day spans are slow to estimate).
_WIDE_MAX_RUNTIME_S = 1200.0

# Yakima Valley bbox and year window used by the wide bbox fixture.
_YAKIMA_BBOX = {"min_lat": 46.0, "max_lat": 46.5, "min_lon": -120.0, "max_lon": -119.0}
_YAKIMA_YEAR = {"start_date": "2018-01-01", "end_date": "2018-12-31"}


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=_DATASET_CASES)
def dc(request) -> _DatasetCase:
    return request.param


@pytest.fixture(scope="module")
def avail_vars(dc: _DatasetCase) -> dict:
    """Available variables; loaded once per module run."""
    return dc.spec.available_variables()


@pytest.fixture(scope="module")
def wide_point_result(dc: _DatasetCase) -> dict:
    """Point query at NH_RURAL over a wide date range; used for schema/count tests."""
    return dc.spec.point_query(
        latitude=NH_RURAL.coordinates.latitude,
        longitude=NH_RURAL.coordinates.longitude,
        start_date=_WIDE_START,
        end_date=_WIDE_END,
        max_runtime_s=_WIDE_MAX_RUNTIME_S,
        limit=100,
        **dc.spec.extra_point_kwargs,
    )


@pytest.fixture(scope="module")
def wide_bbox_result(dc: _DatasetCase) -> dict:
    """Bbox query over Yakima Valley for a full year; used for schema/count tests."""
    return dc.spec.bbox_query(
        **_YAKIMA_BBOX,
        **_YAKIMA_YEAR,
        max_runtime_s=_WIDE_MAX_RUNTIME_S,
        limit=100,
        **dc.spec.extra_bbox_kwargs,
    )


# ---------------------------------------------------------------------------
# TestAvailableVariables (GBIF-specific; common tests run via test_common_live.py)
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """GBIF-specific available_variables checks beyond common coverage."""

    def test_primary_var_present(self, dc: _DatasetCase, avail_vars: dict) -> None:
        assert dc.spec.primary_variable in avail_vars["data"], (
            f"{dc.spec.name}: {dc.spec.primary_variable!r} absent from available variables"
        )

    def test_primary_var_has_description(self, dc: _DatasetCase, avail_vars: dict) -> None:
        entry = avail_vars["data"][dc.spec.primary_variable]
        assert "units" in entry
        assert "description" in entry
        assert len(entry["description"]) > 0


# ---------------------------------------------------------------------------
# TestPointQuery (GBIF-specific, uses wide-date fixture)
# ---------------------------------------------------------------------------


class TestPointQuery:
    """GBIF-specific point query checks; common tests cover schema/meta/consistency."""

    def test_wide_date_returns_substantial_data(
        self, dc: _DatasetCase, wide_point_result: dict
    ) -> None:
        """A wide date range at NH_RURAL returns many occurrence records."""
        assert_meta_success(wide_point_result)
        meta = wide_point_result["_meta"]
        assert meta["geometries_returned"] > 10, (
            f"{dc.spec.name}: expected >10 occurrences; got {meta['geometries_returned']}"
        )
        assert meta["geometries_returned"] <= 100  # limit=100 enforced

    def test_core_occurrence_columns_present(
        self, dc: _DatasetCase, wide_point_result: dict
    ) -> None:
        """Schema stability: core GBIF Parquet columns must not be renamed."""
        rec = wide_point_result["data"][0]["records"][0]
        assert "decimalLatitude" in rec, (
            f"{dc.spec.name}: GBIF Parquet: decimalLatitude column renamed or removed"
        )
        assert "decimalLongitude" in rec, (
            f"{dc.spec.name}: GBIF Parquet: decimalLongitude column renamed or removed"
        )
        assert "eventDate" in rec, (
            f"{dc.spec.name}: GBIF Parquet: eventDate column renamed or removed"
        )
        assert "species" in rec or "scientificName" in rec, (
            f"{dc.spec.name}: GBIF Parquet: neither 'species' nor 'scientificName' present"
        )

    def test_decimal_lat_lon_physical_range(
        self, dc: _DatasetCase, wide_point_result: dict
    ) -> None:
        """``decimalLatitude`` / ``decimalLongitude`` values fall within WGS84 range."""
        for group in wide_point_result["data"]:
            lat = group["records"][0].get("decimalLatitude")
            lon = group["records"][0].get("decimalLongitude")
            if lat is not None:
                assert -90.0 <= lat <= 90.0, (
                    f"{dc.spec.name}: GBIF: decimalLatitude={lat} outside physical range"
                )
            if lon is not None:
                assert -180.0 <= lon <= 180.0, (
                    f"{dc.spec.name}: GBIF: decimalLongitude={lon} outside physical range"
                )

    def test_default_vars_present_in_rows(self, dc: _DatasetCase, wide_point_result: dict) -> None:
        """At least one default variable appears in the first occurrence record."""
        row = wide_point_result["data"][0]["records"][0]
        found = [v for v in dc.spec.default_variables if v in row]
        assert len(found) > 0, f"{dc.spec.name}: no default variables found in output row"

    def test_geometry_type_is_point(self, dc: _DatasetCase, wide_point_result: dict) -> None:
        """GBIF occurrence records always produce Point geometries."""
        for group in wide_point_result["data"][:10]:
            geom = group["geometry"]
            assert geom["type"] == "Point", (
                f"{dc.spec.name}: unexpected geometry type '{geom['type']}'; expected 'Point'"
            )


# ---------------------------------------------------------------------------
# TestBboxQuery (GBIF-specific, uses wide-date fixture)
# ---------------------------------------------------------------------------


class TestBboxQuery:
    """GBIF-specific bbox query checks; common tests cover schema/meta/consistency."""

    def test_wide_date_returns_data(self, dc: _DatasetCase, wide_bbox_result: dict) -> None:
        """A Yakima Valley bbox over a full year returns occurrence records."""
        assert_meta_success(wide_bbox_result)
        assert wide_bbox_result["_meta"]["geometries_returned"] > 0, (
            f"{dc.spec.name}: bbox query returned no occurrences for Yakima/2018"
        )

    def test_primary_var_in_rows(self, dc: _DatasetCase, wide_bbox_result: dict) -> None:
        assert dc.spec.primary_variable in wide_bbox_result["data"][0]["records"][0], (
            f"{dc.spec.name}: primary var '{dc.spec.primary_variable}' absent from bbox record"
        )

    def test_geometry_type_is_point(self, dc: _DatasetCase, wide_bbox_result: dict) -> None:
        """GBIF bbox results also produce Point geometries."""
        for group in wide_bbox_result["data"][:10]:
            geom = group["geometry"]
            assert geom["type"] == "Point", (
                f"{dc.spec.name}: unexpected geometry type '{geom['type']}'; expected 'Point'"
            )


# ---------------------------------------------------------------------------
# TestNonDefaultVariable (GBIF-specific custom_var; uses wide date range for reliability)
# ---------------------------------------------------------------------------


class TestNonDefaultVariable:
    """Custom variable not in defaults is returned when explicitly requested."""

    def test_custom_var_returned_in_point_query(self, dc: _DatasetCase) -> None:
        if not dc.custom_var:
            pytest.skip(f"{dc.spec.name}: no custom_var configured")
        result = dc.spec.point_query(
            latitude=NH_RURAL.coordinates.latitude,
            longitude=NH_RURAL.coordinates.longitude,
            start_date=_WIDE_START,
            end_date="2018-12-31",
            variables=[dc.custom_var],
            max_runtime_s=_WIDE_MAX_RUNTIME_S,
            limit=100,
            **dc.spec.extra_point_kwargs,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.spec.name}: custom variable '{dc.custom_var}' query failed"
            f" — {result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0, (
            f"{dc.spec.name}: no data returned for custom variable '{dc.custom_var}'"
        )
        assert dc.custom_var in result["data"][0]["records"][0], (
            f"{dc.spec.name}: requested column '{dc.custom_var}' absent from output record"
        )

    def test_custom_var_returned_in_bbox_query(self, dc: _DatasetCase) -> None:
        if not dc.custom_var:
            pytest.skip(f"{dc.spec.name}: no custom_var configured")
        result = dc.spec.bbox_query(
            **_YAKIMA_BBOX,
            **_YAKIMA_YEAR,
            variables=[dc.custom_var],
            max_runtime_s=_WIDE_MAX_RUNTIME_S,
            limit=100,
            **dc.spec.extra_bbox_kwargs,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.spec.name}: bbox custom variable '{dc.custom_var}' query failed"
            f" — {result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0, (
            f"{dc.spec.name}: no bbox data for custom variable '{dc.custom_var}'"
        )
        assert dc.custom_var in result["data"][0]["records"][0], (
            f"{dc.spec.name}: requested column '{dc.custom_var}' absent from bbox output record"
        )


# ---------------------------------------------------------------------------
# TestAvailableVariablesRoundtrip
# ---------------------------------------------------------------------------


class TestAvailableVariablesRoundtrip:
    """Discover non-default variables from available_variables(), then use them in queries.

    Proves the full discovery → selection → query workflow end-to-end.
    """

    def test_avail_variables_usable_in_point_query(
        self, dc: _DatasetCase, avail_vars: dict
    ) -> None:
        assert avail_vars["_meta"]["success"] is True, (
            f"{dc.spec.name}: avail_fn() failed: {avail_vars['_meta'].get('error')}"
        )
        default_set = set(dc.spec.default_variables)
        non_default = [v for v in avail_vars["data"] if v not in default_set][:3]
        if not non_default:
            pytest.skip(f"{dc.spec.name}: no non-default variables found in avail result")
        result = dc.spec.point_query(
            latitude=NH_RURAL.coordinates.latitude,
            longitude=NH_RURAL.coordinates.longitude,
            start_date=_WIDE_START,
            end_date="2018-12-31",
            variables=non_default,
            max_runtime_s=_WIDE_MAX_RUNTIME_S,
            limit=100,
            **dc.spec.extra_point_kwargs,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.spec.name}: point query with non-default vars {non_default} failed: "
            f"{result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0, (
            f"{dc.spec.name}: expected data for non-default vars {non_default} but got none"
        )

    def test_avail_variables_usable_in_bbox_query(self, dc: _DatasetCase, avail_vars: dict) -> None:
        assert avail_vars["_meta"]["success"] is True, (
            f"{dc.spec.name}: avail_fn() failed: {avail_vars['_meta'].get('error')}"
        )
        default_set = set(dc.spec.default_variables)
        non_default = [v for v in avail_vars["data"] if v not in default_set][:3]
        if not non_default:
            pytest.skip(f"{dc.spec.name}: no non-default variables found in avail result")
        result = dc.spec.bbox_query(
            **_YAKIMA_BBOX,
            **_YAKIMA_YEAR,
            variables=non_default,
            max_runtime_s=_WIDE_MAX_RUNTIME_S,
            limit=100,
            **dc.spec.extra_bbox_kwargs,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.spec.name}: bbox query with non-default vars {non_default} failed"
            f" — {result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0, (
            f"{dc.spec.name}: expected data for non-default vars {non_default} but got none"
        )
