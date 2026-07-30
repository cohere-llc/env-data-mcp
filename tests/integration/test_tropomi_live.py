"""Integration tests for the Sentinel 5-TROPOMI adapter — requires live AWS S3 access.

All tests require network access to the MEEO S3 bucket and the Copernicus Data
Space Ecosystem (CDSE) OData API.  Run with:
    uv run pytest tests/integration/test_tropomi_live.py -m integration -v --no-cov
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import httpx
import pytest

from env_data_mcp.sources.tropomi._constants import DEFAULT_VARIABLES, PRODUCT_TYPES, ProductType
from env_data_mcp.sources.tropomi._query import VariableInfo, _get_netcdf_file_paths
from env_data_mcp.sources.tropomi.tools import (
    tropomi_available_variables,
    tropomi_bbox_query,
    tropomi_point_query,
)

from .common import (
    NH_MIDLAT_SMALL_BBOX,
    NH_RURAL,
    AdapterSpec,
    DataExpectation,
    assert_grouped_geometry_response_valid,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

_AWS_TROPOMI_HEALTH = "https://meeo-s5p.s3.amazonaws.com"


@pytest.fixture(scope="module", autouse=True)
def _require_tropomi_available():
    """Skip all tests if the TROPOMI S3 bucket is not accessible."""
    try:
        r = httpx.get(_AWS_TROPOMI_HEALTH, timeout=10)
        r.raise_for_status()
    except Exception as e:
        pytest.skip(f"TROPOMI AWS S3 bucket not reachable: {e}")


# ---------------------------------------------------------------------------
# Adapter-specific validate hooks — called by test_common_live.py after
# common assertions, and directly by adapter-specific tests below.
# ---------------------------------------------------------------------------


def _validate_tropomi_point_result(result: dict) -> None:
    """TROPOMI-specific assertions for a point query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "tropomi"
    assert result["_meta"]["auth_required"] is False
    for group in result["data"]:
        assert group.get("geometry", {}).get("type") == "Point", (
            "TROPOMI point query must return Point geometries"
        )
        assert "latitude" in group, "TROPOMI group missing top-level 'latitude'"
        assert "longitude" in group, "TROPOMI group missing top-level 'longitude'"
        for rec in group["records"]:
            assert "date" in rec, "TROPOMI record missing 'date' key"


