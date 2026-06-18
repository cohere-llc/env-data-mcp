"""Integration tests for SoilGrids — requires live ISRIC WebCoverageService access.

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests call the real SoilGrids web services and require network access.
"""

from __future__ import annotations

from collections.abc import Sequence
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

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _require_soilgrids_available():
    """Skip tests if the SoilGrids services are unreachable."""
    try:
        r = httpx.get(_LAYERS_INFO_URL, timeout=30)
        if r.status_code != HTTPStatus.OK:
            pytest.skip(f"SoilGrids layer description URL returned HTTP {r.status_code}")
        r = httpx.get(_WEB_MAP_SERVICE_URL, timeout=30)
        if r.status_code != HTTPStatus.OK:
            pytest.skip(f"SoilGrids map service URL returned HTTP {r.status_code}")
    except Exception as e:
        pytest.skip(f"SoilGrids URLs not reachable: {e}")


# ---------------------------------------------------------------------------
# Available variables tool tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def var_info() -> dict[str, Any]:
    return soilgrids_available_variables()


class TestSoilgridsAvailableVariables:
    """Tests for the soilgrids_available_variables() tool."""

    def test_returns_dict_with_data(self, var_info: dict[str, Any]):
        """Test returns expected results."""
        assert isinstance(var_info, dict)
        assert "data" in var_info
        assert len(var_info["data"]) > 0

    def test_contains_known_nitrogen_variable(self, var_info: dict[str, Any]):
        """Test results include known variable data."""
        data = var_info["data"]
        assert "nitrogen_15-30cm_mean" in data
        nitro_info = data["nitrogen_15-30cm_mean"]
        assert "description" in nitro_info
        assert "Nitrogen" in nitro_info["description"]
        assert "units" in nitro_info
        assert len(nitro_info["units"]) > 0

    @pytest.mark.parametrize("var", DEFAULT_VARIABLES)
    def test_contains_default_variables(self, var_info: dict[str, Any], var: str):
        """Test results include all default variables."""
        data = var_info["data"]
        assert var in data
        assert "description" in data[var]
        assert len(data[var]["description"])
        assert "units" in data[var]

    def test_includes_non_default_variables(self, var_info: dict[str, Any]):
        """Ensure there are more than just the default variables"""
        assert len(var_info["data"]) > len(DEFAULT_VARIABLES)

    def test_contains_expected_metadata(self, var_info: dict[str, Any]):
        """Test metadata is complete and correct."""
        assert "_meta" in var_info
        meta = var_info["_meta"]
        assert "source" in meta
        assert meta["source"] == "soilgrids"
        assert "success" in meta
        assert meta["success"] is True
        assert "rows_returned" in meta
        assert meta["rows_returned"] == len(var_info["data"])
        assert "license" in meta or "license_url" in meta
        if "license" in meta:
            assert len(meta["license"]) > 0
        if "license_url" in meta:
            assert len(meta["license_url"]) > 0

    def test_contains_depth_and_quantile(self, var_info: dict[str, Any]):
        """Test variable descriptions include depth and quantile."""
        for _, info in var_info["data"].items():
            assert "depth" in info["description"]
            assert "quantile" in info["description"]


# ---------------------------------------------------------------------------
# Point query tool tests
# ---------------------------------------------------------------------------


# Test coordinates - Yakima Valley, WA
_LAT = 46.2531882
_LON = -119.4768203


@dataclass(frozen=True)
class _PointCase:
    name: str
    requested_vars: Sequence[str] | None
    expected_vars: Sequence[str]
    unavailable_vars: Sequence[str]
    lat_lon: tuple[float, float] = (_LAT, _LON)
    radius_km: float = 1.0
    expect_slow_warn: bool = False


