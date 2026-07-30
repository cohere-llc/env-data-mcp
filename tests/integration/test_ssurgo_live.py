"""Integration tests for the SSURGO adapter — requires live USDA SDA access.

All tests require live USDA SDA HTTP access.  Run with:
    uv run pytest tests/integration/test_ssurgo_live.py -m integration -v --no-cov
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from env_data_mcp.models import (
    GroupedGeometryResponse,
    SuitabilityRulesResponse,
)
from env_data_mcp.sources.ssurgo import (
    ssurgo_area_summary_available_variables,
    ssurgo_area_summary_bbox_query,
    ssurgo_area_summary_point_query,
    ssurgo_ecological_site_available_variables,
    ssurgo_ecological_site_bbox_query,
    ssurgo_ecological_site_point_query,
    ssurgo_parent_material_available_variables,
    ssurgo_parent_material_bbox_query,
    ssurgo_parent_material_point_query,
    ssurgo_seasonal_hydrology_available_variables,
    ssurgo_seasonal_hydrology_bbox_query,
    ssurgo_seasonal_hydrology_point_query,
    ssurgo_soil_profile_available_variables,
    ssurgo_soil_profile_bbox_query,
    ssurgo_soil_profile_point_query,
    ssurgo_soil_suitability_available_rule_names,
    ssurgo_soil_suitability_bbox_query,
    ssurgo_soil_suitability_point_query,
    ssurgo_soil_temperature_available_variables,
    ssurgo_soil_temperature_bbox_query,
    ssurgo_soil_temperature_point_query,
    ssurgo_subsurface_barriers_available_variables,
    ssurgo_subsurface_barriers_bbox_query,
    ssurgo_subsurface_barriers_point_query,
)
from env_data_mcp.sources.ssurgo._constants import (
    DEFAULT_AREA_SUMMARY_VARIABLES,
    DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    DEFAULT_PARENT_MATERIAL_VARIABLES,
    DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    DEFAULT_SOIL_PROFILE_VARIABLES,
    DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
)

from .common import (
    AdapterSpec,
    DataExpectation,
    assert_grouped_geometry_response_valid,
    assert_meta_success,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Query geometry constants
# ---------------------------------------------------------------------------

# Yakima River WA: confirmed SSURGO coverage for all 8 query types
_LAT = 46.2531882
_LON = -119.4768203

# 0.5x1-degree bbox in Yakima Valley - covers multiple map units, fast per timing model
_BBOX = dict(min_lat=46.0, max_lat=46.5, min_lon=-120.0, max_lon=-119.0)

# Paris, France: outside SSURGO coverage
_NON_US_LAT = 48.8566
_NON_US_LON = 2.3522


# ---------------------------------------------------------------------------
# Adapter-specific validate hooks - called by test_common_live.py after
# common assertions, and directly by adapter-specific tests below.
# ---------------------------------------------------------------------------


def _validate_ssurgo_point_result(result: dict) -> None:
    """SSURGO-specific assertions for a point query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "ssurgo"
    assert result["_meta"]["auth_required"] is False
    for group in result["data"]:
        assert "mukey" in group, "'mukey' absent from group wrapper"
        assert "muname" in group, "'muname' absent from group wrapper"
        assert len(group["records"]) > 0, f"mukey={group['mukey']!r} group has no records"


