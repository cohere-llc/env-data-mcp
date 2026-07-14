"""Integration tests for SoilGrids — requires live ISRIC WebCoverageService access.

All tests require live network access to the ISRIC WCS and HTML endpoints.  Run with:
    uv run --extra dev pytest tests/integration/test_soilgrids_live.py -m integration -v --no-cov

Common adapter tests (metadata, schema, variable catalog, bbox consistency) are run
automatically via test_common_live.py because SOILGRIDS_SPEC is registered in
adapter_specs.py.  The tests below focus on SoilGrids-specific behaviour: depth/quantile
variable naming, soil-property value plausibility, the single-record-per-geometry
guarantee, and fine-grained variable-selection edge cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import httpx
import pytest

from env_data_mcp.sources.soilgrids import (
    soilgrids_available_variables,
    soilgrids_bbox_query,
    soilgrids_query,
)
from env_data_mcp.sources.soilgrids.constants import (
    _LAYERS_INFO_URL,
    _WEB_MAP_SERVICE_URL,
    DEFAULT_VARIABLES,
)

from .common import (
    AdapterSpec,
    DataExpectation,
    assert_grouped_geometry_response_valid,
    assert_meta_success,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _require_soilgrids_available() -> None:
    """Skip the module if the ISRIC services are unreachable."""
    try:
        r = httpx.get(_LAYERS_INFO_URL, timeout=30)
        if r.status_code != HTTPStatus.OK:
            pytest.skip(f"SoilGrids layer info URL returned HTTP {r.status_code}")
        r = httpx.get(_WEB_MAP_SERVICE_URL, timeout=30)
        if r.status_code != HTTPStatus.OK:
            pytest.skip(f"SoilGrids WCS URL returned HTTP {r.status_code}")
    except Exception as e:
        pytest.skip(f"SoilGrids endpoints not reachable: {e}")


# ---------------------------------------------------------------------------
# Adapter-specific validate hooks - called by test_common_live.py after
# common assertions, and directly by adapter-specific tests below.
# ---------------------------------------------------------------------------


def _validate_soilgrids_point_result(result: dict) -> None:
    """SoilGrids-specific assertions for a point query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "soilgrids"
    assert result["_meta"]["auth_required"] is False
    for group in result["data"]:
        assert len(group["records"]) == 1, (
            "SoilGrids has no temporal dimension; every geometry group must carry exactly 1 record"
        )