_POINT_CASES: list[_PointCase] = [
    _PointCase("default", None, DEFAULT_VARIABLES, []),
    _PointCase("too small bbox", None, [], DEFAULT_VARIABLES, radius_km=0.00001),
    _PointCase("Nairobi, Kenya", None, DEFAULT_VARIABLES, [], lat_lon=(-1.29, 36.82)),
    _PointCase("Idalia, Australia", None, DEFAULT_VARIABLES, [], lat_lon=(-24.977, 144.673)),
    _PointCase("slow query warning", None, [], [], radius_km=10000.0, expect_slow_warn=True),
    _PointCase("single variable", ["soc_0-5cm_mean"], ["soc_0-5cm_mean"], []),
    _PointCase(
        "some non-standard",
        ["soc_0-5cm_Q0.95", "silt_0-5cm_uncertainty"],
        ["soc_0-5cm_Q0.95", "silt_0-5cm_uncertainty"],
        [],
    ),
    _PointCase("some unavailable", ["foo", "soc_15-30cm_Q0.5"], ["soc_15-30cm_Q0.5"], ["foo"]),
    _PointCase("all unavailable", ["bar", "baz", "qux"], [], ["bar", "baz", "qux"]),
]


@pytest.fixture(scope="module", params=_POINT_CASES, ids=lambda c: c.name)
def point_case(request) -> _PointCase:
    return request.param


@pytest.fixture(scope="module")
def point_result(point_case: _PointCase) -> dict[str, Any]:
    lat, lon = point_case.lat_lon
    kwargs: dict[str, float | Sequence[str]] = {
        "latitude": lat,
        "longitude": lon,
        "radius_km": point_case.radius_km,
    }
    if point_case.requested_vars is not None:
        kwargs["variables"] = point_case.requested_vars
    return soilgrids_query(**kwargs)


@pytest.fixture(scope="module")
def requested_vars_effective(point_case: _PointCase) -> list[str]:
    return list(
        DEFAULT_VARIABLES if point_case.requested_vars is None else point_case.requested_vars
    )


class TestSoilgridsQuery:
    """Tests of the soilgrids_query() tool."""

    def test_metadata_success(self, point_case: _PointCase, point_result: dict[str, Any]):
        """Tests metadata indicates success."""
        assert "_meta" in point_result
        meta = point_result["_meta"]
        if point_case.expect_slow_warn:
            assert "exceeds" in meta["message"] and "threshold" in meta["message"]
        assert meta["success"] == (not point_case.expect_slow_warn)
        assert meta["error"] is None
        assert meta["source"] == "soilgrids"

    def test_metadata_stats(self, point_case: _PointCase, point_result: dict[str, Any]):
        """Tests counts and timers in metadata."""
        meta = point_result["_meta"]
        if len(point_case.expected_vars) > 0:
            assert meta["latency_s"] > 1.0  # should take at least a second
            assert meta["rows_returned"] > 0
        else:
            assert meta["rows_returned"] == 0

    def test_metadata_variables_echoed(
        self, requested_vars_effective: list[str], point_result: dict[str, Any]
    ):
        """Tests that the variables list in metadata mirrors what was requested."""
        got = point_result["_meta"]["variables"]
        assert len(got) == len(requested_vars_effective)
        for var in requested_vars_effective:
            assert var in got

    def test_metadata_unavailable_variables(
        self, point_case: _PointCase, point_result: dict[str, Any]
    ):
        """Tests that the expected unavailable variables are returned."""
        got = point_result["_meta"]["unavailable_variables"]
        assert len(got) == len(point_case.unavailable_vars)
        for var in point_case.unavailable_vars:
            assert var in got

    def test_metadata_variable_info(self, point_case: _PointCase, point_result: dict[str, Any]):
        """Tests that variable info in metadata is as expected."""
        got = point_result["_meta"]["variable_info"]
        assert len(got) == len(point_case.expected_vars)
        for var in point_case.expected_vars:
            assert var in got
            assert "description" in got[var]
            assert "units" in got[var]

    def test_geojson_geometry_in_expected_range(
        self, point_case: _PointCase, point_result: dict[str, Any]
    ):
        """Test that points returned are in or near the bounding box."""
        for point in point_result["data"]:
            assert point["longitude"] == point["geometry"]["coordinates"][0]
            assert point["latitude"] == point["geometry"]["coordinates"][1]
            assert -90.0 <= point["latitude"] <= 90.0
            assert -180.0 <= point["longitude"] <= 180.0

    def test_data_includes_variables(self, point_case: _PointCase, point_result: dict[str, Any]):
        """Test that data point returned have the expected records."""
        for point in point_result["data"]:
            assert len(point["records"]) == 1, (
                "only one record set per point for SoilGrids (no temporal changes)."
            )
            assert len(point["records"][0]) == len(point_case.expected_vars)
            for var in point_case.expected_vars:
                assert var in point["records"][0]

    def test_data_has_expected_property_values(
        self, point_case: _PointCase, point_result: dict[str, Any]
    ):
        """Test that point values in the PNW location have reasonable values for density and pH."""
        if point_case.lat_lon == (_LAT, _LON) and point_case.expected_vars == DEFAULT_VARIABLES:
            for point in point_result["data"]:
                assert 0.2 <= point["records"][0]["bdod_0-5cm_mean"] <= 2.5
                assert 3 <= point["records"][0]["phh2o_0-5cm_mean"] <= 10

    def test_has_in_bbox_point_when_variables_available(
        self, point_case: _PointCase, point_result: dict[str, Any]
    ):
        """Test that data inside the bounding box is returned when variables are available."""
        any_in_bbox = any(p["in_bbox"] for p in point_result["data"])
        assert any_in_bbox == (len(point_case.expected_vars) > 0)