def _validate_ssurgo_bbox_result(result: dict) -> None:
    """SSURGO-specific assertions for a bbox query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "ssurgo"
    assert result["_meta"]["auth_required"] is False
    for group in result["data"]:
        assert "mukey" in group, "'mukey' absent from group wrapper"
        assert "muname" in group, "'muname' absent from group wrapper"
        assert len(group["records"]) > 0, f"mukey={group['mukey']!r} group has no records"


# ---------------------------------------------------------------------------
# SSURGO AdapterSpec instances exported for test_common_live.py
# ---------------------------------------------------------------------------

# All non-US / ocean locations return empty data for this US-only dataset.
_NON_US_EXPECTATIONS: dict[str, DataExpectation] = {
    "sh_rural": DataExpectation(has_data=False, notes="Non-US: Patagonia, Argentina"),
    "sh_urban": DataExpectation(has_data=False, notes="Non-US: Sao Paulo, Brazil"),
    "nh_polar": DataExpectation(has_data=False, notes="Non-US: Svalbard, Norway"),
    "sh_polar": DataExpectation(has_data=False, notes="Non-US: Antarctica"),
    "ocean": DataExpectation(has_data=False, notes="Open ocean — no SSURGO coverage"),
    "sh_midlat": DataExpectation(has_data=False, notes="Non-US: Patagonia, Argentina"),
    "equatorial": DataExpectation(has_data=False, notes="Open ocean — no SSURGO coverage"),
}

SOIL_PROFILE_SPEC = AdapterSpec(
    name="ssurgo_soil_profile",
    available_variables=ssurgo_soil_profile_available_variables,
    point_query=ssurgo_soil_profile_point_query,
    bbox_query=ssurgo_soil_profile_bbox_query,
    supports_date_range=False,
    primary_variable="sandtotal_r",
    default_variables=DEFAULT_SOIL_PROFILE_VARIABLES,
    max_runtime_s=120.0,
    data_expectations=_NON_US_EXPECTATIONS,
    validate_point_result=_validate_ssurgo_point_result,
    validate_bbox_result=_validate_ssurgo_bbox_result,
)

AREA_SUMMARY_SPEC = AdapterSpec(
    name="ssurgo_area_summary",
    available_variables=ssurgo_area_summary_available_variables,
    point_query=ssurgo_area_summary_point_query,
    bbox_query=ssurgo_area_summary_bbox_query,
    supports_date_range=False,
    primary_variable="drclassdcd",
    default_variables=DEFAULT_AREA_SUMMARY_VARIABLES,
    max_runtime_s=120.0,
    data_expectations=_NON_US_EXPECTATIONS,
    validate_point_result=_validate_ssurgo_point_result,
    validate_bbox_result=_validate_ssurgo_bbox_result,
)

SUBSURFACE_BARRIERS_SPEC = AdapterSpec(
    name="ssurgo_subsurface_barriers",
    available_variables=ssurgo_subsurface_barriers_available_variables,
    point_query=ssurgo_subsurface_barriers_point_query,
    bbox_query=ssurgo_subsurface_barriers_bbox_query,
    supports_date_range=False,
    primary_variable="reshard",
    default_variables=DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    max_runtime_s=120.0,
    data_expectations=_NON_US_EXPECTATIONS,
    validate_point_result=_validate_ssurgo_point_result,
    validate_bbox_result=_validate_ssurgo_bbox_result,
)

SEASONAL_HYDROLOGY_SPEC = AdapterSpec(
    name="ssurgo_seasonal_hydrology",
    available_variables=ssurgo_seasonal_hydrology_available_variables,
    point_query=ssurgo_seasonal_hydrology_point_query,
    bbox_query=ssurgo_seasonal_hydrology_bbox_query,
    supports_date_range=False,
    primary_variable="month",
    default_variables=DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    max_runtime_s=120.0,
    data_expectations=_NON_US_EXPECTATIONS,
    use_small_bboxes=True,  # 4-table join via comonth hits SDA row limit on 4x4-degree bbox
    validate_point_result=_validate_ssurgo_point_result,
    validate_bbox_result=_validate_ssurgo_bbox_result,
)

ECOLOGICAL_SITE_SPEC = AdapterSpec(
    name="ssurgo_ecological_site",
    available_variables=ssurgo_ecological_site_available_variables,
    point_query=ssurgo_ecological_site_point_query,
    bbox_query=ssurgo_ecological_site_bbox_query,
    supports_date_range=False,
    primary_variable="ecoclasstypename",
    default_variables=DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    max_runtime_s=120.0,
    data_expectations=_NON_US_EXPECTATIONS,
    validate_point_result=_validate_ssurgo_point_result,
    validate_bbox_result=_validate_ssurgo_bbox_result,
)

PARENT_MATERIAL_SPEC = AdapterSpec(
    name="ssurgo_parent_material",
    available_variables=ssurgo_parent_material_available_variables,
    point_query=ssurgo_parent_material_point_query,
    bbox_query=ssurgo_parent_material_bbox_query,
    supports_date_range=False,
    primary_variable="pmorder",
    default_variables=DEFAULT_PARENT_MATERIAL_VARIABLES,
    max_runtime_s=120.0,
    data_expectations=_NON_US_EXPECTATIONS,
    validate_point_result=_validate_ssurgo_point_result,
    validate_bbox_result=_validate_ssurgo_bbox_result,
)

SOIL_TEMPERATURE_SPEC = AdapterSpec(
    name="ssurgo_soil_temperature",
    available_variables=ssurgo_soil_temperature_available_variables,
    point_query=ssurgo_soil_temperature_point_query,
    bbox_query=ssurgo_soil_temperature_bbox_query,
    supports_date_range=False,
    primary_variable="soitempmm",
    default_variables=DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    max_runtime_s=120.0,
    data_expectations=_NON_US_EXPECTATIONS,
    use_small_bboxes=True,  # 4-table join via comonth hits SDA row limit on 4x4-degree bbox
    validate_point_result=_validate_ssurgo_point_result,
    validate_bbox_result=_validate_ssurgo_bbox_result,
)

# Exported for adapter_specs.py. soil_suitability is excluded because it uses
# rule_names instead of variables and is incompatible with the common test framework.
ALL_SSURGO_SPECS: list[AdapterSpec] = [
    SOIL_PROFILE_SPEC,
    AREA_SUMMARY_SPEC,
    SUBSURFACE_BARRIERS_SPEC,
    SEASONAL_HYDROLOGY_SPEC,
    ECOLOGICAL_SITE_SPEC,
    PARENT_MATERIAL_SPEC,
    SOIL_TEMPERATURE_SPEC,
]


# ---------------------------------------------------------------------------
# Adapter-specific parameter table (all 8 query types including suitability)
# ---------------------------------------------------------------------------


@dataclass
class _QueryCase:
    label: str
    spec: AdapterSpec | None  # None for soil_suitability (no AdapterSpec)
    point_fn: Callable
    bbox_fn: Callable
    avail_fn: Callable
    # Variable-based query types
    default_vars: list[str] = field(default_factory=list)
    custom_var: str = ""  # A non-default column to verify custom queries work
    # Rule-based query types
    default_rule_names: list[str] = field(default_factory=list)
    uses_rule_names: bool = False
    # Structural assertions
    primary_col: str = ""  # A column expected in every result row (inner record dict)
    # Optional plausible-value numeric check
    plausible_col: str = ""
    plausible_lo: float = 0.0
    plausible_hi: float = 100.0


_QUERY_CASES = [
    pytest.param(
        _QueryCase(
            label="soil_profile",
            spec=SOIL_PROFILE_SPEC,
            point_fn=ssurgo_soil_profile_point_query,
            bbox_fn=ssurgo_soil_profile_bbox_query,
            avail_fn=ssurgo_soil_profile_available_variables,
            default_vars=DEFAULT_SOIL_PROFILE_VARIABLES,
            custom_var="dbtenthbar_r",  # bulk density at 0.1 bar, chorizon - not in defaults
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
            spec=AREA_SUMMARY_SPEC,
            point_fn=ssurgo_area_summary_point_query,
            bbox_fn=ssurgo_area_summary_bbox_query,
            avail_fn=ssurgo_area_summary_available_variables,
            default_vars=DEFAULT_AREA_SUMMARY_VARIABLES,
            custom_var="aws025wta",  # available water storage 0-25 cm - not in defaults
            primary_col="drclassdcd",
        ),
        id="area_summary",
    ),
    pytest.param(
        _QueryCase(
            label="subsurface_barriers",
            spec=SUBSURFACE_BARRIERS_SPEC,
            point_fn=ssurgo_subsurface_barriers_point_query,
            bbox_fn=ssurgo_subsurface_barriers_bbox_query,
            avail_fn=ssurgo_subsurface_barriers_available_variables,
            default_vars=DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
            custom_var="resdept_h",  # restriction top depth high - not in defaults
            primary_col="compname",
        ),
        id="subsurface_barriers",
    ),
    pytest.param(
        _QueryCase(
            label="seasonal_hydrology",
            spec=SEASONAL_HYDROLOGY_SPEC,
            point_fn=ssurgo_seasonal_hydrology_point_query,
            bbox_fn=ssurgo_seasonal_hydrology_bbox_query,
            avail_fn=ssurgo_seasonal_hydrology_available_variables,
            default_vars=DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
            custom_var="soimoistdepb_r",  # bottom of saturation zone - not in defaults
            primary_col="month",
        ),
        id="seasonal_hydrology",
    ),
    pytest.param(
        _QueryCase(
            label="soil_suitability",
            spec=None,  # Not registered in common framework
            point_fn=ssurgo_soil_suitability_point_query,
            bbox_fn=ssurgo_soil_suitability_bbox_query,
            avail_fn=ssurgo_soil_suitability_available_rule_names,
            default_rule_names=DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
            uses_rule_names=True,
            primary_col="mrulename",
        ),
        id="soil_suitability",
    ),
    pytest.param(
        _QueryCase(
            label="ecological_site",
            spec=ECOLOGICAL_SITE_SPEC,
            point_fn=ssurgo_ecological_site_point_query,
            bbox_fn=ssurgo_ecological_site_bbox_query,
            avail_fn=ssurgo_ecological_site_available_variables,
            default_vars=DEFAULT_ECOLOGICAL_SITE_VARIABLES,
            custom_var="ecoclasstypename",  # class type name, coecoclass - not in defaults
            primary_col="ecoclassid",
        ),
        id="ecological_site",
    ),
    pytest.param(
        _QueryCase(
            label="parent_material",
            spec=PARENT_MATERIAL_SPEC,
            point_fn=ssurgo_parent_material_point_query,
            bbox_fn=ssurgo_parent_material_bbox_query,
            avail_fn=ssurgo_parent_material_available_variables,
            default_vars=DEFAULT_PARENT_MATERIAL_VARIABLES,
            custom_var="pmgenmod",  # parent material genetic modifier - not in defaults
            primary_col="pmkind",
        ),
        id="parent_material",
    ),
    pytest.param(
        _QueryCase(
            label="soil_temperature",
            spec=SOIL_TEMPERATURE_SPEC,
            point_fn=ssurgo_soil_temperature_point_query,
            bbox_fn=ssurgo_soil_temperature_bbox_query,
            avail_fn=ssurgo_soil_temperature_available_variables,
            default_vars=DEFAULT_SOIL_TEMPERATURE_VARIABLES,
            custom_var="soitempdept_l",  # top depth low end, cosoiltemp - not in defaults
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
def avail_result(qc: _QueryCase) -> dict:
    """Available-variables/rule-names result; fetched once per query type."""
    return qc.avail_fn()


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
# TestAvailableVariables - SSURGO-specific content checks
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """SSURGO-specific available-variables content (schema/meta/catalog in common tests)."""

    def test_each_entry_has_description_and_units(self, qc: _QueryCase, avail_result: dict) -> None:
        """Every catalog entry has a non-empty description and a 'units' key.

        Descriptions and units come from the SDA Tables and Columns Report PDF.
        Units may legitimately be empty for dimensionless quantities; the key
        must always be present.
        """
        if qc.uses_rule_names:
            pytest.skip(f"{qc.label}: soil_suitability uses rule_names, not variable columns")
        for col, entry in avail_result["data"].items():
            assert col, f"{qc.label}: empty column name in available variables"
            assert entry.get("description"), (
                f"{qc.label}: column {col!r} missing non-empty 'description'"
            )
            assert "units" in entry, f"{qc.label}: column {col!r} missing 'units' key"

    def test_suitability_schema(self, qc: _QueryCase, avail_result: dict) -> None:
        """soil_suitability available_rule_names validates against SuitabilityRulesResponse."""
        if not qc.uses_rule_names:
            pytest.skip(f"{qc.label}: variable-based type. schema checked by common tests")
        SuitabilityRulesResponse.model_validate(avail_result)
        assert len(avail_result["data"]) > 0, f"{qc.label}: no rule names returned"
        assert any(r in avail_result["data"] for r in qc.default_rule_names), (
            f"{qc.label}: none of the default rule names found in available rules"
        )


# ---------------------------------------------------------------------------
# TestPointQuery - SSURGO-specific structure checks
# ---------------------------------------------------------------------------


class TestPointQuery:
    """SSURGO-specific point-query assertions: group wrapper and column presence."""

    def test_group_wrapper_fields(self, qc: _QueryCase, baseline_point: dict) -> None:
        """Every geometry group carries 'mukey' and 'muname' at the top level."""
        if not baseline_point["data"]:
            pytest.skip(f"{qc.label}: no data rows returned at Yakima WA")
        for group in baseline_point["data"]:
            assert "mukey" in group, f"{qc.label}: 'mukey' absent from group wrapper"
            assert "muname" in group, f"{qc.label}: 'muname' absent from group wrapper"

    def test_primary_col_in_records(self, qc: _QueryCase, baseline_point: dict) -> None:
        """The type-specific primary column appears in the first inner record."""
        if not baseline_point["data"] or not qc.primary_col:
            pytest.skip(f"{qc.label}: no data or no primary_col defined")
        record = baseline_point["data"][0]["records"][0]
        assert qc.primary_col in record, (
            f"{qc.label}: primary_col {qc.primary_col!r} absent from first record"
        )

    def test_plausible_values_at_yakima(self, qc: _QueryCase, baseline_point: dict) -> None:
        """Numeric primary column values are within the expected plausible range."""
        if not qc.plausible_col:
            pytest.skip(f"{qc.label}: no plausible_col defined")
        for group in baseline_point["data"]:
            for record in group["records"]:
                val = record.get(qc.plausible_col)
                if val is None:
                    continue
                assert qc.plausible_lo <= float(val) <= qc.plausible_hi, (
                    f"{qc.label}: {qc.plausible_col}={val} outside "
                    f"[{qc.plausible_lo}, {qc.plausible_hi}]"
                )

    def test_custom_var_in_point_query(self, qc: _QueryCase) -> None:
        """Querying with a non-default variable returns that column in the result rows."""
        if qc.uses_rule_names:
            avail = qc.avail_fn()
            custom = next((r for r in avail["data"] if r not in qc.default_rule_names), None)
            if custom is None:
                pytest.skip(f"{qc.label}: all available rules are in the default set")
            result = qc.point_fn(
                latitude=_LAT, longitude=_LON, rule_names=[custom], max_runtime_s=120.0
            )
            assert result["_meta"]["success"] is True
            if result["data"]:
                assert "mrulename" in result["data"][0]["records"][0]
        else:
            result = qc.point_fn(
                latitude=_LAT, longitude=_LON, variables=[qc.custom_var], max_runtime_s=120.0
            )
            assert result["_meta"]["success"] is True, (
                f"{qc.label}: custom var {qc.custom_var!r} query failed: "
                f"{result['_meta'].get('error')}"
            )
            assert len(result["data"]) > 0, f"{qc.label}: no data for custom var {qc.custom_var!r}"
            assert qc.custom_var in result["data"][0]["records"][0], (
                f"{qc.label}: {qc.custom_var!r} absent from record"
            )


# ---------------------------------------------------------------------------
# TestBboxQuery - SSURGO-specific structure checks
# ---------------------------------------------------------------------------


class TestBboxQuery:
    """SSURGO-specific bbox-query assertions: group wrapper and column presence."""

    def test_group_wrapper_fields(self, qc: _QueryCase, baseline_bbox: dict) -> None:
        """Every geometry group carries 'mukey' and 'muname' at the top level."""
        if not baseline_bbox["data"]:
            pytest.skip(f"{qc.label}: no bbox data rows returned")
        for group in baseline_bbox["data"]:
            assert "mukey" in group, f"{qc.label}: 'mukey' absent from bbox group wrapper"
            assert "muname" in group, f"{qc.label}: 'muname' absent from bbox group wrapper"

    def test_primary_col_in_rows(self, qc: _QueryCase, baseline_bbox: dict) -> None:
        """The type-specific primary column appears in every bbox result row."""
        if not baseline_bbox["data"] or not qc.primary_col:
            pytest.skip(f"{qc.label}: no data or no primary_col defined")
        for group in baseline_bbox["data"]:
            assert qc.primary_col in group["records"][0], (
                f"{qc.label}: primary_col {qc.primary_col!r} absent from bbox record"
            )

    def test_custom_var_in_bbox_query(self, qc: _QueryCase) -> None:
        """Querying with a non-default variable in a bbox returns that column in result rows."""
        if qc.uses_rule_names:
            avail = qc.avail_fn()
            custom = next((r for r in avail["data"] if r not in qc.default_rule_names), None)
            if custom is None:
                pytest.skip(f"{qc.label}: all available rules are in the default set")
            result = qc.bbox_fn(**_BBOX, rule_names=[custom], max_runtime_s=120.0)
            assert result["_meta"]["success"] is True
        else:
            result = qc.bbox_fn(**_BBOX, variables=[qc.custom_var], max_runtime_s=120.0)
            assert result["_meta"]["success"] is True, (
                f"{qc.label}: custom var {qc.custom_var!r} bbox query failed"
            )
            if result["data"]:
                assert qc.custom_var in result["data"][0]["records"][0], (
                    f"{qc.label}: {qc.custom_var!r} absent from bbox record"
                )


# ---------------------------------------------------------------------------
# TestNonCoveragePoint - non-US points return empty data without error
# ---------------------------------------------------------------------------


class TestNonCoveragePoint:
    """Queries outside SSURGO coverage return empty data (success=True, error=None)."""

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

    def test_non_us_returns_empty_data(self, qc: _QueryCase) -> None:
        result = self._run_non_us(qc)
        assert_meta_success(result)
        assert result["data"] == [], (
            f"{qc.label}: expected empty data for non-US point; got {len(result['data'])} groups"
        )

    def test_non_us_schema_valid(self, qc: _QueryCase) -> None:
        result = self._run_non_us(qc)
        GroupedGeometryResponse.model_validate(result)


# ---------------------------------------------------------------------------
# TestSuitabilityMaxRuntimeGate - soil_suitability only
# ---------------------------------------------------------------------------


class TestSuitabilityMaxRuntimeGate:
    """soil_suitability max_runtime_s gate (not registered in common framework)."""

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_zero_max_runtime_blocks_query(self, query_mode: str) -> None:
        if query_mode == "point":
            result = ssurgo_soil_suitability_point_query(
                latitude=_LAT,
                longitude=_LON,
                rule_names=DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
                max_runtime_s=0.0,
            )
        else:
            result = ssurgo_soil_suitability_bbox_query(
                **_BBOX,
                rule_names=DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
                max_runtime_s=0.0,
            )
        assert result["_meta"]["success"] is False
        assert result["_meta"].get("slow_query_warning") is True
        assert result["data"] == []

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_generous_max_runtime_allows_query(self, query_mode: str) -> None:
        if query_mode == "point":
            result = ssurgo_soil_suitability_point_query(
                latitude=_LAT,
                longitude=_LON,
                rule_names=DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
                max_runtime_s=3600.0,
            )
        else:
            result = ssurgo_soil_suitability_bbox_query(
                **_BBOX,
                rule_names=DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
                max_runtime_s=3600.0,
            )
        assert result["_meta"]["success"] is True, (
            f"soil_suitability/{query_mode}: max_runtime_s=3600 should allow query; "
            f"error={result['_meta'].get('error')}"
        )
        assert len(result["data"]) > 0


# ---------------------------------------------------------------------------
# TestSoilSuitability - soil_suitability-specific tests
# ---------------------------------------------------------------------------


class TestSoilSuitability:
    """soil_suitability point and bbox queries — rule_names API."""

    @pytest.fixture(scope="class")
    def suitability_point(self) -> dict:
        return ssurgo_soil_suitability_point_query(
            latitude=_LAT,
            longitude=_LON,
            rule_names=DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
            max_runtime_s=120.0,
        )

    @pytest.fixture(scope="class")
    def suitability_bbox(self) -> dict:
        return ssurgo_soil_suitability_bbox_query(
            **_BBOX,
            rule_names=DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
            max_runtime_s=120.0,
        )

    @pytest.fixture(scope="class")
    def suitability_avail(self) -> dict:
        return ssurgo_soil_suitability_available_rule_names()

    def test_avail_returns_rule_names_list(self, suitability_avail: dict) -> None:
        assert suitability_avail["_meta"]["success"] is True
        assert isinstance(suitability_avail["data"], list)
        assert len(suitability_avail["data"]) > 0

    def test_default_rule_names_present(self, suitability_avail: dict) -> None:
        assert any(r in suitability_avail["data"] for r in DEFAULT_SOIL_SUITABILITY_RULE_NAMES), (
            "None of the default rule names found in available rules"
        )

    def test_point_returns_data(self, suitability_point: dict) -> None:
        assert_meta_success(suitability_point)
        assert len(suitability_point["data"]) > 0

    def test_point_mrulename_in_records(self, suitability_point: dict) -> None:
        if not suitability_point["data"]:
            pytest.skip("no data returned")
        assert "mrulename" in suitability_point["data"][0]["records"][0]

    def test_point_mukey_muname_in_groups(self, suitability_point: dict) -> None:
        if not suitability_point["data"]:
            pytest.skip("no data returned")
        for group in suitability_point["data"]:
            assert "mukey" in group
            assert "muname" in group

    def test_bbox_returns_data(self, suitability_bbox: dict) -> None:
        assert_meta_success(suitability_bbox)
        assert len(suitability_bbox["data"]) > 0

    def test_non_us_point_returns_empty(self) -> None:
        result = ssurgo_soil_suitability_point_query(
            latitude=_NON_US_LAT,
            longitude=_NON_US_LON,
            rule_names=DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
            max_runtime_s=120.0,
        )
        assert_meta_success(result)
        assert result["data"] == []

    def test_schema_valid(self, suitability_point: dict) -> None:
        GroupedGeometryResponse.model_validate(suitability_point)

    def test_avail_schema_valid(self, suitability_avail: dict) -> None:
        SuitabilityRulesResponse.model_validate(suitability_avail)