def _validate_soilgrids_bbox_result(result: dict) -> None:
    """SoilGrids-specific assertions for a bbox query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "soilgrids"
    assert result["_meta"]["auth_required"] is False
    for group in result["data"]:
        assert len(group["records"]) == 1, (
            "SoilGrids has no temporal dimension; every geometry group must carry exactly 1 record"
        )


# ---------------------------------------------------------------------------
# SoilGrids AdapterSpec — exported for test_common_live.py
# ---------------------------------------------------------------------------

SOILGRIDS_SPEC = AdapterSpec(
    name="soilgrids",
    available_variables=soilgrids_available_variables,
    point_query=soilgrids_query,
    bbox_query=soilgrids_bbox_query,
    supports_date_range=False,
    primary_variable="soc_0-5cm_mean",
    default_variables=list(DEFAULT_VARIABLES),
    max_runtime_s=60.0,
    data_expectations={
        "sh_polar": DataExpectation(has_data=False, notes="Antarctic ice sheet: no soil data"),
        "ocean": DataExpectation(has_data=False, notes="Open Atlantic: no soil data"),
        "equatorial": DataExpectation(has_data=False, notes="Open Atlantic ocean: no soil data"),
    },
    extra_point_kwargs={"radius_km": 5.0},
    extra_bbox_kwargs={},
    use_small_bboxes=True,
    supports_bbox_bounds_test=False,
    supports_bbox_union_test=False,
    validate_point_result=_validate_soilgrids_point_result,
    validate_bbox_result=_validate_soilgrids_bbox_result,
)


# ---------------------------------------------------------------------------
# Adapter-specific dataset parameter table
# ---------------------------------------------------------------------------


@dataclass
class _DatasetCase:
    spec: AdapterSpec
    # Plausible ranges for key variables at the Yakima WA test location
    bdod_range: tuple[float, float]
    phh2o_range: tuple[float, float]


_DATASET_CASES = [
    pytest.param(
        _DatasetCase(
            spec=SOILGRIDS_SPEC,
            bdod_range=(0.2, 2.5),  # bulk density g/cm3; Yakima semi-arid ag land
            phh2o_range=(3.0, 10.0),  # pH (valid global range)
        ),
        id="soilgrids",
    ),
]

# Yakima Valley, WA - primary validation location (also used in original tests)
_YAKIMA_LAT = 46.2531882
_YAKIMA_LON = -119.4768203
_YAKIMA_BBOX_KWARGS: dict[str, float] = {
    "min_lat": 46.244,
    "max_lat": 46.262,
    "min_lon": -119.490,
    "max_lon": -119.463,
}


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=_DATASET_CASES)
def dc(request) -> _DatasetCase:
    return request.param


@pytest.fixture(scope="module")
def avail_vars(dc: _DatasetCase) -> dict[str, Any]:
    """Available-variables result; loaded once per module run."""
    return dc.spec.available_variables()


@pytest.fixture(scope="module")
def yakima_point_result(dc: _DatasetCase) -> dict[str, Any]:
    """Default-variable point query at Yakima WA; loaded once per module run."""
    return dc.spec.point_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        max_runtime_s=dc.spec.max_runtime_s,
        **dc.spec.extra_point_kwargs,
    )


@pytest.fixture(scope="module")
def yakima_bbox_result(dc: _DatasetCase) -> dict[str, Any]:
    """Default-variable bbox query over the small Yakima study area; loaded once."""
    return soilgrids_bbox_query(
        **_YAKIMA_BBOX_KWARGS,
        max_runtime_s=dc.spec.max_runtime_s,
    )


# ---------------------------------------------------------------------------
# TestAvailableVariables
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """SoilGrids-specific available-variables content."""

    def test_nitrogen_variable_content(self, avail_vars: dict[str, Any]) -> None:
        """A specific non-default variable has the expected description and units."""
        assert "nitrogen_15-30cm_mean" in avail_vars["data"]
        info = avail_vars["data"]["nitrogen_15-30cm_mean"]
        assert "Nitrogen" in info["description"]
        assert len(info["units"]) > 0

    def test_depth_and_quantile_in_descriptions(self, avail_vars: dict[str, Any]) -> None:
        """Every variable description references its depth interval and statistical quantile."""
        for var_name, info in avail_vars["data"].items():
            assert "depth" in info["description"], f"{var_name}: 'depth' missing from description"
            assert "quantile" in info["description"], (
                f"{var_name}: 'quantile' missing from description"
            )


# ---------------------------------------------------------------------------
# TestPointQuery
# ---------------------------------------------------------------------------


class TestPointQuery:
    """soilgrids_query() at Yakima WA: SoilGrids-specific checks."""

    def test_query_params_echoed(self, yakima_point_result: dict[str, Any]) -> None:
        qp = yakima_point_result["_meta"]["query_params"]
        assert qp["latitude"] == pytest.approx(_YAKIMA_LAT)
        assert qp["longitude"] == pytest.approx(_YAKIMA_LON)
        assert qp["radius_km"] == pytest.approx(5.0)

    def test_default_variables_in_records(
        self, dc: _DatasetCase, yakima_point_result: dict[str, Any]
    ) -> None:
        for group in yakima_point_result["data"]:
            rec = group["records"][0]
            for var in dc.spec.default_variables:
                assert var in rec, (
                    f"{var!r} absent from record at "
                    f"({group.get('latitude')}, {group.get('longitude')})"
                )

    def test_plausible_property_values_at_yakima(
        self, dc: _DatasetCase, yakima_point_result: dict[str, Any]
    ) -> None:
        """Bulk density and pH at Yakima WA are within plausible agronomic ranges."""
        for group in yakima_point_result["data"]:
            rec = group["records"][0]
            bdod = rec.get("bdod_0-5cm_mean")
            phh2o = rec.get("phh2o_0-5cm_mean")
            if bdod is not None:
                lo, hi = dc.bdod_range
                assert lo <= bdod <= hi, f"bdod={bdod} outside [{lo}, {hi}]"
            if phh2o is not None:
                lo, hi = dc.phh2o_range
                assert lo <= phh2o <= hi, f"phh2o={phh2o} outside [{lo}, {hi}]"

    def test_at_least_one_in_bbox_point(self, yakima_point_result: dict[str, Any]) -> None:
        """At least one returned pixel falls inside the query radius bbox."""
        assert any(p["in_bbox"] for p in yakima_point_result["data"]), (
            "No returned pixel has in_bbox=True"
        )

    def test_too_small_radius_returns_no_data(self, dc: _DatasetCase) -> None:
        """A sub-pixel radius (< 250 m) returns no data records."""
        result = soilgrids_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=0.00001,
            max_runtime_s=dc.spec.max_runtime_s,
        )
        assert_meta_success(result)
        assert len(result["data"]) == 0, (
            f"Expected no data for sub-pixel radius; got {len(result['data'])} records"
        )

    def test_single_variable_query(self, dc: _DatasetCase) -> None:
        """Querying a single variable returns only that variable in each record."""
        result = soilgrids_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=0.5,
            variables=["soc_0-5cm_mean"],
            max_runtime_s=dc.spec.max_runtime_s,
        )
        assert_meta_success(result)
        assert len(result["data"]) > 0
        for group in result["data"]:
            rec = group["records"][0]
            assert "soc_0-5cm_mean" in rec
            assert len(rec) == 1, f"Expected 1 key in record; got {list(rec.keys())}"

    def test_non_standard_quantile_and_depth_variables(self, dc: _DatasetCase) -> None:
        """Non-default quantile (Q0.95) and uncertainty variables are queryable."""
        vars_ = ["soc_0-5cm_Q0.95", "silt_0-5cm_uncertainty"]
        result = soilgrids_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=0.5,
            variables=vars_,
            max_runtime_s=dc.spec.max_runtime_s,
        )
        assert_meta_success(result)
        assert len(result["data"]) > 0
        for group in result["data"]:
            for v in vars_:
                assert v in group["records"][0], f"{v!r} absent from record"

    def test_partial_unavailable_variables_returns_available_subset(self, dc: _DatasetCase) -> None:
        """When only some requested variables exist, available ones are returned."""
        result = soilgrids_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=0.5,
            variables=["soc_15-30cm_Q0.5", "foo_does_not_exist"],
            max_runtime_s=dc.spec.max_runtime_s,
        )
        assert_meta_success(result)
        assert len(result["data"]) > 0
        assert "foo_does_not_exist" in result["_meta"]["unavailable_variables"]
        for group in result["data"]:
            assert "soc_15-30cm_Q0.5" in group["records"][0]


# ---------------------------------------------------------------------------
# TestBboxQuery
# ---------------------------------------------------------------------------


class TestBboxQuery:
    """soilgrids_bbox_query() over a small Yakima study area: SoilGrids-specific checks."""

    def test_query_params_echoed(self, yakima_bbox_result: dict[str, Any]) -> None:
        qp = yakima_bbox_result["_meta"]["query_params"]
        for key, val in _YAKIMA_BBOX_KWARGS.items():
            assert qp[key] == pytest.approx(val), f"query_params[{key!r}] mismatch"

    def test_default_variables_in_variable_info(
        self, dc: _DatasetCase, yakima_bbox_result: dict[str, Any]
    ) -> None:
        vi = yakima_bbox_result["_meta"]["variable_info"]
        for var in dc.spec.default_variables:
            assert var in vi, f"{var!r} absent from variable_info"
            assert vi[var]["description"]
            assert "units" in vi[var]

    def test_default_variables_in_records(
        self, dc: _DatasetCase, yakima_bbox_result: dict[str, Any]
    ) -> None:
        for group in yakima_bbox_result["data"]:
            rec = group["records"][0]
            for var in dc.spec.default_variables:
                assert var in rec, f"{var!r} absent from record"

    def test_plausible_property_values_at_yakima(
        self, dc: _DatasetCase, yakima_bbox_result: dict[str, Any]
    ) -> None:
        """Bulk density and pH at Yakima WA are within plausible agronomic ranges."""
        for group in yakima_bbox_result["data"]:
            rec = group["records"][0]
            bdod = rec.get("bdod_0-5cm_mean")
            phh2o = rec.get("phh2o_0-5cm_mean")
            if bdod is not None:
                lo, hi = dc.bdod_range
                assert lo <= bdod <= hi, f"bdod={bdod} outside [{lo}, {hi}]"
            if phh2o is not None:
                lo, hi = dc.phh2o_range
                assert lo <= phh2o <= hi, f"phh2o={phh2o} outside [{lo}, {hi}]"

    def test_in_bbox_flag_and_coordinates(self, yakima_bbox_result: dict[str, Any]) -> None:
        """in_bbox=True points lie within the queried bbox; False points are buffer pixels."""
        assert any(p["in_bbox"] for p in yakima_bbox_result["data"]), (
            "No returned pixel has in_bbox=True"
        )
        for group in yakima_bbox_result["data"]:
            if group["in_bbox"]:
                lat, lon = group["latitude"], group["longitude"]
                assert _YAKIMA_BBOX_KWARGS["min_lat"] <= lat <= _YAKIMA_BBOX_KWARGS["max_lat"], (
                    f"in_bbox=True but lat={lat} outside query lat range"
                )
                assert _YAKIMA_BBOX_KWARGS["min_lon"] <= lon <= _YAKIMA_BBOX_KWARGS["max_lon"], (
                    f"in_bbox=True but lon={lon} outside query lon range"
                )

    def test_too_small_bbox_returns_no_data(self, dc: _DatasetCase) -> None:
        """A sub-pixel bbox (< 250 m side) returns no data records."""
        result = soilgrids_bbox_query(
            min_lat=_YAKIMA_BBOX_KWARGS["min_lat"],
            max_lat=_YAKIMA_BBOX_KWARGS["min_lat"] + 0.000001,
            min_lon=_YAKIMA_BBOX_KWARGS["min_lon"],
            max_lon=_YAKIMA_BBOX_KWARGS["min_lon"] + 0.000001,
            max_runtime_s=dc.spec.max_runtime_s,
        )
        assert_meta_success(result)
        assert len(result["data"]) == 0, (
            f"Expected no data for sub-pixel bbox; got {len(result['data'])} records"
        )