# ---------------------------------------------------------------------------
# BBox query tool tests
# ---------------------------------------------------------------------------


# Test coordinates - Yakima Valley, WA
_MIN_LAT = 46.244
_MAX_LAT = 46.262
_MIN_LON = -119.490
_MAX_LON = -119.463


@dataclass(frozen=True)
class _BBoxCase:
    name: str
    requested_vars: Sequence[str] | None
    expected_vars: Sequence[str]
    unavailable_vars: Sequence[str]
    bbox: tuple[float, float, float, float] = (_MIN_LAT, _MAX_LAT, _MIN_LON, _MAX_LON)
    expect_slow_warn: bool = False


_BBOX_CASES: list[_BBoxCase] = [
    _BBoxCase("default", None, DEFAULT_VARIABLES, []),
    _BBoxCase(
        "too small bbox",
        None,
        [],
        DEFAULT_VARIABLES,
        bbox=(_MIN_LAT, _MIN_LAT + 0.000001, _MIN_LON, _MIN_LON + 0.000001),
    ),
    _BBoxCase("Nairobi, Kenya", None, DEFAULT_VARIABLES, [], bbox=(-1.29, -1.28, 36.82, 36.83)),
    _BBoxCase(
        "Idalia, Australia", None, DEFAULT_VARIABLES, [], bbox=(-24.98, -24.97, 144.67, 144.68)
    ),
    _BBoxCase(
        "slow query warning", None, [], [], bbox=(50.0, 62.0, -30.0, 10.0), expect_slow_warn=True
    ),
    _BBoxCase("single variable", ["soc_0-5cm_mean"], ["soc_0-5cm_mean"], []),
    _BBoxCase(
        "some non-standard",
        ["soc_0-5cm_Q0.95", "silt_0-5cm_uncertainty"],
        ["soc_0-5cm_Q0.95", "silt_0-5cm_uncertainty"],
        [],
    ),
    _BBoxCase("some unavailable", ["foo", "soc_15-30cm_Q0.5"], ["soc_15-30cm_Q0.5"], ["foo"]),
    _BBoxCase("all unavailable", ["bar", "baz", "qux"], [], ["bar", "baz", "qux"]),
]


@pytest.fixture(scope="module", params=_BBOX_CASES, ids=lambda c: c.name)
def bbox_case(request) -> _BBoxCase:
    return request.param


@pytest.fixture(scope="module")
def bbox_result(bbox_case: _BBoxCase) -> dict[str, Any]:
    min_lat, max_lat, min_lon, max_lon = bbox_case.bbox
    kwargs: dict[str, float | Sequence[str]] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }
    if bbox_case.requested_vars is not None:
        kwargs["variables"] = bbox_case.requested_vars
    return soilgrids_bbox_query(**kwargs)


@pytest.fixture(scope="module")
def requested_vars_effective_bbox(bbox_case: _BBoxCase) -> list[str]:
    return list(DEFAULT_VARIABLES if bbox_case.requested_vars is None else bbox_case.requested_vars)