def _validate_tropomi_bbox_result(result: dict) -> None:
    """TROPOMI-specific assertions for a bbox query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "tropomi"
    assert result["_meta"]["auth_required"] is False
    for group in result["data"]:
        assert group.get("geometry", {}).get("type") == "Point", (
            "TROPOMI bbox query must return Point geometries"
        )
        assert "latitude" in group, "TROPOMI group missing top-level 'latitude'"
        assert "longitude" in group, "TROPOMI group missing top-level 'longitude'"


# ---------------------------------------------------------------------------
# TROPOMI AdapterSpec — exported for test_common_live.py
# ---------------------------------------------------------------------------

TROPOMI_SPEC = AdapterSpec(
    name="tropomi",
    available_variables=tropomi_available_variables,
    point_query=tropomi_point_query,
    bbox_query=tropomi_bbox_query,
    supports_date_range=True,
    primary_variable="OFFL-L2_NO2",
    default_variables=DEFAULT_VARIABLES,
    max_runtime_s=120.0,
    data_expectations={
        "sh_polar": DataExpectation(
            has_data=False,
            notes="Antarctic polar night in June; no TROPOMI data expected",
        ),
    },
    supports_bbox_union_test=False,  # raster pixel boundary effects at split_lon
    use_small_bboxes=True,  # 4×4-degree bbox with 6 vars × 7 days would be very slow
    validate_point_result=_validate_tropomi_point_result,
    validate_bbox_result=_validate_tropomi_bbox_result,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def avail_result() -> dict[str, Any]:
    """Available variables; loaded once per module run."""
    return tropomi_available_variables()


@pytest.fixture(scope="module")
def nh_rural_result() -> dict[str, Any]:
    """Point query at NH_RURAL over the standard date window."""
    return tropomi_point_query(
        latitude=NH_RURAL.coordinates.latitude,
        longitude=NH_RURAL.coordinates.longitude,
        start_date=NH_RURAL.start_date,
        end_date=NH_RURAL.end_date,
        max_runtime_s=TROPOMI_SPEC.max_runtime_s,
    )


@pytest.fixture(scope="module")
def nh_midlat_bbox_result() -> dict[str, Any]:
    """Bbox query over the 1×1-degree NH_MIDLAT small bbox."""
    return tropomi_bbox_query(
        min_lat=NH_MIDLAT_SMALL_BBOX.coordinates.min_lat,
        max_lat=NH_MIDLAT_SMALL_BBOX.coordinates.max_lat,
        min_lon=NH_MIDLAT_SMALL_BBOX.coordinates.min_lon,
        max_lon=NH_MIDLAT_SMALL_BBOX.coordinates.max_lon,
        start_date=NH_MIDLAT_SMALL_BBOX.start_date,
        end_date=NH_MIDLAT_SMALL_BBOX.end_date,
        max_runtime_s=TROPOMI_SPEC.max_runtime_s,
    )


# ---------------------------------------------------------------------------
# TestAvailableVariables — TROPOMI-specific content checks
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """TROPOMI-specific available-variables content checks."""

    def test_methane_variable_info(self, avail_result: dict[str, Any]) -> None:
        """OFFL-L2_CH4 entry has correct description and units."""
        data = avail_result["data"]
        assert "OFFL-L2_CH4" in data, "'OFFL-L2_CH4' absent from available variables"
        ch4 = data["OFFL-L2_CH4"]
        assert any(word in ch4["description"].lower() for word in ["methane", "ch4"]), (
            f"'OFFL-L2_CH4' description {ch4['description']!r} does not mention methane"
        )
        assert "offline" in ch4["description"].lower(), (
            f"'OFFL-L2_CH4' description {ch4['description']!r} does not mention 'offline'"
        )
        assert ch4["units"] == "ppb", f"Expected CH4 units 'ppb'; got {ch4['units']!r}"

    def test_product_type_in_description(self, avail_result: dict[str, Any]) -> None:
        """Every variable's description includes its product-type label."""
        for key, val in avail_result["data"].items():
            parts = key.split("-")
            assert len(parts) >= 2, f"Variable key {key!r} does not match PRODUCT-name format"
            product = parts[0]
            assert product in PRODUCT_TYPES, (
                f"Variable {key!r}: prefix {product!r} not in _PRODUCT_TYPES"
            )
            assert PRODUCT_TYPES[product] in val["description"], (
                f"Variable {key!r}: product type description {PRODUCT_TYPES[product]!r} "
                f"absent from description {val['description']!r}"
            )


# ---------------------------------------------------------------------------
# TestPointQuery — TROPOMI-specific structural checks
# ---------------------------------------------------------------------------


class TestPointQuery:
    """TROPOMI-specific point-query assertions."""

    def test_source_and_auth(self, nh_rural_result: dict[str, Any]) -> None:
        assert nh_rural_result["_meta"]["source"] == "tropomi"
        assert nh_rural_result["_meta"]["auth_required"] is False

    def test_geometry_is_point(self, nh_rural_result: dict[str, Any]) -> None:
        """All returned geometry groups have GeoJSON Point geometries."""
        for group in nh_rural_result["data"]:
            assert group.get("geometry", {}).get("type") == "Point", (
                "Expected Point geometry for TROPOMI point query"
            )

    def test_lat_lon_in_group_header(self, nh_rural_result: dict[str, Any]) -> None:
        """Each group carries top-level 'latitude' and 'longitude' fields."""
        for group in nh_rural_result["data"]:
            assert "latitude" in group, "TROPOMI group missing top-level 'latitude'"
            assert "longitude" in group, "TROPOMI group missing top-level 'longitude'"
            # Top-level values must match the Point geometry coordinates
            coords = group["geometry"]["coordinates"]
            assert group["longitude"] == pytest.approx(coords[0])
            assert group["latitude"] == pytest.approx(coords[1])

    def test_date_key_in_records(self, nh_rural_result: dict[str, Any]) -> None:
        """Every record contains an ISO 8601 date string."""
        for group in nh_rural_result["data"]:
            for rec in group["records"]:
                assert "date" in rec, "TROPOMI record missing 'date' key"
                assert len(rec["date"]) == 10, f"Expected YYYY-MM-DD date; got {rec['date']!r}"

    def test_no2_plausible_at_yakima(self, nh_rural_result: dict[str, Any]) -> None:
        """Tropospheric NO2 column over Yakima Valley falls in a plausible range."""
        no2_values = [
            rec["OFFL-L2_NO2"]
            for group in nh_rural_result["data"]
            for rec in group["records"]
            if "OFFL-L2_NO2" in rec
        ]
        if not no2_values:
            pytest.skip("No OFFL-L2_NO2 values returned — skipping plausible-range check")
        for val in no2_values:
            # Tropospheric NO2 column over rural WA: typically 0–0.001 mol/m².
            # Small negatives (~-0.001) are valid retrievals near the detection limit.
            assert -0.001 <= val <= 0.01, (
                f"NO2={val:.2e} mol/m² outside plausible range [-0.001, 0.01]"
            )


