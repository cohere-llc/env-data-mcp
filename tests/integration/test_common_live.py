"""Common integration tests run against all adapters."""

from __future__ import annotations

from typing import Any

import pytest

from .adapter_specs import ALL_ADAPTER_SPECS
from .common import (
    NH_MIDLAT_BBOX,
    NH_RURAL,
    STANDARD_BBOXES,
    STANDARD_LOCATIONS,
    AdapterSpec,
    BboxCase,
    LocationCase,
    assert_available_variables_valid,
    assert_meta_success,
    assert_point_results_in_bbox,
    assert_slow_query_blocked,
    extract_lat_lon_pairs,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Query kwarg builders
# ---------------------------------------------------------------------------


def _point_kwargs(
    spec: AdapterSpec,
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    *,
    max_runtime_s_override: float | None = None,
) -> dict[str, Any]:
    """Build point query kwargs for *spec* at the given location."""
    return {
        "latitude": lat,
        "longitude": lon,
        **({"start_date": start_date, "end_date": end_date} if spec.supports_date_range else {}),
        **(
            {"max_runtime_s": runtime}
            if (
                runtime := max_runtime_s_override
                if max_runtime_s_override is not None
                else spec.max_runtime_s
            )
            is not None
            else {}
        ),
        **spec.extra_point_kwargs,
    }


def _location_case_kwargs(
    spec: AdapterSpec,
    loc: LocationCase,
    *,
    max_runtime_s_override: float | None = None,
) -> dict[str, Any]:
    """Convenience function for building point kwargs from a ``LocationCase``."""
    return _point_kwargs(
        spec,
        loc.coordinates.latitude,
        loc.coordinates.longitude,
        loc.start_date,
        loc.end_date,
        max_runtime_s_override=max_runtime_s_override,
    )


def _bbox_kwargs(
    spec: AdapterSpec,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    *,
    max_runtime_s_override: float | None = None,
) -> dict[str, Any]:
    """Build bbox query kwargs for *spec* for the given dimensions."""
    return {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        **({"start_date": start_date, "end_date": end_date} if spec.supports_date_range else {}),
        **(
            {"max_runtime_s": runtime}
            if (
                runtime := max_runtime_s_override
                if max_runtime_s_override is not None
                else spec.max_runtime_s
            )
            is not None
            else {}
        ),
        **spec.extra_bbox_kwargs,
    }


def _bbox_case_kwargs(
    spec: AdapterSpec,
    bbox: BboxCase,
    *,
    max_runtime_s_override: float | None = None,
) -> dict[str, Any]:
    """Convenience function for building bbox query kwargs from a ``BboxCase``."""
    return _bbox_kwargs(
        spec,
        bbox.coordinates.min_lat,
        bbox.coordinates.max_lat,
        bbox.coordinates.min_lon,
        bbox.coordinates.max_lon,
        bbox.start_date,
        bbox.end_date,
        max_runtime_s_override=max_runtime_s_override,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=ALL_ADAPTER_SPECS, ids=lambda s: s.name)
def spec(request) -> AdapterSpec:
    """Parameterized over every registered adapter spec."""
    return request.param


@pytest.fixture(scope="module")
def avail_result(spec: AdapterSpec) -> dict[str, Any]:
    """Available-variables query result; fetched once per module run."""
    return spec.available_variables()


@pytest.fixture(params=STANDARD_LOCATIONS, ids=lambda p: p.label)
def loc(request) -> LocationCase:
    """Parameterized over all standard test point locations."""
    return request.param


@pytest.fixture(params=STANDARD_BBOXES, ids=lambda b: b.label)
def bbox_case(request) -> BboxCase:
    """Parameterized over all standard test bounding boxes."""
    return request.param


# ---------------------------------------------------------------------------
# TestAvailableVariables
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """``available_variables`` returns a valid schema and non-empty variables catalog."""

    def test_schema_and_meta(self, spec: AdapterSpec, avail_result: dict) -> None:
        assert_available_variables_valid(avail_result)


# ---------------------------------------------------------------------------
# TestPointQuery
# ---------------------------------------------------------------------------


class TestPointQuery:
    """Point queries at all standard locations: metadata, schema, and adapter hooks."""

    def test_meta_at_location(self, spec: AdapterSpec, loc: LocationCase) -> None:
        result = spec.point_query(**_location_case_kwargs(spec, loc))
        assert_meta_success(result)
        if spec.expects_data(loc):
            assert result["_meta"]["geometries_returned"] > 0
            assert result["_meta"]["total_records_returned"] > 0
        else:
            assert result["_meta"]["geometries_returned"] == 0
            assert result["_meta"]["total_records_returned"] == 0

    def test_adapter_hook_at_location(self, spec: AdapterSpec, loc: LocationCase) -> None:
        if spec.validate_point_result is None:
            pytest.skip(f"{spec.name}: no validate_point_result hook registered")
        if not spec.expects_data(loc):
            pytest.skip(f"{spec.name}: no data expected at {loc.label!r}; skipping hook")
        result = spec.point_query(**_location_case_kwargs(spec, loc))
        spec.validate_point_result(result)


# ---------------------------------------------------------------------------
# TestBboxQuery
# ---------------------------------------------------------------------------


class TestBboxQuery:
    """Bbox queries at all standard bboxes: metadata, schema, consistency, and adapter hooks."""

    def test_meta_at_bbox(self, spec: AdapterSpec, bbox_case: BboxCase) -> None:
        result = spec.bbox_query(**_bbox_case_kwargs(spec, bbox_case))
        assert_meta_success(result)
        if spec.expects_data(bbox_case):
            assert result["_meta"]["geometries_returned"] > 0
            assert result["_meta"]["total_records_returned"] > 0
        else:
            assert result["_meta"]["geometries_returned"] == 0
            assert result["_meta"]["total_records_returned"] == 0

    def test_adapter_hook_at_bbox(self, spec: AdapterSpec, bbox_case: BboxCase) -> None:
        if spec.validate_bbox_result is None:
            pytest.skip(f"{spec.name}: no validate_bbox_result hook registered")
        if not spec.expects_data(bbox_case):
            pytest.skip(f"{spec.name}: no data expected at {bbox_case.label!r}; skipping hook")
        result = spec.bbox_query(**_bbox_case_kwargs(spec, bbox_case))
        spec.validate_bbox_result(result)

    def test_point_in_bbox_consistency(
        self,
        spec: AdapterSpec,
        bbox_case: BboxCase,
    ) -> None:
        """Every (lat, lon) from a bbox-center point query appears in the full bbox result."""
        if not spec.expects_data(bbox_case):
            pytest.skip(
                f"{spec.name}: no data expected at {bbox_case.label!r}; skipping consistency check"
            )
        center_lat = (bbox_case.coordinates.min_lat + bbox_case.coordinates.max_lat) / 2.0
        center_lon = (bbox_case.coordinates.min_lon + bbox_case.coordinates.max_lon) / 2.0
        point_result = spec.point_query(
            **_point_kwargs(
                spec,
                center_lat,
                center_lon,
                bbox_case.start_date,
                bbox_case.end_date,
            )
        )
        bbox_result = spec.bbox_query(**_bbox_case_kwargs(spec, bbox_case))
        assert_point_results_in_bbox(point_result["data"], bbox_result["data"])

    def test_adjacent_bbox_union(
        self,
        spec: AdapterSpec,
        bbox_case: BboxCase,
    ) -> None:
        """West and East sub-bboxes must union to equal the full bbox results."""
        if not getattr(spec, "supports_bbox_union_test", True):
            pytest.skip(f"{spec.name}: bbox union consistency not guaranteed for this adapter")
        if not spec.expects_data(bbox_case):
            pytest.skip(
                f"{spec.name}: no data expected at {bbox_case.label!r}; skipping sub-box test"
            )
        coords = bbox_case.coordinates
        west_result = spec.bbox_query(
            **_bbox_kwargs(
                spec,
                coords.min_lat,
                coords.max_lat,
                coords.min_lon,
                bbox_case.split_lon,
                bbox_case.start_date,
                bbox_case.end_date,
            ),
        )
        east_result = spec.bbox_query(
            **_bbox_kwargs(
                spec,
                coords.min_lat,
                coords.max_lat,
                bbox_case.split_lon,
                coords.max_lon,
                bbox_case.start_date,
                bbox_case.end_date,
            ),
        )
        full_result = spec.bbox_query(**_bbox_case_kwargs(spec, bbox_case))

        west_pairs = extract_lat_lon_pairs(west_result["data"], 2)
        east_pairs = extract_lat_lon_pairs(east_result["data"], 2)
        full_pairs = extract_lat_lon_pairs(full_result["data"], 2)

        assert west_pairs | east_pairs == full_pairs, (
            f"{spec.name}/{bbox_case.label}: union of adjacent sub-bbox pairs"
            f" != full bbox pairs.\n"
            f"  west + east: {west_pairs | east_pairs}\n"
            f"  full:         {full_pairs}\n"
            f"  only in west + east: {(west_pairs | east_pairs) - full_pairs}\n"
            f"  only in full:       {full_pairs - (west_pairs | east_pairs)}"
        )


# ---------------------------------------------------------------------------
# TestNonDefaultVariable
# ---------------------------------------------------------------------------


class TestNonDefaultVariable:
    """Requesting a non-default variable returns it in the output records."""

    def test_non_default_variable_returned(self, spec: AdapterSpec) -> None:
        all_vars = spec.available_variables()["data"]
        extra = next((v for v in all_vars if v not in spec.default_variables), None)
        if extra is None:
            pytest.skip(f"{spec.name}: every available variable is in the default set")
        result = spec.point_query(
            **_location_case_kwargs(spec, NH_RURAL),
            variables=[extra],
        )
        assert_meta_success(result)
        records = result["data"][0]["records"]
        assert any(extra in rec for rec in records), (
            f"{spec.name}: non-default variable {extra!r} absent from all records"
        )


# ---------------------------------------------------------------------------
# TestUnavailableVariable
# ---------------------------------------------------------------------------


class TestUnavailableVariable:
    """Requesting a non-existent variable does not error; it is reported in metadata."""

    _BOGUS = "DOES_NOT_EXIST_XYZ"

    def _unavail_result(self, spec: AdapterSpec) -> dict:
        return spec.point_query(**_location_case_kwargs(spec, NH_RURAL), variables=[self._BOGUS])

    def test_nonexistent_variable_in_unavailable_list(self, spec: AdapterSpec) -> None:
        result = self._unavail_result(spec)
        assert_meta_success(result)
        assert self._BOGUS in result["_meta"]["unavailable_variables"], (
            f"{spec.name}: {self._BOGUS!r} not reported in unavailable_variables"
        )

    def test_nonexistent_variable_absent_from_records(self, spec: AdapterSpec) -> None:
        result = self._unavail_result(spec)
        assert len(result["data"]) == 0, (
            f"{spec.name}: unexpected data in invalid variable name query"
        )


# ---------------------------------------------------------------------------
# TestMaxRuntimeGate
# ---------------------------------------------------------------------------


class TestMaxRuntimeGate:
    """``max_runtime_s=0.0`` blocks queries; a generous limit allows them."""

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_zero_max_runtime_blocks_query(self, spec: AdapterSpec, query_mode: str) -> None:
        if query_mode == "point":
            result = spec.point_query(
                **_location_case_kwargs(spec, NH_RURAL, max_runtime_s_override=0.0)
            )
        else:
            result = spec.bbox_query(
                **_bbox_case_kwargs(spec, NH_MIDLAT_BBOX, max_runtime_s_override=0.0)
            )
        assert_slow_query_blocked(result)

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_generous_max_runtime_allows_query(self, spec: AdapterSpec, query_mode: str) -> None:
        if query_mode == "point":
            result = spec.point_query(
                **_location_case_kwargs(spec, NH_RURAL, max_runtime_s_override=3600.0)
            )
        else:
            result = spec.bbox_query(
                **_bbox_case_kwargs(spec, NH_MIDLAT_BBOX, max_runtime_s_override=3600.0)
            )
        assert_meta_success(result)
        assert len(result["data"]) > 0, (
            f"{spec.name}/{query_mode}: max_runtime_s=3600.0 should have returned data"
        )