class TestSoilgridsBBoxQuery:
    """Tests of the soilgrids_bbox_query() tool."""

    def test_metadata_success(self, bbox_case: _BBoxCase, bbox_result: dict[str, Any]):
        """Tests metadata indicates success."""
        assert "_meta" in bbox_result
        meta = bbox_result["_meta"]
        if bbox_case.expect_slow_warn:
            assert "exceeds" in meta["message"] and "threshold" in meta["message"]
        assert meta["success"] == (not bbox_case.expect_slow_warn)
        assert meta["error"] is None
        assert meta["source"] == "soilgrids"

    def test_metadata_stats(self, bbox_case: _BBoxCase, bbox_result: dict[str, Any]):
        """Tests counts and timers in metadata."""
        meta = bbox_result["_meta"]
        if len(bbox_case.expected_vars) > 0:
            assert meta["latency_s"] > 1.0  # should take at least a second
            assert meta["rows_returned"] > 0
        else:
            assert meta["rows_returned"] == 0

    def test_metadata_variables_echoed(
        self, requested_vars_effective_bbox: list[str], bbox_result: dict[str, Any]
    ):
        """Tests that the variables list in metadata mirrors what was requested."""
        got = bbox_result["_meta"]["variables"]
        assert len(got) == len(requested_vars_effective_bbox)
        for var in requested_vars_effective_bbox:
            assert var in got

    def test_metadata_unavailable_variables(
        self, bbox_case: _BBoxCase, bbox_result: dict[str, Any]
    ):
        """Tests that the expected unavailable variables are returned."""
        got = bbox_result["_meta"]["unavailable_variables"]
        assert len(got) == len(bbox_case.unavailable_vars)
        for var in bbox_case.unavailable_vars:
            assert var in got

    def test_metadata_variable_info(self, bbox_case: _BBoxCase, bbox_result: dict[str, Any]):
        """Tests that variable info in metadata is as expected."""
        got = bbox_result["_meta"]["variable_info"]
        assert len(got) == len(bbox_case.expected_vars)
        for var in bbox_case.expected_vars:
            assert var in got
            assert "description" in got[var]
            assert "units" in got[var]

    def test_geojson_geometry_in_expected_range(
        self, bbox_case: _BBoxCase, bbox_result: dict[str, Any]
    ):
        """Test that bboxs returned are in or near the bounding box."""
        for bbox in bbox_result["data"]:
            assert bbox["longitude"] == bbox["geometry"]["coordinates"][0]
            assert bbox["latitude"] == bbox["geometry"]["coordinates"][1]
            assert -90.0 <= bbox["latitude"] <= 90.0
            assert -180.0 <= bbox["longitude"] <= 180.0
            is_in_bbox = bool(
                (bbox_case.bbox[0] <= bbox["latitude"] <= bbox_case.bbox[1])
                and (bbox_case.bbox[2] <= bbox["longitude"] <= bbox_case.bbox[3])
            )
            assert bbox["in_bbox"] == is_in_bbox

    def test_data_includes_variables(self, bbox_case: _BBoxCase, bbox_result: dict[str, Any]):
        """Test that data bbox returned have the expected records."""
        for bbox in bbox_result["data"]:
            assert len(bbox["records"]) == 1, (
                "only one record set per bbox for SoilGrids (no temporal changes)."
            )
            assert len(bbox["records"][0]) == len(bbox_case.expected_vars)
            for var in bbox_case.expected_vars:
                assert var in bbox["records"][0]

    def test_data_has_expected_property_values(
        self, bbox_case: _BBoxCase, bbox_result: dict[str, Any]
    ):
        """Test that bbox values in the PNW location have reasonable values for density and pH."""
        if (
            bbox_case.bbox == (_MIN_LAT, _MAX_LAT, _MIN_LON, _MAX_LON)
            and bbox_case.expected_vars == DEFAULT_VARIABLES
        ):
            for bbox in bbox_result["data"]:
                assert 0.2 <= bbox["records"][0]["bdod_0-5cm_mean"] <= 2.5
                assert 3 <= bbox["records"][0]["phh2o_0-5cm_mean"] <= 10

    def test_has_in_bbox_bbox_when_variables_available(
        self, bbox_case: _BBoxCase, bbox_result: dict[str, Any]
    ):
        """Test that data inside the bounding box is returned when variables are available."""
        any_in_bbox = any(p["in_bbox"] for p in bbox_result["data"])
        assert any_in_bbox == (len(bbox_case.expected_vars) > 0)