# ---------------------------------------------------------------------------
# TestBboxQuery — TROPOMI-specific structural checks
# ---------------------------------------------------------------------------


class TestBboxQuery:
    """TROPOMI-specific bbox-query assertions."""

    def test_source_and_auth(self, nh_midlat_bbox_result: dict[str, Any]) -> None:
        assert nh_midlat_bbox_result["_meta"]["source"] == "tropomi"
        assert nh_midlat_bbox_result["_meta"]["auth_required"] is False

    def test_multiple_pixels_in_1deg_bbox(self, nh_midlat_bbox_result: dict[str, Any]) -> None:
        """A 1x1-degree bbox returns more than one distinct pixel grid cell."""
        assert len(nh_midlat_bbox_result["data"]) > 1, (
            "Expected multiple TROPOMI pixel groups for a 1x1-degree bbox; "
            f"got {len(nh_midlat_bbox_result['data'])}"
        )

    def test_geometry_is_point(self, nh_midlat_bbox_result: dict[str, Any]) -> None:
        for group in nh_midlat_bbox_result["data"]:
            assert group.get("geometry", {}).get("type") == "Point"

    def test_lat_lon_in_group_header(self, nh_midlat_bbox_result: dict[str, Any]) -> None:
        """Each bbox group carries top-level lat/lon matching its Point geometry."""
        for group in nh_midlat_bbox_result["data"]:
            assert "latitude" in group
            assert "longitude" in group
            coords = group["geometry"]["coordinates"]
            assert group["longitude"] == pytest.approx(coords[0])
            assert group["latitude"] == pytest.approx(coords[1])

    def test_date_key_in_records(self, nh_midlat_bbox_result: dict[str, Any]) -> None:
        """Every bbox record has a valid ISO 8601 date string."""
        for group in nh_midlat_bbox_result["data"]:
            for rec in group["records"]:
                assert "date" in rec
                assert len(rec["date"]) == 10, f"Expected YYYY-MM-DD; got {rec['date']!r}"

    def test_no2_plausible_at_yakima(self, nh_midlat_bbox_result: dict[str, Any]) -> None:
        """Tropospheric NO2 column over the Yakima Valley bbox is in a plausible range."""
        no2_values = [
            rec["OFFL-L2_NO2"]
            for group in nh_midlat_bbox_result["data"]
            for rec in group["records"]
            if "OFFL-L2_NO2" in rec
        ]
        if not no2_values:
            pytest.skip("No OFFL-L2_NO2 values returned — skipping plausible-range check")
        for val in no2_values:
            assert -0.001 <= val <= 0.01, (
                f"NO2={val:.2e} mol/m2 outside plausible range [-0.001, 0.01]"
            )


# ---------------------------------------------------------------------------
# TestGetS3FilePaths — internal CDSE/S3 file-path discovery
# ---------------------------------------------------------------------------


def _new_variable(
    name: str,
    *,
    description: str = "",
    units: str = "",
    product_type: ProductType = ProductType.NRTI,
    property_name: str = "",
    underscored_name: str = "",
    cogt_name: str = "",
) -> VariableInfo:
    """Create a stub _VariableInfo for TestGetS3FilePaths."""
    return VariableInfo(
        name=name,
        description=description,
        units=units,
        product_type=product_type,
        property_name=property_name,
        underscored_name=underscored_name,
        cogt_name=cogt_name,
    )


@dataclass(frozen=True)
class _NetCDFPathTest:
    name: str
    variable: VariableInfo
    start_date: str
    end_date: str
    geometry: str
    expect_results: bool = True
    expected_name_prefix: str = ""


# Southern California point/bbox used for S3 path tests (close to TROPOMI test origin)
_SOCAL_POINT = "geography'SRID=4326;POINT(-116.4856 33.8434)'"
_SOCAL_POLYGON = (
    "geography'SRID=4326;POLYGON((-117.0 33.5,-116.0 33.5,-116.0 34.5,-117.0 34.5,-117.0 33.5))'"
)

