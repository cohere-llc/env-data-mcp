"""Integration tests for the GBIF source adapter (live REST access).

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests call the real GBIF REST service and require network access.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest

from env_data_mcp.models import AvailableVariablesResponse, GeoJsonGeometry, GroupedGeometryResponse
from env_data_mcp.sources.gbif._query import _get_variable_info
from env_data_mcp.sources.gbif.constants import _DEFAULT_VARIABLES, _QueryType
from env_data_mcp.sources.gbif.tools import (
    gbif_occurrence_available_variables,
    gbif_occurrence_bbox_query,
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
    point_fn: Callable
    bbox_fn: Callable
    default_vars: list[str]
    primary_var: str
    custom_var: str = ""  # A non-default column name to use in custom-var tests


_DATASET_CASES = [
    pytest.param(
        _DatasetCase(
            label="occurrence",
            avail_fn=gbif_occurrence_available_variables,
            point_fn=gbif_occurrence_query,
            bbox_fn=gbif_occurrence_bbox_query,
            default_vars=_DEFAULT_VARIABLES[_QueryType.OCCURRENCE],
            primary_var="scientificName",
            custom_var="institutionCode",  # not in defaults; present in museum/iNat records
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


@pytest.fixture(scope="module")
def avail_result(dc: _DatasetCase) -> dict:
    """Available variables query results."""
    return dc.avail_fn()


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """available_variables tool returns expected results."""

    def test_returns_nonempty_dict(self, avail_result: dict):
        assert isinstance(avail_result, dict)
        assert len(avail_result) > 0

    def test_primary_var_present(self, dc: _DatasetCase, avail_result: dict):
        assert dc.primary_var in avail_result["data"], (
            f"{dc.label}: {dc.primary_var} missing from available variables"
            " - upstream schema change?"
        )

    def test_primary_var_has_description(self, dc: _DatasetCase, avail_result: dict):
        entry = avail_result["data"][dc.primary_var]
        assert "units" in entry
        assert "description" in entry
        assert len(entry["description"]) > 0

    def test_all_default_vars_present(self, dc: _DatasetCase, avail_result: dict):
        missing = [v for v in dc.default_vars if v not in avail_result["data"]]
        assert not missing, f"{dc.label}: default variables absent from available set: {missing}"

    def test_meta_success(self, dc: _DatasetCase, avail_result: dict):
        assert avail_result["_meta"]["success"] is True, (
            f"{dc.label}: avail_fn meta.success is False — {avail_result['_meta'].get('error')}"
        )

    def test_more_than_defaults_available(self, dc: _DatasetCase, avail_result: dict):
        """GBIF schema exposes additional columns beyond the curated default set."""
        all_vars = list(avail_result["data"].keys())
        assert len(all_vars) > len(dc.default_vars), (
            f"{dc.label}: expected more columns than the {len(dc.default_vars)} defaults,"
            f" but only got {len(all_vars)}"
        )

    def test_each_entry_has_variable_name_and_metadata(self, dc: _DatasetCase, avail_result: dict):
        """Every entry has non-empty 'description' and a 'units' key."""
        for col, entry in avail_result["data"].items():
            assert col, f"{dc.label}: empty column name in available variables"
            assert entry.get("description"), (
                f"{dc.label}: column '{col}' missing non-empty 'description'"
            )
            assert "units" in entry, f"{dc.label}: column '{col}' missing 'units' key"

    def test_schema_valid(self, dc: _DatasetCase, avail_result: dict):
        """Full available_variables response validates against its Pydantic schema."""
        AvailableVariablesResponse.model_validate(avail_result)


# ---------------------------------------------------------------------------
# Test coordinates — Yakima Valley, WA
# ---------------------------------------------------------------------------

_LAT = 46.2531882
_LON = -119.4768203

# 0.5° × 1° bbox in Yakima Valley — matches the SSURGO integration test bbox
_BBOX = dict(min_lat=46.0, max_lat=46.5, min_lon=-120.0, max_lon=-119.0)
_START_DATE = "2018-01-01"
_END_DATE = "2018-12-31"


@pytest.fixture(scope="module")
def point_result(dc: _DatasetCase) -> dict:
    """Point query results."""
    return dc.point_fn(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=100,
        max_runtime_s=9999,
    )


@pytest.fixture(scope="module")
def baseline_bbox(dc: _DatasetCase) -> dict:
    """Default-variable bbox query at Yakima WA; run once per dataset type."""
    return dc.bbox_fn(
        **_BBOX,
        start_date=_START_DATE,
        end_date=_END_DATE,
        limit=100,
        max_runtime_s=9999,
    )


class TestPointQuery:
    """Tests of the gbif point query tools."""

    @pytest.mark.integration
    def test_gbif_occurrences_live_returns_success(self, point_result: dict):
        assert point_result["_meta"]["success"] is True
        assert point_result["_meta"]["source"] == "gbif"

    @pytest.mark.integration
    def test_gbif_occurrences_live_meta_fields(self, point_result: dict):
        meta = point_result["_meta"]
        assert meta["auth_required"] is False
        assert meta["latency_s"] > 0
        assert meta["rows_returned"] > 10
        assert meta["rows_returned"] <= 100
        assert meta["license"] != ""

    @pytest.mark.integration
    def test_gbif_occurrences_live_license_populated(self, point_result: dict):
        # License must be non-empty whether records exist or not.
        assert point_result["_meta"]["license"] != ""

    @pytest.mark.integration
    def test_gbif_occurrences_live_record_schema(self, point_result: dict):
        assert "data" in point_result
        rec = point_result["data"][0]["records"][0]
        assert "decimalLatitude" in rec, "GBIF Parquet: decimalLatitude column renamed or removed"
        assert "decimalLongitude" in rec, "GBIF Parquet: decimalLongitude column renamed or removed"
        assert "eventDate" in rec, "GBIF Parquet: eventDate column renamed or removed"
        assert "species" in rec or "scientificName" in rec, (
            "GBIF Parquet: neither 'species' nor 'scientificName' present — schema may have changed"
        )

    @pytest.mark.integration
    def test_gbif_schema_lat_lon_physical_range(self, point_result: dict):
        for rec in point_result["data"]:
            lat = rec["records"][0].get("decimalLatitude")
            lon = rec["records"][0].get("decimalLongitude")
            if lat is not None:
                assert -90.0 <= lat <= 90.0, (
                    f"GBIF: decimalLatitude={lat} outside physical range"
                    " — fill value or unit change?"
                )
            if lon is not None:
                assert -180.0 <= lon <= 180.0, (
                    f"GBIF: decimalLongitude={lon} outside physical range"
                )

    @pytest.mark.integration
    def test_gbif_schema_variable_info_present(self, point_result: dict):
        meta = point_result["_meta"]
        assert "variable_info" in meta, "GBIF: _meta.variable_info missing"
        vi = meta["variable_info"]
        assert "decimalLatitude" in vi, "GBIF: variable_info missing decimalLatitude entry"
        assert "units" in vi["decimalLatitude"], (
            "GBIF: variable_info['decimalLatitude'] missing 'units'"
        )

    @pytest.mark.integration
    def test_gbif_schema_license_present(self, point_result: dict):
        meta = point_result["_meta"]
        assert meta["license"] != "", "GBIF: _meta.license is empty"
        assert "latitude" in meta["query_params"], "GBIF: query_params missing latitude"

    def test_meta_source_field(self, point_result: dict):
        assert point_result["_meta"]["source"] == "gbif"

    def test_meta_auth_not_required(self, point_result: dict):
        assert point_result["_meta"]["auth_required"] is False

    def test_meta_latency_positive(self, point_result: dict):
        assert point_result["_meta"]["latency_s"] > 0

    def test_meta_query_params_echoed(self, point_result: dict):
        qp = point_result["_meta"]["query_params"]
        assert qp["latitude"] == _LAT
        assert qp["longitude"] == _LON

    def test_meta_license_nonempty(self, point_result: dict):
        assert point_result["_meta"]["license"] != ""

    def test_meta_rows_returned_consistent(self, point_result: dict):
        data = point_result["data"]
        assert point_result["_meta"]["rows_returned"] == len(data)

    def test_full_response_schema_valid(self, point_result: dict):
        """Full point-query response validates against GroupedGeometryResponse schema."""
        GroupedGeometryResponse.model_validate(point_result)

    def test_default_vars_present_in_rows(self, dc: _DatasetCase, point_result: dict):
        if not point_result["data"]:
            pytest.skip(f"{dc.label}: no data rows returned")
        row = point_result["data"][0]["records"][0]
        found = [v for v in dc.default_vars if v in row]
        assert len(found) > 0, f"{dc.label}: no default variables found in output row"

    def test_group_wrapper_fields(self, dc: _DatasetCase, point_result: dict):
        if not point_result["data"]:
            pytest.skip(f"{dc.label}: no data returned")
        group = point_result["data"][0]
        assert "geometry" in group, f"{dc.label}: 'geometry' absent from group wrapper"
        assert "records" in group, f"{dc.label}: 'records' absent from group wrapper"
        assert "latitude" in group, f"{dc.label}: 'latitude' absent from group wrapper"
        assert "longitude" in group, f"{dc.label}: 'longitude' absent from group wrapper"
        assert len(group["records"]) > 0, f"{dc.label}: group has no inner records"

    def test_group_has_geometry(self, dc: _DatasetCase, point_result: dict):
        if not point_result["data"]:
            pytest.skip(f"{dc.label}: no data returned")
        geom = point_result["data"][0]["geometry"]
        assert geom is not None, f"{dc.label}: geometry is None for first group"
        GeoJsonGeometry.model_validate(geom)


class TestNonDefaultVariable:
    """Requesting a non-default variable returns that column in result rows."""

    def test_custom_var_returned_in_point_query(self, dc: _DatasetCase):
        if not dc.custom_var:
            pytest.skip(f"{dc.label}: no custom_var configured")
        result = dc.point_fn(
            latitude=_LAT,
            longitude=_LON,
            radius_km=50.0,
            start_date=_START_DATE,
            end_date=_END_DATE,
            variables=[dc.custom_var],
            limit=50,
            max_runtime_s=120.0,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.label}: custom variable '{dc.custom_var}' query failed"
            f" — {result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0, (
            f"{dc.label}: no data returned for custom variable '{dc.custom_var}'"
        )
        assert dc.custom_var in result["data"][0]["records"][0], (
            f"{dc.label}: requested column '{dc.custom_var}' absent from output record"
        )

    def test_custom_var_returned_in_bbox_query(self, dc: _DatasetCase):
        if not dc.custom_var:
            pytest.skip(f"{dc.label}: no custom_var configured")
        result = dc.bbox_fn(
            **_BBOX,
            start_date=_START_DATE,
            end_date=_END_DATE,
            variables=[dc.custom_var],
            limit=50,
            max_runtime_s=120.0,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.label}: bbox custom variable '{dc.custom_var}' query failed"
            f" — {result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0, (
            f"{dc.label}: no bbox data for custom variable '{dc.custom_var}'"
        )
        assert dc.custom_var in result["data"][0]["records"][0], (
            f"{dc.label}: requested column '{dc.custom_var}' absent from bbox output record"
        )


class TestMaxRuntimeGate:
    """max_runtime_s=0.0 must block; max_runtime_s=3600.0 must allow."""

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_zero_max_runtime_blocks_query(self, dc: _DatasetCase, query_mode: str):
        if query_mode == "point":
            result = dc.point_fn(
                latitude=_LAT,
                longitude=_LON,
                radius_km=50.0,
                start_date=_START_DATE,
                end_date=_END_DATE,
                max_runtime_s=0.0,
            )
        else:
            result = dc.bbox_fn(
                **_BBOX,
                start_date=_START_DATE,
                end_date=_END_DATE,
                max_runtime_s=0.0,
            )
        assert result["_meta"]["success"] is False, (
            f"{dc.label}/{query_mode}: max_runtime_s=0.0 should have blocked the query"
        )
        assert result["_meta"]["slow_query_warning"] is True
        assert result["data"] == []

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_generous_max_runtime_allows_query(self, dc: _DatasetCase, query_mode: str):
        if query_mode == "point":
            result = dc.point_fn(
                latitude=_LAT,
                longitude=_LON,
                radius_km=50.0,
                start_date=_START_DATE,
                end_date=_END_DATE,
                limit=10,
                max_runtime_s=3600.0,
            )
        else:
            result = dc.bbox_fn(
                **_BBOX,
                start_date=_START_DATE,
                end_date=_END_DATE,
                limit=10,
                max_runtime_s=3600.0,
            )
        assert result["_meta"]["success"] is True, (
            f"{dc.label}/{query_mode}: max_runtime_s=3600.0 should have allowed the query,"
            f" got error: {result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0


class TestBboxQuery:
    """Bbox queries return occurrence records with correct structure."""

    def test_returns_data(self, dc: _DatasetCase, baseline_bbox: dict):
        assert baseline_bbox["_meta"]["success"] is True, (
            f"{dc.label}: bbox query failed — {baseline_bbox['_meta'].get('error')}"
        )
        assert len(baseline_bbox["data"]) > 0, f"{dc.label}: bbox query returned no data rows"

    def test_primary_var_in_rows(self, dc: _DatasetCase, baseline_bbox: dict):
        if not baseline_bbox["data"]:
            pytest.skip(f"{dc.label}: no bbox data rows returned")
        assert dc.primary_var in baseline_bbox["data"][0]["records"][0], (
            f"{dc.label}: primary_var '{dc.primary_var}' absent from bbox record"
        )

    def test_meta_query_params_echoed(self, dc: _DatasetCase, baseline_bbox: dict):
        qp = baseline_bbox["_meta"]["query_params"]
        assert qp["min_lat"] == _BBOX["min_lat"]
        assert qp["max_lat"] == _BBOX["max_lat"]
        assert qp["min_lon"] == _BBOX["min_lon"]
        assert qp["max_lon"] == _BBOX["max_lon"]

    def test_meta_rows_returned_consistent(self, baseline_bbox: dict):
        data = baseline_bbox["data"]
        assert baseline_bbox["_meta"]["rows_returned"] == len(data)

    def test_meta_source_field(self, baseline_bbox: dict):
        assert baseline_bbox["_meta"]["source"] == "gbif"

    def test_full_response_schema_valid(self, baseline_bbox: dict):
        GroupedGeometryResponse.model_validate(baseline_bbox)

    def test_group_has_geometry(self, dc: _DatasetCase, baseline_bbox: dict):
        if not baseline_bbox["data"]:
            pytest.skip(f"{dc.label}: no bbox data returned")
        geom = baseline_bbox["data"][0]["geometry"]
        assert geom is not None, f"{dc.label}: geometry is None for first bbox group"
        GeoJsonGeometry.model_validate(geom)

    def test_lat_lon_physical_range(self, dc: _DatasetCase, baseline_bbox: dict):
        for group in baseline_bbox["data"]:
            lat = group.get("latitude")
            lon = group.get("longitude")
            if lat is not None:
                assert -90.0 <= lat <= 90.0, (
                    f"{dc.label}: bbox group latitude={lat} outside physical range"
                )
            if lon is not None:
                assert -180.0 <= lon <= 180.0, (
                    f"{dc.label}: bbox group longitude={lon} outside physical range"
                )


class TestSchemaStability:
    """Schema-stability assertions — catch GBIF structural changes early."""

    def test_primary_var_present(self, dc: _DatasetCase, point_result: dict):
        if not point_result["data"]:
            pytest.skip(f"{dc.label}: no data rows returned")
        assert dc.primary_var in point_result["data"][0]["records"][0], (
            f"{dc.label}: primary_var '{dc.primary_var}' missing — GBIF schema change?"
        )

    def test_meta_variable_info_present(self, dc: _DatasetCase, point_result: dict):
        vi = point_result["_meta"]["variable_info"]
        assert isinstance(vi, dict)
        assert len(vi) > 0, f"{dc.label}: variable_info empty"

    def test_meta_license_nonempty(self, point_result: dict):
        assert point_result["_meta"]["license"] != ""

    def test_meta_license_url_nonempty(self, point_result: dict):
        # license_url may be empty when license aggregates multiple datasets;
        # assert the key is present regardless
        assert "license_url" in point_result["_meta"]

    def test_meta_rows_returned_consistent(self, point_result: dict):
        data = point_result["data"]
        assert point_result["_meta"]["rows_returned"] == len(data)

    def test_geometry_type_is_point(self, dc: _DatasetCase, point_result: dict):
        """GBIF occurrence records always produce Point geometries."""
        if not point_result["data"]:
            pytest.skip(f"{dc.label}: no data rows returned")
        for group in point_result["data"][:10]:
            geom = group["geometry"]
            assert geom["type"] == "Point", (
                f"{dc.label}: unexpected geometry type '{geom['type']}' — expected 'Point'"
            )


class TestAvailableVariablesRoundtrip:
    """Verify that non-default variables returned by available_variables can be
    used directly in point and bbox query functions.

    For each dataset type, this test calls ``avail_fn()`` to discover available
    variables, selects up to three columns that are *not* in the curated
    default set, then issues a live query with those non-default columns and
    asserts the query succeeds and returns data.  This proves the full
    discovery → selection → query workflow end-to-end.
    """

    def test_avail_variables_usable_in_point_query(self, dc: _DatasetCase):
        avail = dc.avail_fn()
        assert avail["_meta"]["success"] is True, (
            f"{dc.label}: avail_fn() failed — {avail['_meta'].get('error')}"
        )
        default_set = set(dc.default_vars)
        non_default = [v for v in avail["data"] if v not in default_set][:3]
        if not non_default:
            pytest.skip(f"{dc.label}: no non-default variables found in avail result")
        result = dc.point_fn(
            latitude=_LAT,
            longitude=_LON,
            radius_km=50.0,
            start_date=_START_DATE,
            end_date=_END_DATE,
            variables=non_default,
            limit=20,
            max_runtime_s=120.0,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.label}: point query with non-default vars {non_default} failed"
            f" — {result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0, (
            f"{dc.label}: expected data rows for non-default vars {non_default} but got none"
        )

    def test_avail_variables_usable_in_bbox_query(self, dc: _DatasetCase):
        avail = dc.avail_fn()
        assert avail["_meta"]["success"] is True, (
            f"{dc.label}: avail_fn() failed — {avail['_meta'].get('error')}"
        )
        default_set = set(dc.default_vars)
        non_default = [v for v in avail["data"] if v not in default_set][:3]
        if not non_default:
            pytest.skip(f"{dc.label}: no non-default variables found in avail result")
        result = dc.bbox_fn(
            **_BBOX,
            start_date=_START_DATE,
            end_date=_END_DATE,
            variables=non_default,
            limit=20,
            max_runtime_s=120.0,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.label}: bbox query with non-default vars {non_default} failed"
            f" — {result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0, (
            f"{dc.label}: expected data rows for non-default vars {non_default} but got none"
        )
