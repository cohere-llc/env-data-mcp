"""Common fixtures, data structues, and assertions for integration tests.

Provides a common set of test conditions for all adapters.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any

from env_data_mcp.models import (
    AvailableVariablesResponse,
    BboxInput,
    GroupedGeometryResponse,
    PointInput,
    ResponseMeta,
    ToolResponse,
)

__all__ = [
    "AdapterSpec",
    "BboxCase",
    "DataExpectation",
    "LocationCase",
    "STANDARD_BBOXES",
    "STANDARD_END_DATE",
    "STANDARD_LOCATIONS",
    "STANDARD_START_DATE",
    "assert_all_geometry_groups_valid",
    "assert_available_variables_valid",
    "assert_geometry_group_valid",
    "assert_grouped_geometry_response_valid",
    "assert_meta_error",
    "assert_meta_success",
    "assert_meta_valid",
    "assert_point_results_in_bbox",
    "assert_tool_response_valid",
]

# ---------------------------------------------------------------------------
# Constants and Enums
# ---------------------------------------------------------------------------

# date range available is most datasets
STANDARD_START_DATE = "2022-06-01"
STANDARD_END_DATE = "2022-06-07"


class Hemisphere(StrEnum):
    """Global hemispheres."""

    NORTH = auto()
    SOUTH = auto()
    EQUATOR = auto()


class Environment(StrEnum):
    """Surface environment classes."""

    RURAL = auto()
    URBAN = auto()
    OCEAN = auto()
    POLAR = auto()


# ---------------------------------------------------------------------------
# Point-locations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocationCase:
    """A test location with geographic context."""

    label: str
    coordinates: PointInput
    hemisphere: Hemisphere
    environment: Environment
    start_date: str = STANDARD_START_DATE
    end_date: str = STANDARD_END_DATE
    description: str = ""


STANDARD_LOCATIONS: list[LocationCase] = [
    LocationCase(
        label="nh_rural",
        coordinates=PointInput(latitude=46.2531882, longitude=-119.4768203),
        hemisphere=Hemisphere.NORTH,
        environment=Environment.RURAL,
        description="Yakima River, WA",
    ),
    LocationCase(
        label="nh_urban",
        coordinates=PointInput(latitude=40.7128, longitude=-74.0060),
        hemisphere=Hemisphere.NORTH,
        environment=Environment.URBAN,
        description="New York City, NY",
    ),
    LocationCase(
        label="sh_rural",
        coordinates=PointInput(latitude=-50.0, longitude=-70.0),
        hemisphere=Hemisphere.SOUTH,
        environment=Environment.RURAL,
        description="Patagonia, Argentina",
    ),
    LocationCase(
        label="sh_urban",
        coordinates=PointInput(latitude=-23.5505, longitude=-46.6333),
        hemisphere=Hemisphere.SOUTH,
        environment=Environment.URBAN,
        description="Sao Paulo, Brazil",
    ),
    LocationCase(
        label="nh_polar",
        coordinates=PointInput(latitude=78.0, longitude=16.0),
        hemisphere=Hemisphere.NORTH,
        environment=Environment.POLAR,
        description="Svalbard, Norway",
    ),
    LocationCase(
        label="sh_polar",
        coordinates=PointInput(latitude=-78.0, longitude=0.0),
        hemisphere=Hemisphere.SOUTH,
        environment=Environment.POLAR,
        description="Antarctic coast, at meridian",
    ),
    LocationCase(
        label="ocean",
        coordinates=PointInput(latitude=0.0, longitude=-30.0),
        hemisphere=Hemisphere.EQUATOR,
        environment=Environment.OCEAN,
        description="Mid-Atlantic Ocean (equatorial)",
    ),
]


# ---------------------------------------------------------------------------
# Bbox-locations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BboxCase:
    """A bounding box with an east/west split for union-consistency testing.

    ``split_lon`` divides the full box into east and west boxes. Results for the
    full box can be compared to the combination of east and west boxes for
    consistency.
    """

    label: str
    coordinates: BboxInput
    split_lon: float
    hemisphere: Hemisphere
    environment: Environment
    start_date: str = STANDARD_START_DATE
    end_date: str = STANDARD_END_DATE
    description: str = ""


STANDARD_BBOXES: list[BboxCase] = [
    BboxCase(
        label="nh_midlat",
        coordinates=BboxInput(min_lat=44, max_lat=48, min_lon=-122, max_lon=-118),
        split_lon=-120,
        hemisphere=Hemisphere.NORTH,
        environment=Environment.RURAL,
        description="Yakima River, WA",
    ),
    BboxCase(
        label="sh_midlat",
        coordinates=BboxInput(
            min_lat=-52,
            max_lat=-48,
            min_lon=-72,
            max_lon=-68,
        ),
        split_lon=-70,
        hemisphere=Hemisphere.SOUTH,
        environment=Environment.RURAL,
        description="Patagonia, Argentia",
    ),
    BboxCase(
        label="equatorial",
        coordinates=BboxInput(
            min_lat=-2,
            max_lat=2,
            min_lon=-32,
            max_lon=-28,
        ),
        split_lon=-30,
        hemisphere=Hemisphere.EQUATOR,
        environment=Environment.OCEAN,
        description="Mid-Atlantic Ocean (equitorial)",
    ),
]


# ---------------------------------------------------------------------------
# AdapaterSpec and helper classes
# ---------------------------------------------------------------------------


@dataclass
class DataExpectation:
    """Per-adapter expectation for a specific ``LocationCase`` or ``BboxCase``."""

    has_data: bool = True
    notes: str = "Data expected in response."
    """Rationale, e.g., "US-only dataset - no coverage over SH"."""


@dataclass
class AdapterSpec:
    """Per-adapter capabilities consumed by common parameterized tests.

    Instantiate one `AdapterSpec` per unique available-variables/point-query/
    bbox-query combination (e.g., NASA POWER-MERRA2, not just NASA POWER)
    """

    name: str
    """Unique identifier used as the pytest id, e.g., ``"nasa_power_merra2"``."""

    available_variables: Callable[..., dict]
    """Tool function returning an ``AvailableVariablesResponse``-compatible dict."""

    point_query: Callable[..., dict]
    """Tool function accepting at minimum ``latitude`` and ``longitude`` and returning
    a ``PointQueryResponse``-compatible dict."""

    bbox_query: Callable[..., dict]
    """Tool function accepting at minimum ``min_lat``, ``max_lat``, ``min_lon``, and
    ``max_lon`` and returning a ``BboxQueryResponse``-compatible dict."""

    supports_date_range: bool
    """True for adapters that accept ``start_date`` and ``end_date``."""

    max_runtime_s: float | None = None
    """Runtime forwarded to query functions when not None."""

    data_expectations: dict[str, DataExpectation] = field(default_factory=dict)
    """Map ``LocationCase.label`` or ``BboxCase.label`` to expected outcome. Labels
    not present in the map are assigned the default ``DataExpectation``."""

    extra_point_kwargs: dict[str, Any] = field(default_factory=dict)
    """Extra kwargs forwarded to every ``point_query`` call for adapter-specific args."""

    extra_bbox_kwargs: dict[str, Any] = field(default_factory=dict)
    """Extra kwargs forwarded to every ``bbox_query`` call for adapter-specific args."""

    validate_point_result: Callable[[dict], None] | None = None
    """Optional adapter-specific hook called after common assertions on a point query
    result. Raise ``AssertionError`` to fail the test."""

    validate_bbox_result: Callable[[dict], None] | None = None
    """Optional adapter-specific hook called after common assertions on a bbox query
    result. Raise ``AssertionError`` to fail the test."""

    def expects_data(self, location: LocationCase | BboxCase) -> bool:
        """Return whether this adapter is expected to return data for *location*."""
        return self.data_expectations.get(location.label, DataExpectation()).has_data


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_meta_valid(meta: dict[str, Any]) -> None:
    """Assert that *meta* satisfies the ``ResponseMeta`` schema."""
    ResponseMeta.model_validate(meta)


def assert_meta_success(result: dict[str, Any]) -> None:
    """Assert that *meta* represents a successful query result."""
    meta = result["_meta"]
    assert_meta_valid(meta)
    assert meta["success"] is True, f"Expected success=True; error={meta.get('error')!r}"
    assert meta["error"] is None, f"Expected error=None; got {meta['error']!r}"
    assert isinstance(meta["rows_returned"], int)
    assert meta["rows_returned"] == len(result["data"]), (
        "rows_returned must match number of records returned; expected "
        f"{len(result['data'])}; got {meta['rows_returned']}"
    )
    assert meta["latency_s"] > 0, f"latency_s must be > 0; got {meta['latency_s']}"
    assert meta["license"], "license must be a non-empty string"
    assert meta["citation"], "citation must be a non-empty string"


def assert_meta_error(result: dict[str, Any], substr: str = "") -> None:
    """Assert that *meta* represents a failed query.

    If *substr* is provided, asserts that it appears in the ``error`` field.
    """
    meta = result["_meta"]
    assert_meta_valid(meta)
    assert meta["success"] is False, "Expected success=False"
    assert meta["error"], "error field must be a non-empty string on failure"
    if substr:
        assert substr in meta["error"], (
            f"Expected {substr!r} in error message; got {meta['error']!r}"
        )
    assert isinstance(meta["rows_returned"], int)
    assert meta["rows_returned"] == 0
    assert len(result["data"]) == 0


def assert_available_variables_valid(result: dict[str, Any]) -> None:
    """Assert that *result* satisfies the ``AvailableVariablesResponse`` schema."""
    AvailableVariablesResponse.model_validate(result)
    assert result["data"], "available_variables returned an empty dict"
    assert_meta_success(result)
    for var_name, info in result["data"].items():
        assert var_name, "variable name must be non-empty"
        assert info.get("description"), f"variable {var_name!r} missing a non-empty 'description'"
        assert "units" in info, f"variable {var_name!r} missing 'units' key"


def assert_geometry_group_valid(group: dict[str, Any]) -> None:
    """Assert that a *group* is a valid ``GeometryGroup`` dict."""

    geom = group.get("geometry")
    assert geom
    assert isinstance(geom, dict), f"geometry must be a dict; got {type(geom)}"
    assert "type" in geom, "geometry missing 'type' key"
    assert "coordinates" in geom, "geometry missing 'coordinates' key"
    if geom["type"] == "Point":
        coords = geom["coordinates"]
        assert len(coords) == 2, "Point geometry must have two coordinates"
        lon, lat = coords[0], coords[1]
        assert -180.0 <= lon <= 180.0, f"Point longitude {lon} out of WGS84 range [-180, 180]"
        assert -90.0 <= lat <= 90.0, f"Point latitude {lat} out of WGS84 range [-90, 90]"
    # TODO Add validation of Polygon geometries (SSURGO)
    assert "records" in group, "geometry group missing 'records' key"
    assert isinstance(group["records"], list), "'records' must be a list"
    assert len(group["records"]) > 0, "'records' cannot be emtpy"


def assert_all_geometry_groups_valid(result: dict[str, Any]) -> None:
    """Assert that all data grouped by geometry are valid is a result dict."""
    assert isinstance(result["data"], list), "'data' must be a list"
    for group in result["data"]:
        assert_geometry_group_valid(group)


def assert_grouped_geometry_response_valid(result: dict[str, Any]) -> None:
    """Assert that *result* satisfies the ``GroupedGeometryResponse`` schema."""
    GroupedGeometryResponse.model_validate(result)


def assert_tool_response_valid(result: dict[str, Any]) -> None:
    """Assert that *result* satisfies the ``ToolResponse`` schema."""
    ToolResponse.model_validate(result)


# ---------------------------------------------------------------------------
# Point-in-bbox consistency helper
# ---------------------------------------------------------------------------


def _extract_lat_lon_pairs(data: list[dict[str, Any]], precision: int) -> set[tuple[float, float]]:
    """Extract ``(lat, lon)`` pairs from a response ``data`` list."""
    pairs: set[tuple[float, float]] = set()
    for group in data:
        geom = group.get("geometry")
        if isinstance(geom, dict) and geom.get("type") == "Point":
            coords = geom.get("coordinates", [])
            if len(coords) == 2:
                lon, lat = float(coords[0]), float(coords[1])
                pairs.add((round(lat, precision), round(lon, precision)))
    return pairs


def assert_point_results_in_bbox(
    point_data: list[dict[str, Any]],
    bbox_data: list[dict[str, Any]],
    *,
    precision: int = 2,
) -> None:
    """Assert that every (lat, lon) from a point query also appears in the
    corresponding bbox query result.

    Coordinate values are rounded to *precision* decimal places before comarison.

    Silently skips non-Point geometries (e.g., Polygon from SSURGO).
    """
    if not point_data:
        return

    point_pairs = _extract_lat_lon_pairs(point_data, precision)
    if not point_pairs:
        return  # non-Point geometries

    bbox_pairs = _extract_lat_lon_pairs(bbox_data, precision)
    missing = point_pairs - bbox_pairs
    assert not missing, (
        f"Point query returned (lat, lon) pairs absent from the bbox query result.\n"
        f"  Missing from bbox: {missing}\n"
        f"  All bbox pairs:    {bbox_pairs}"
    )