_NETCDF_PATH_TESTS: list[_NetCDFPathTest] = [
    _NetCDFPathTest(
        "point - ozone",
        variable=_new_variable(
            "OFFL-L2_O3",
            product_type=ProductType.OFFL,
            property_name="L2_O3",
            underscored_name="L2__O3____",
        ),
        start_date="2024-01-03",
        end_date="2024-01-05",
        geometry=_SOCAL_POINT,
        expected_name_prefix="S5P_OFFL_L2__O3",
    ),
    _NetCDFPathTest(
        "polygon - methane",
        variable=_new_variable(
            "OFFL-L2_CH4",
            product_type=ProductType.OFFL,
            property_name="L2_CH4",
            underscored_name="L2__CH4___",
        ),
        start_date="2024-01-03",
        end_date="2024-01-05",
        geometry=_SOCAL_POLYGON,
        expected_name_prefix="S5P_OFFL_L2__CH4",
    ),
    _NetCDFPathTest(
        "point - carbon monoxide",
        variable=_new_variable(
            "OFFL-L2_CO",
            product_type=ProductType.OFFL,
            property_name="L2_CO",
            underscored_name="L2__CO____",
        ),
        start_date="2024-01-03",
        end_date="2024-01-05",
        geometry=_SOCAL_POINT,
        expected_name_prefix="S5P_OFFL_L2__CO",
    ),
    _NetCDFPathTest(
        "polygon - no results (future date)",
        variable=_new_variable(
            "OFFL-L2_O3",
            product_type=ProductType.OFFL,
            property_name="L2_O3",
            underscored_name="L2__O3____",
        ),
        start_date="2099-01-01",
        end_date="2099-01-03",
        geometry=_SOCAL_POLYGON,
        expect_results=False,
    ),
]


@pytest.fixture(scope="module", params=_NETCDF_PATH_TESTS, ids=lambda c: c.name)
def netcdf_path_case(request) -> _NetCDFPathTest:
    return request.param


@pytest.fixture(scope="module")
def netcdf_file_paths(netcdf_path_case: _NetCDFPathTest) -> list[str]:
    return _get_netcdf_file_paths(
        variable=netcdf_path_case.variable,
        start_date=netcdf_path_case.start_date,
        end_date=netcdf_path_case.end_date,
        geometry_string=netcdf_path_case.geometry,
    )


class TestGetS3FilePaths:
    """Internal CDSE/S3 path discovery: _get_netcdf_file_paths()."""

    def test_returns_valid_paths(
        self, netcdf_file_paths: list[str], netcdf_path_case: _NetCDFPathTest
    ) -> None:
        if netcdf_path_case.expect_results:
            assert len(netcdf_file_paths) > 0
        else:
            assert len(netcdf_file_paths) == 0
        for path in netcdf_file_paths:
            posix_path = PurePosixPath(path)
            assert len(posix_path.parts) > 1
            assert posix_path.suffix == ".nc"

    def test_paths_have_expected_product_prefix(
        self, netcdf_file_paths: list[str], netcdf_path_case: _NetCDFPathTest
    ) -> None:
        if not netcdf_path_case.expected_name_prefix:
            pytest.skip("no expected_name_prefix defined for this case")
        for path in netcdf_file_paths:
            filename = PurePosixPath(path).name
            assert filename.startswith(netcdf_path_case.expected_name_prefix), (
                f"{filename!r} does not start with {netcdf_path_case.expected_name_prefix!r}"
            )

    def test_paths_are_unique(self, netcdf_file_paths: list[str]) -> None:
        assert len(netcdf_file_paths) == len(set(netcdf_file_paths))

    def test_invalid_variable_returns_empty_list(self) -> None:
        results = _get_netcdf_file_paths(
            variable=_new_variable("OFFL-L2_DOES_NOT_EXIST"),
            start_date="2024-01-01",
            end_date="2024-01-02",
            geometry_string=_SOCAL_POINT,
        )
        assert len(results) == 0

    def test_invalid_start_date_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid date"):
            _get_netcdf_file_paths(
                variable=_new_variable("OFFL-L2_O3"),
                start_date="01/03/2024",
                end_date="2024-01-05",
                geometry_string=_SOCAL_POINT,
            )

    def test_invalid_end_date_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid date"):
            _get_netcdf_file_paths(
                variable=_new_variable("OFFL-L2_O3"),
                start_date="2024-01-03",
                end_date="January 5 2024",
                geometry_string=_SOCAL_POINT,
            )

    def test_malformed_geometry_raises_http_error(self) -> None:
        with pytest.raises(httpx.HTTPStatusError):
            _get_netcdf_file_paths(
                variable=_new_variable("OFFL-L2_O3"),
                start_date="2024-01-03",
                end_date="2024-01-05",
                geometry_string="not-a-valid-geometry",
            )
