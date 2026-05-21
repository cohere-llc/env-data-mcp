"""Parameterized integration tests for all 8 SSURGO query types.

All tests require live USDA SDA HTTP access.  Run with:
    uv run pytest tests/integration/test_ssurgo_live.py -m integration -v --no-cov
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from env_data_mcp.sources.ssurgo import (
    _NO_COVERAGE_MSG,
    ssurgo_area_summary_available_variables,
    ssurgo_area_summary_bbox_query,
    ssurgo_area_summary_query,
    ssurgo_ecological_site_available_variables,
    ssurgo_ecological_site_bbox_query,
    ssurgo_ecological_site_query,
    ssurgo_parent_material_available_variables,
    ssurgo_parent_material_bbox_query,
    ssurgo_parent_material_query,
    ssurgo_seasonal_hydrology_available_variables,
    ssurgo_seasonal_hydrology_bbox_query,
    ssurgo_seasonal_hydrology_query,
    ssurgo_soil_profile_available_variables,
    ssurgo_soil_profile_bbox_query,
    ssurgo_soil_profile_query,
    ssurgo_soil_suitability_available_variables,
    ssurgo_soil_suitability_bbox_query,
    ssurgo_soil_suitability_query,
    ssurgo_soil_temperature_available_variables,
    ssurgo_soil_temperature_bbox_query,
    ssurgo_soil_temperature_query,
    ssurgo_subsurface_barriers_available_variables,
    ssurgo_subsurface_barriers_bbox_query,
    ssurgo_subsurface_barriers_query,
)
from env_data_mcp.sources.ssurgo.constants import (
    DEFAULT_AREA_SUMMARY_VARIABLES,
    DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    DEFAULT_PARENT_MATERIAL_VARIABLES,
    DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    DEFAULT_SOIL_PROFILE_VARIABLES,
    DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Query geometry constants
# ---------------------------------------------------------------------------

# Yakima River WA: confirmed SSURGO coverage for all 8 query types
_LAT = 46.2531882
_LON = -119.4768203

# 0.5° × 1° bbox in Yakima Valley — covers multiple map units, fast per timing model
_BBOX = dict(min_lat=46.0, max_lat=46.5, min_lon=-120.0, max_lon=-119.0)

# Paris, France: outside SSURGO coverage
_NON_US_LAT = 48.8566
_NON_US_LON = 2.3522


# ---------------------------------------------------------------------------
# Per-query-type parameter table
# ---------------------------------------------------------------------------


@dataclass
class _QueryCase:
    label: str
    point_fn: Callable
    bbox_fn: Callable
    avail_fn: Callable
    # Variable-based query types (all except soil_suitability)
    default_vars: list[str] = field(default_factory=list)
    custom_var: str = ""  # A non-default column name to use in custom-var tests
    # Suitability (rule_names-based)
    default_rule_names: list[str] = field(default_factory=list)
    uses_rule_names: bool = False
    # Structural assertions
    primary_col: str = "mukey"  # Column expected in every result row
    # Optional plausible-value check (soil_profile only)
    plausible_col: str = ""
    plausible_lo: float = 0.0
    plausible_hi: float = 100.0


_QUERY_CASES = [
    pytest.param(
        _QueryCase(
            label="soil_profile",
            point_fn=ssurgo_soil_profile_query,
            bbox_fn=ssurgo_soil_profile_bbox_query,
            avail_fn=ssurgo_soil_profile_available_variables,
            default_vars=DEFAULT_SOIL_PROFILE_VARIABLES,
            custom_var="dbtenthbar_r",  # bulk density at 0.1 bar, chorizon — not in defaults
            primary_col="sandtotal_r",
            plausible_col="sandtotal_r",
            plausible_lo=0.0,
            plausible_hi=100.0,
        ),
        id="soil_profile",
    ),
    pytest.param(
        _QueryCase(
            label="area_summary",
            point_fn=ssurgo_area_summary_query,
            bbox_fn=ssurgo_area_summary_bbox_query,
            avail_fn=ssurgo_area_summary_available_variables,
            default_vars=DEFAULT_AREA_SUMMARY_VARIABLES,
            custom_var="aws025wta",  # available water storage 0–25 cm, muaggatt — not in defaults
            primary_col="drclassdcd",
        ),
        id="area_summary",
    ),
    pytest.param(
        _QueryCase(
            label="subsurface_barriers",
            point_fn=ssurgo_subsurface_barriers_query,
            bbox_fn=ssurgo_subsurface_barriers_bbox_query,
            avail_fn=ssurgo_subsurface_barriers_available_variables,
            default_vars=DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
            custom_var="resdept_h",  # restriction top depth high, corestrictions — not in defaults
            primary_col="mukey",
        ),
        id="subsurface_barriers",
    ),
    pytest.param(
        _QueryCase(
            label="seasonal_hydrology",
            point_fn=ssurgo_seasonal_hydrology_query,
            bbox_fn=ssurgo_seasonal_hydrology_bbox_query,
            avail_fn=ssurgo_seasonal_hydrology_available_variables,
            default_vars=DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
            custom_var="soimoistdepb_r",  # bottom of saturation zone, cosoilmoist — not in defaults
            primary_col="month",
        ),
        id="seasonal_hydrology",
    ),
    pytest.param(
        _QueryCase(
            label="soil_suitability",
            point_fn=ssurgo_soil_suitability_query,
            bbox_fn=ssurgo_soil_suitability_bbox_query,
            avail_fn=ssurgo_soil_suitability_available_variables,
            default_rule_names=DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
            uses_rule_names=True,
            primary_col="mrulename",
        ),
        id="soil_suitability",
    ),
    pytest.param(
        _QueryCase(
            label="ecological_site",
            point_fn=ssurgo_ecological_site_query,
            bbox_fn=ssurgo_ecological_site_bbox_query,
            avail_fn=ssurgo_ecological_site_available_variables,
            default_vars=DEFAULT_ECOLOGICAL_SITE_VARIABLES,
            custom_var="ecoclasstypename",  # class type name, coecoclass — not in defaults
            primary_col="ecoclassid",
        ),
        id="ecological_site",
    ),
    pytest.param(
        _QueryCase(
            label="parent_material",
            point_fn=ssurgo_parent_material_query,
            bbox_fn=ssurgo_parent_material_bbox_query,
            avail_fn=ssurgo_parent_material_available_variables,
            default_vars=DEFAULT_PARENT_MATERIAL_VARIABLES,
            custom_var="pmgenmod",  # parent material genetic modifier, copm — not in defaults
            primary_col="pmkind",
        ),
        id="parent_material",
    ),
    pytest.param(
        _QueryCase(
            label="soil_temperature",
            point_fn=ssurgo_soil_temperature_query,
            bbox_fn=ssurgo_soil_temperature_bbox_query,
            avail_fn=ssurgo_soil_temperature_available_variables,
            default_vars=DEFAULT_SOIL_TEMPERATURE_VARIABLES,
            custom_var="soitempdept_l",  # top depth low end, cosoiltemp — not in defaults
            primary_col="soitempmm",
        ),
        id="soil_temperature",
    ),
]


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=_QUERY_CASES)
def qc(request) -> _QueryCase:
    return request.param


@pytest.fixture(scope="module")
def baseline_point(qc: _QueryCase) -> dict:
    """Default-variable/rule point query at Yakima WA; run once per query type."""
    if qc.uses_rule_names:
        return qc.point_fn(
            latitude=_LAT,
            longitude=_LON,
            rule_names=qc.default_rule_names,
            max_runtime_s=120.0,
        )
    return qc.point_fn(
        latitude=_LAT,
        longitude=_LON,
        variables=qc.default_vars,
        max_runtime_s=120.0,
    )


@pytest.fixture(scope="module")
def baseline_bbox(qc: _QueryCase) -> dict:
    """Default-variable/rule bbox query at Yakima WA; run once per query type."""
    if qc.uses_rule_names:
        return qc.bbox_fn(
            **_BBOX,
            rule_names=qc.default_rule_names,
            max_runtime_s=120.0,
        )
    return qc.bbox_fn(
        **_BBOX,
        variables=qc.default_vars,
        max_runtime_s=120.0,
    )


# ---------------------------------------------------------------------------
# Test classes — all parametrized by the `qc` fixture (8 query types)
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """available_variables tool returns a non-empty result with the expected shape."""

    def test_returns_nonempty(self, qc: _QueryCase):
        result = qc.avail_fn()
        key = "rule_names" if qc.uses_rule_names else "variables"
        assert len(result[key]) > 0, f"{qc.label}: avail result is empty"

    def test_result_key_present(self, qc: _QueryCase):
        result = qc.avail_fn()
        key = "rule_names" if qc.uses_rule_names else "variables"
        assert key in result, f"{qc.label}: expected key '{key}' missing from avail result"

    def test_primary_col_listed(self, qc: _QueryCase):
        result = qc.avail_fn()
        if qc.uses_rule_names:
            rule_names = result["rule_names"]
            assert any(r in rule_names for r in qc.default_rule_names), (
                f"{qc.label}: none of the default rule names found in SDA cointerp"
            )
        else:
            all_vars = [v["variable"] for t_vars in result["variables"].values() for v in t_vars]
            assert qc.primary_col in all_vars, (
                f"{qc.label}: primary_col '{qc.primary_col}' absent from available variables"
                " — SDA schema change?"
            )

    def test_meta_success(self, qc: _QueryCase):
        result = qc.avail_fn()
        assert result["_meta"]["success"] is True, (
            f"{qc.label}: avail_fn meta.success is False — {result['_meta'].get('error')}"
        )

    def test_all_default_vars_present(self, qc: _QueryCase):
        if qc.uses_rule_names:
            pytest.skip("soil_suitability uses rule_names, not variable columns")
        result = qc.avail_fn()
        all_vars = [v["variable"] for t_vars in result["variables"].values() for v in t_vars]
        missing = [v for v in qc.default_vars if v not in all_vars]
        assert not missing, (
            f"{qc.label}: default variables missing from available set: {missing}"
            " — SDA schema change?"
        )

    def test_more_than_defaults_available(self, qc: _QueryCase):
        """SDA exposes additional columns beyond the curated default set."""
        if qc.uses_rule_names:
            pytest.skip("soil_suitability uses rule_names, not variable columns")
        result = qc.avail_fn()
        all_vars = [v["variable"] for t_vars in result["variables"].values() for v in t_vars]
        assert len(all_vars) > len(qc.default_vars), (
            f"{qc.label}: expected more columns than the {len(qc.default_vars)} defaults,"
            f" but only got {len(all_vars)}"
        )

    def test_each_entry_has_variable_name_and_metadata(self, qc: _QueryCase):
        """Every entry has a non-empty 'variable', 'label', and 'units' field.

        Labels and units are parsed from the SDA Tables and Columns Report PDF
        (``TablesAndColumnsReport.pdf``) downloaded once per process.  Units
        may legitimately be empty for dimensionless quantities such as pH; for
        those columns the ``units`` key is absent from the entry rather than
        present with an empty value.
        """
        if qc.uses_rule_names:
            pytest.skip("soil_suitability uses rule_names, not variable columns")
        result = qc.avail_fn()
        for table, entries in result["variables"].items():
            for entry in entries:
                assert entry.get("variable"), (
                    f"{qc.label}/{table}: entry missing non-empty 'variable': {entry!r}"
                )
                assert entry.get("label"), (
                    f"{qc.label}/{table}: entry missing non-empty 'label': {entry!r}"
                )
                if "units" in entry:
                    assert entry["units"], (
                        f"{qc.label}/{table}: entry has empty 'units' string: {entry!r}"
                    )


class TestPointQueryStructure:
    """Baseline default-variable point query: structure and meta fields."""

    def test_success_is_true(self, baseline_point: dict):
        assert baseline_point["_meta"]["success"] is True

    def test_returns_data(self, qc: _QueryCase, baseline_point: dict):
        assert len(baseline_point["data"]) > 0, (
            f"{qc.label}: expected data rows at Yakima WA but got none"
        )

    def test_primary_col_in_row(self, qc: _QueryCase, baseline_point: dict):
        if not baseline_point["data"]:
            pytest.skip(f"{qc.label}: no data rows returned")
        assert qc.primary_col in baseline_point["data"][0], (
            f"{qc.label}: primary_col '{qc.primary_col}' absent from first row"
        )

    def test_meta_source_field(self, baseline_point: dict):
        assert baseline_point["_meta"]["source"] == "ssurgo"

    def test_meta_auth_not_required(self, baseline_point: dict):
        assert baseline_point["_meta"]["auth_required"] is False

    def test_meta_latency_positive(self, baseline_point: dict):
        assert baseline_point["_meta"]["latency_s"] > 0

    def test_meta_query_params_echoed(self, baseline_point: dict):
        qp = baseline_point["_meta"]["query_params"]
        assert qp["latitude"] == _LAT
        assert qp["longitude"] == _LON

    def test_meta_license_nonempty(self, baseline_point: dict):
        assert baseline_point["_meta"]["license"] != ""

    def test_meta_variable_info_present(self, qc: _QueryCase, baseline_point: dict):
        if qc.uses_rule_names:
            pytest.skip("soil_suitability does not populate variable_info")
        vi = baseline_point["_meta"]["variable_info"]
        assert isinstance(vi, dict)
        assert len(vi) > 0, f"{qc.label}: variable_info is empty"

    def test_meta_rows_returned_consistent(self, baseline_point: dict):
        assert baseline_point["_meta"]["rows_returned"] == len(baseline_point["data"])

    def test_default_vars_present_in_rows(self, qc: _QueryCase, baseline_point: dict):
        if not baseline_point["data"]:
            pytest.skip(f"{qc.label}: no data rows returned")
        row = baseline_point["data"][0]
        if qc.uses_rule_names:
            assert "mrulename" in row, f"{qc.label}: mrulename absent from suitability row"
        else:
            found = [v for v in qc.default_vars if v in row]
            assert len(found) > 0, f"{qc.label}: no default variables found in output row"


class TestNonDefaultVariable:
    """Requesting a non-default variable/rule returns that column in result rows."""

    def test_custom_var_returned_in_point_query(self, qc: _QueryCase):
        if qc.uses_rule_names:
            # Dynamically pick a non-default rule from the available list
            avail = qc.avail_fn()
            custom = next(
                (r for r in avail["rule_names"] if r not in qc.default_rule_names),
                None,
            )
            if custom is None:
                pytest.skip(f"{qc.label}: all available rules are in the default set")
            result = qc.point_fn(
                latitude=_LAT,
                longitude=_LON,
                rule_names=[custom],
                max_runtime_s=120.0,
            )
            assert result["_meta"]["success"] is True, (
                f"{qc.label}: custom rule '{custom}' query failed — {result['_meta'].get('error')}"
            )
            # Rows may be empty if the soil has no rating for this rule
            if result["data"]:
                assert "mrulename" in result["data"][0]
        else:
            result = qc.point_fn(
                latitude=_LAT,
                longitude=_LON,
                variables=[qc.custom_var],
                max_runtime_s=120.0,
            )
            assert result["_meta"]["success"] is True, (
                f"{qc.label}: custom variable '{qc.custom_var}' query failed"
                f" — {result['_meta'].get('error')}"
            )
            assert len(result["data"]) > 0, (
                f"{qc.label}: no data returned for custom variable '{qc.custom_var}'"
            )
            assert qc.custom_var in result["data"][0], (
                f"{qc.label}: requested column '{qc.custom_var}' absent from output row"
            )


class TestNonCoveragePoint:
    """Queries outside SSURGO coverage return empty data with the no-coverage message."""

    def _run_non_us(self, qc: _QueryCase) -> dict:
        if qc.uses_rule_names:
            return qc.point_fn(
                latitude=_NON_US_LAT,
                longitude=_NON_US_LON,
                rule_names=qc.default_rule_names,
                max_runtime_s=120.0,
            )
        return qc.point_fn(
            latitude=_NON_US_LAT,
            longitude=_NON_US_LON,
            variables=qc.default_vars,
            max_runtime_s=120.0,
        )

    def test_non_us_point_returns_empty(self, qc: _QueryCase):
        result = self._run_non_us(qc)
        assert result["_meta"]["success"] is True, (
            f"{qc.label}: non-US query should succeed (no exception), but success=False"
        )
        assert result["data"] == [], (
            f"{qc.label}: expected empty data for non-US point, got {len(result['data'])} rows"
        )

    def test_non_us_point_error_message(self, qc: _QueryCase):
        result = self._run_non_us(qc)
        assert result["_meta"]["error"] == _NO_COVERAGE_MSG, (
            f"{qc.label}: expected _NO_COVERAGE_MSG, got: {result['_meta'].get('error')!r}"
        )


class TestMaxRuntimeGate:
    """max_runtime_s=0.0 must block; max_runtime_s=3600.0 must allow."""

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_zero_max_runtime_blocks_query(self, qc: _QueryCase, query_mode: str):
        if query_mode == "point":
            if qc.uses_rule_names:
                result = qc.point_fn(
                    latitude=_LAT,
                    longitude=_LON,
                    rule_names=qc.default_rule_names,
                    max_runtime_s=0.0,
                )
            else:
                result = qc.point_fn(
                    latitude=_LAT,
                    longitude=_LON,
                    variables=qc.default_vars,
                    max_runtime_s=0.0,
                )
        else:
            if qc.uses_rule_names:
                result = qc.bbox_fn(
                    **_BBOX,
                    rule_names=qc.default_rule_names,
                    max_runtime_s=0.0,
                )
            else:
                result = qc.bbox_fn(
                    **_BBOX,
                    variables=qc.default_vars,
                    max_runtime_s=0.0,
                )
        assert result["_meta"]["success"] is False, (
            f"{qc.label}/{query_mode}: max_runtime_s=0.0 should have blocked the query"
        )
        assert result["_meta"]["slow_query_warning"] is True
        assert result["data"] == []

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_generous_max_runtime_allows_query(self, qc: _QueryCase, query_mode: str):
        if query_mode == "point":
            if qc.uses_rule_names:
                result = qc.point_fn(
                    latitude=_LAT,
                    longitude=_LON,
                    rule_names=qc.default_rule_names,
                    max_runtime_s=3600.0,
                )
            else:
                result = qc.point_fn(
                    latitude=_LAT,
                    longitude=_LON,
                    variables=qc.default_vars,
                    max_runtime_s=3600.0,
                )
        else:
            if qc.uses_rule_names:
                result = qc.bbox_fn(
                    **_BBOX,
                    rule_names=qc.default_rule_names,
                    max_runtime_s=3600.0,
                )
            else:
                result = qc.bbox_fn(
                    **_BBOX,
                    variables=qc.default_vars,
                    max_runtime_s=3600.0,
                )
        assert result["_meta"]["success"] is True, (
            f"{qc.label}/{query_mode}: max_runtime_s=3600.0 should have allowed the query,"
            f" got error: {result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0


class TestBboxQuery:
    """Bbox queries return map-unit records with correct structure."""

    def test_returns_data(self, qc: _QueryCase, baseline_bbox: dict):
        assert baseline_bbox["_meta"]["success"] is True, (
            f"{qc.label}: bbox query failed — {baseline_bbox['_meta'].get('error')}"
        )
        assert len(baseline_bbox["data"]) > 0, f"{qc.label}: bbox query returned no data rows"

    def test_primary_col_in_rows(self, qc: _QueryCase, baseline_bbox: dict):
        if not baseline_bbox["data"]:
            pytest.skip(f"{qc.label}: no bbox data rows returned")
        for row in baseline_bbox["data"]:
            assert qc.primary_col in row, (
                f"{qc.label}: primary_col '{qc.primary_col}' absent from bbox row"
            )

    def test_meta_query_params_echoed(self, qc: _QueryCase, baseline_bbox: dict):
        qp = baseline_bbox["_meta"]["query_params"]
        assert qp["min_lat"] == _BBOX["min_lat"]
        assert qp["max_lat"] == _BBOX["max_lat"]
        assert qp["min_lon"] == _BBOX["min_lon"]
        assert qp["max_lon"] == _BBOX["max_lon"]

    def test_meta_rows_returned_consistent(self, baseline_bbox: dict):
        assert baseline_bbox["_meta"]["rows_returned"] == len(baseline_bbox["data"])

    def test_custom_var_returned(self, qc: _QueryCase):
        if qc.uses_rule_names:
            avail = qc.avail_fn()
            custom = next(
                (r for r in avail["rule_names"] if r not in qc.default_rule_names),
                None,
            )
            if custom is None:
                pytest.skip(f"{qc.label}: all available rules are in the default set")
            result = qc.bbox_fn(
                **_BBOX,
                rule_names=[custom],
                max_runtime_s=120.0,
            )
            assert result["_meta"]["success"] is True, (
                f"{qc.label}: bbox custom rule '{custom}' query failed"
            )
        else:
            result = qc.bbox_fn(
                **_BBOX,
                variables=[qc.custom_var],
                max_runtime_s=120.0,
            )
            assert result["_meta"]["success"] is True, (
                f"{qc.label}: bbox custom var '{qc.custom_var}' query failed"
            )
            if result["data"]:
                assert qc.custom_var in result["data"][0], (
                    f"{qc.label}: custom column '{qc.custom_var}' absent from bbox row"
                )


class TestSchemaStability:
    """Schema-stability assertions — catch SDA structural changes early."""

    def test_primary_col_present(self, qc: _QueryCase, baseline_point: dict):
        if not baseline_point["data"]:
            pytest.skip(f"{qc.label}: no data rows returned")
        assert qc.primary_col in baseline_point["data"][0], (
            f"{qc.label}: primary_col '{qc.primary_col}' missing — SDA schema change?"
        )

    def test_meta_variable_info_present(self, qc: _QueryCase, baseline_point: dict):
        if qc.uses_rule_names:
            pytest.skip("soil_suitability does not populate variable_info")
        vi = baseline_point["_meta"]["variable_info"]
        assert isinstance(vi, dict)
        assert len(vi) > 0, f"{qc.label}: variable_info empty — mdstatcolmas catalogue unavailable?"

    def test_meta_license_nonempty(self, baseline_point: dict):
        assert baseline_point["_meta"]["license"] != ""
        assert baseline_point["_meta"]["license_url"] != ""

    def test_meta_rows_returned_consistent(self, baseline_point: dict):
        assert baseline_point["_meta"]["rows_returned"] == len(baseline_point["data"])

    def test_plausible_value_range(self, qc: _QueryCase, baseline_point: dict):
        """Numeric plausible-range check — currently configured for soil_profile sand %."""
        if not qc.plausible_col:
            pytest.skip(f"{qc.label}: no plausible_col configured")
        col = qc.plausible_col
        values = [float(r[col]) for r in baseline_point["data"] if r.get(col) is not None]
        if not values:
            pytest.skip(f"{qc.label}: all rows have NULL for '{col}'")
        for v in values:
            assert qc.plausible_lo <= v <= qc.plausible_hi, (
                f"{qc.label}: {col}={v} outside expected range"
                f" [{qc.plausible_lo}, {qc.plausible_hi}] — fill value or unit change?"
            )
