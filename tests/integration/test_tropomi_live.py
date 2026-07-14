"""Integration tests for the Sentinel 5-TROPOMI source adapter (live AWS access).

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests query the real AWS S3 bucket for TROPOMI data and require network access.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import httpx
import pytest

from env_data_mcp.sources.tropomi._query import _get_netcdf_file_paths, _VariableInfo
from env_data_mcp.sources.tropomi.constants import _PRODUCT_TYPES, DEFAULT_VARIABLES, ProductType
from env_data_mcp.sources.tropomi.tools import (
    tropomi_available_variables,
    tropomi_bbox_query,
    tropomi_query,
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
# Available variables tool tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def var_info() -> dict[str, Any]:
    return tropomi_available_variables()


class TestAvailableVariables:
    """tropomi_available_variables() tool tests."""

    def test_returns_dict_with_data(self, var_info: dict[str, Any]):
        """Test returns data."""
        assert isinstance(var_info, dict)
        assert "data" in var_info
        assert len(var_info["data"]) > 0
        for _, val in var_info["data"].items():
            assert "description" in val
            assert len(val["description"]) > 0
            assert "units" in val
            assert len(val["units"]) > 0

    def test_contains_known_methane_variable(self, var_info: dict[str, Any]):
        """Test results include known variable info."""
        data = var_info["data"]
        assert "OFFL-L2_CH4" in data
        ch4_info = data["OFFL-L2_CH4"]
        assert "description" in ch4_info
        assert any(word in ch4_info["description"].lower() for word in ["methane", "ch4"])
        assert "offline" in ch4_info["description"].lower()
        assert "units" in ch4_info
        assert ch4_info["units"] == "ppb"

    @pytest.mark.parametrize("var", DEFAULT_VARIABLES)
    def test_contains_default_variables(self, var_info: dict[str, Any], var: str):
        """Test results include all default variables."""
        data = var_info["data"]
        assert var in data

    def test_includes_non_default_variables(self, var_info: dict[str, Any]):
        """Test results include more than just the default variables."""
        assert len(var_info["data"]) > len(DEFAULT_VARIABLES)

    def test_contains_expected_metadata(self, var_info: dict[str, Any]):
        """Test metadata is complete and correct."""
        assert "_meta" in var_info
        meta = var_info["_meta"]
        assert "source" in meta
        assert meta["source"] == "tropomi"
        assert "success" in meta
        assert meta["success"] is True
        assert meta["geometries_returned"] == 0
        assert meta["total_records_returned"] == len(var_info["data"])
        assert len(meta.get("license")) > 0 or len(meta.get("license_url")) > 0

    def test_contains_product_type(self, var_info: dict[str, Any]):
        """Test variable descriptions include the product type."""
        for key, val in var_info["data"].items():
            parts = key.split("-")
            assert len(parts) >= 2
            assert parts[0] in _PRODUCT_TYPES
            assert _PRODUCT_TYPES[parts[0]] in val["description"]


@dataclass(frozen=True)
class _NetCDFPathTest:
    name: str
    variable: _VariableInfo
    start_date: str
    end_date: str
    geometry: str
    expect_results: bool = True
    # expected prefix in path filenames, e.g. "S5P_OFFL_L2__O3"
    expected_name_prefix: str = ""


def new_variable(
    name: str,
    *,
    description: str = "",
    units: str = "",
    product_type: ProductType = ProductType.NRTI,
    property_name: str = "",
    underscored_name: str = "",
    cogt_name: str = "",
) -> _VariableInfo:
    """Create a new _VariableInfo instance with a specified name."""
    return _VariableInfo(
        name=name,
        description=description,
        units=units,
        product_type=product_type,
        property_name=property_name,
        underscored_name=underscored_name,
        cogt_name=cogt_name,
    )


# Southern California point / small bbox centred on ~(33.84 N, 116.49 W)
_SOCAL_POINT = "geography'SRID=4326;POINT(-116.4856 33.8434)'"
# 1° × 1° box around the same area; polygon must close (first == last vertex)
_SOCAL_POLYGON = (
    "geography'SRID=4326;POLYGON((-117.0 33.5,-116.0 33.5,-116.0 34.5,-117.0 34.5,-117.0 33.5))'"
)

_NETCDF_PATH_TESTS: list[_NetCDFPathTest] = [
    _NetCDFPathTest(
        "point - ozone",
        variable=new_variable(
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
        variable=new_variable(
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
        variable=new_variable(
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
        variable=new_variable(
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
    """Tests of the _get_netcdf_file_paths() query function."""

    def test_returns_valid_paths(
        self, netcdf_file_paths: list[str], netcdf_path_case: _NetCDFPathTest
    ):
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
    ):
        """Each filename should start with the S5P product prefix for the variable."""
        if not netcdf_path_case.expected_name_prefix:
            pytest.skip("no expected_name_prefix defined for this case")
        for path in netcdf_file_paths:
            filename = PurePosixPath(path).name
            assert filename.startswith(netcdf_path_case.expected_name_prefix), (
                f"{filename!r} does not start with {netcdf_path_case.expected_name_prefix!r}"
            )

    def test_paths_are_unique(self, netcdf_file_paths: list[str]):
        """CDSE should not return duplicate paths."""
        assert len(netcdf_file_paths) == len(set(netcdf_file_paths))

    def test_invalid_variable_returns_empty_list(self):
        """Passing an unknown variable must return an empty list."""
        results = _get_netcdf_file_paths(
            variable=new_variable("OFFL-L2_DOES_NOT_EXIST"),
            start_date="2024-01-01",
            end_date="2024-01-02",
            geometry_string=_SOCAL_POINT,
        )
        assert len(results) == 0

    def test_invalid_start_date_format_raises(self):
        """A non-ISO start date must raise ValueError before any network call."""
        with pytest.raises(ValueError, match="Invalid date"):
            _get_netcdf_file_paths(
                variable=new_variable("OFFL-L2_O3"),
                start_date="01/03/2024",
                end_date="2024-01-05",
                geometry_string=_SOCAL_POINT,
            )

    def test_invalid_end_date_format_raises(self):
        """A non-ISO end date must raise ValueError before any network call."""
        with pytest.raises(ValueError, match="Invalid date"):
            _get_netcdf_file_paths(
                variable=new_variable("OFFL-L2_O3"),
                start_date="2024-01-03",
                end_date="January 5 2024",
                geometry_string=_SOCAL_POINT,
            )

    def test_malformed_geometry_raises_http_error(self):
        """A geometry string that is not valid WKT must cause CDSE to return HTTP 400."""
        with pytest.raises(httpx.HTTPStatusError):
            _get_netcdf_file_paths(
                variable=new_variable("OFFL-L2_O3"),
                start_date="2024-01-03",
                end_date="2024-01-05",
                geometry_string="not-a-valid-geometry",
            )


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
    start_date: str = "2024-01-03"
    end_date: str = "2024-01-05"
    max_runtime_s: float = 90.0
    expect_slow_warn: bool = False


_RELIABLE_VARS = ["OFFL-L2_NO2", "OFFL-L2_CO", "OFFL-L2_SO2", "OFFL-L2_HCHO"]
_UNRELIABLE_VARS = ["OFFL-L2_CH4", "OFFL-L2_O3_TCL"]  # low QA / limited COGT coverage

_POINT_CASES: list[_PointCase] = [
    _PointCase("default", None, _RELIABLE_VARS, _UNRELIABLE_VARS),
    _PointCase(
        "Nairobi, Kenya",
        None,
        _RELIABLE_VARS,
        _UNRELIABLE_VARS,
        lat_lon=(-1.27, 36.65),
    ),
    _PointCase(
        "slow query warning",
        None,
        [],
        [],
        max_runtime_s=0,  # any estimate triggers the warning
        expect_slow_warn=True,
    ),
    _PointCase("single variable", ["OFFL-L2_NO2"], ["OFFL-L2_NO2"], []),
    _PointCase(
        "some unavailable",
        ["foo", "OFFL-L2_NO2"],
        ["OFFL-L2_NO2"],
        ["foo"],
    ),
    _PointCase("all unavailable", ["bar", "baz", "qux"], [], ["bar", "baz", "qux"]),
    _PointCase(
        "no results (future date)",
        None,
        [],
        DEFAULT_VARIABLES,
        start_date="2099-01-01",
        end_date="2099-01-03",
    ),
]


@pytest.fixture(scope="module", params=_POINT_CASES, ids=lambda c: c.name)
def point_case(request) -> _PointCase:
    return request.param


@pytest.fixture(scope="module")
def point_result(point_case: _PointCase) -> dict[str, Any]:
    lat, lon = point_case.lat_lon
    kwargs: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "start_date": point_case.start_date,
        "end_date": point_case.end_date,
        "max_runtime_s": point_case.max_runtime_s,
    }
    if point_case.requested_vars is not None:
        kwargs["variables"] = point_case.requested_vars
    return tropomi_query(**kwargs)


@pytest.fixture(scope="module")
def requested_vars_effective(point_case: _PointCase) -> list[str]:
    return list(
        DEFAULT_VARIABLES if point_case.requested_vars is None else point_case.requested_vars
    )


class TestTropomiQuery:
    """Tests of the tropomi_query() tool."""

    def test_metadata_success(self, point_case: _PointCase, point_result: dict[str, Any]):
        """Tests metadata indicates success."""
        assert "_meta" in point_result
        meta = point_result["_meta"]
        if point_case.expect_slow_warn:
            assert "exceeds" in meta["message"] and "threshold" in meta["message"]
            assert "exceeds" in meta["error"] and "threshold" in meta["error"]
        else:
            assert meta["error"] is None
        assert meta["success"] == (not point_case.expect_slow_warn)
        assert meta["source"] == "tropomi"

    def test_metadata_stats(self, point_case: _PointCase, point_result: dict[str, Any]):
        """Tests counts and timers in metadata."""
        meta = point_result["_meta"]
        if len(point_case.expected_vars) > 0:
            assert meta["latency_s"] > 0.25
            assert meta["geometries_returned"] > 0
            assert meta["total_records_returned"] > 0
        else:
            assert meta["geometries_returned"] == 0
            assert meta["total_records_returned"] == 0

    def test_metadata_variables_echoed(
        self,
        point_case: _PointCase,
        requested_vars_effective: list[str],
        point_result: dict[str, Any],
    ):
        """Tests that the variables list in metadata mirrors what was requested."""
        if point_case.expect_slow_warn:
            return  # slow-query warning response returns variables=[]
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
        """Tests that variable info in metadata is present for each expected variable."""
        if point_case.expect_slow_warn or len(point_case.expected_vars) == 0:
            return
        got = point_result["_meta"]["variable_info"]
        # variable_info covers all *requested* vars; expected_vars is a subset of those
        for var in point_case.expected_vars:
            assert var in got
            assert "description" in got[var]
            assert "units" in got[var]

    def test_geojson_geometry_in_expected_range(
        self, point_case: _PointCase, point_result: dict[str, Any]
    ):
        """Tests that returned coordinates are valid WGS84 lat/lon values."""
        for point in point_result["data"]:
            assert point["longitude"] == point["geometry"]["coordinates"][0]
            assert point["latitude"] == point["geometry"]["coordinates"][1]
            assert -90.0 <= point["latitude"] <= 90.0
            assert -180.0 <= point["longitude"] <= 180.0

    def test_data_records_have_date_key(self, point_case: _PointCase, point_result: dict[str, Any]):
        """Each record within a geo point must include an ISO 8601 date key."""
        for point in point_result["data"]:
            assert len(point["records"]) >= 1
            for record in point["records"]:
                assert "date" in record
                # YYYY-MM-DD
                assert len(record["date"]) == 10

    def test_data_includes_expected_variables(
        self, point_case: _PointCase, point_result: dict[str, Any]
    ):
        """Each expected variable appears in at least one record across all geo points."""
        for var in point_case.expected_vars:
            found = any(
                var in record for point in point_result["data"] for record in point["records"]
            )
            assert found, f"{var!r} not found in any record"

    def test_data_has_expected_property_values(
        self, point_case: _PointCase, point_result: dict[str, Any]
    ):
        """NO2 values over Yakima Valley fall within a plausible atmospheric range."""
        if point_case.lat_lon == (_LAT, _LON) and "OFFL-L2_NO2" in point_case.expected_vars:
            no2_values = [
                record["OFFL-L2_NO2"]
                for point in point_result["data"]
                for record in point["records"]
                if "OFFL-L2_NO2" in record
            ]
            assert len(no2_values) > 0
            for val in no2_values:
                # Tropospheric NO2 column is typically 0–0.001 mol/m² over rural areas
                assert 0 <= val <= 0.01, (
                    f"NO2 value {val:.2e} mol/m\u00b2 outside plausible range (0-0.01)"
                )


# ---------------------------------------------------------------------------
# BBox query tool tests
# ---------------------------------------------------------------------------

# 1 deg x 1 deg box centred over Yakima Valley, WA (same area as point tests)
_MIN_LAT = 45.75
_MAX_LAT = 46.75
_MIN_LON = -119.98
_MAX_LON = -118.98


@dataclass(frozen=True)
class _BboxCase:
    name: str
    requested_vars: Sequence[str] | None
    expected_vars: Sequence[str]
    unavailable_vars: Sequence[str]
    bbox: tuple[float, float, float, float] = (_MIN_LAT, _MAX_LAT, _MIN_LON, _MAX_LON)
    start_date: str = "2024-01-03"
    end_date: str = "2024-01-05"
    max_runtime_s: float = 120.0
    expect_slow_warn: bool = False


_BBOX_CASES: list[_BboxCase] = [
    _BboxCase("default", None, _RELIABLE_VARS, _UNRELIABLE_VARS),
    _BboxCase("single variable", ["OFFL-L2_NO2"], ["OFFL-L2_NO2"], []),
    _BboxCase(
        "some unavailable",
        ["foo", "OFFL-L2_NO2"],
        ["OFFL-L2_NO2"],
        ["foo"],
    ),
    _BboxCase("all unavailable", ["bar", "baz", "qux"], [], ["bar", "baz", "qux"]),
    _BboxCase(
        "no results (future date)",
        None,
        [],
        DEFAULT_VARIABLES,
        start_date="2099-01-01",
        end_date="2099-01-03",
    ),
    _BboxCase(
        "slow query warning",
        None,
        [],
        [],
        max_runtime_s=0,  # any estimate triggers the warning
        expect_slow_warn=True,
    ),
]


@pytest.fixture(scope="module", params=_BBOX_CASES, ids=lambda c: c.name)
def bbox_case(request) -> _BboxCase:
    return request.param


@pytest.fixture(scope="module")
def bbox_result(bbox_case: _BboxCase) -> dict[str, Any]:
    min_lat, max_lat, min_lon, max_lon = bbox_case.bbox
    kwargs: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": bbox_case.start_date,
        "end_date": bbox_case.end_date,
        "max_runtime_s": bbox_case.max_runtime_s,
    }
    if bbox_case.requested_vars is not None:
        kwargs["variables"] = bbox_case.requested_vars
    return tropomi_bbox_query(**kwargs)


@pytest.fixture(scope="module")
def bbox_requested_vars_effective(bbox_case: _BboxCase) -> list[str]:
    return list(DEFAULT_VARIABLES if bbox_case.requested_vars is None else bbox_case.requested_vars)


class TestTropomiBboxQuery:
    """Tests of the tropomi_bbox_query() tool."""

    def test_metadata_success(self, bbox_case: _BboxCase, bbox_result: dict[str, Any]):
        """Tests metadata indicates success."""
        assert "_meta" in bbox_result
        meta = bbox_result["_meta"]
        if bbox_case.expect_slow_warn:
            assert "exceeds" in meta["message"] and "threshold" in meta["message"]
            assert "exceeds" in meta["error"] and "threshold" in meta["error"]
        else:
            assert meta["error"] is None
        assert meta["success"] == (not bbox_case.expect_slow_warn)
        assert meta["source"] == "tropomi"

    def test_metadata_stats(self, bbox_case: _BboxCase, bbox_result: dict[str, Any]):
        """Tests counts and timers in metadata."""
        meta = bbox_result["_meta"]
        if len(bbox_case.expected_vars) > 0:
            assert meta["latency_s"] > 0.25
            assert meta["geometries_returned"] > 0
            assert meta["total_records_returned"] > 0
        else:
            assert meta["geometries_returned"] == 0
            assert meta["total_records_returned"] == 0

    def test_metadata_variables_echoed(
        self,
        bbox_case: _BboxCase,
        bbox_requested_vars_effective: list[str],
        bbox_result: dict[str, Any],
    ):
        """Tests that the variables list in metadata mirrors what was requested."""
        if bbox_case.expect_slow_warn:
            return  # slow-query warning response returns variables=[]
        got = bbox_result["_meta"]["variables"]
        assert len(got) == len(bbox_requested_vars_effective)
        for var in bbox_requested_vars_effective:
            assert var in got

    def test_metadata_unavailable_variables(
        self, bbox_case: _BboxCase, bbox_result: dict[str, Any]
    ):
        """Tests that the expected unavailable variables are returned."""
        got = bbox_result["_meta"]["unavailable_variables"]
        assert len(got) == len(bbox_case.unavailable_vars)
        for var in bbox_case.unavailable_vars:
            assert var in got

    def test_metadata_variable_info(self, bbox_case: _BboxCase, bbox_result: dict[str, Any]):
        """Tests that variable info in metadata is present for each expected variable."""
        if bbox_case.expect_slow_warn or len(bbox_case.expected_vars) == 0:
            return
        got = bbox_result["_meta"]["variable_info"]
        for var in bbox_case.expected_vars:
            assert var in got
            assert "description" in got[var]
            assert "units" in got[var]

    def test_geojson_geometry_in_expected_range(
        self, bbox_case: _BboxCase, bbox_result: dict[str, Any]
    ):
        """Tests that returned coordinates are valid WGS84 lat/lon values."""
        for point in bbox_result["data"]:
            assert point["longitude"] == point["geometry"]["coordinates"][0]
            assert point["latitude"] == point["geometry"]["coordinates"][1]
            assert -90.0 <= point["latitude"] <= 90.0
            assert -180.0 <= point["longitude"] <= 180.0

    def test_data_points_within_bbox(self, bbox_case: _BboxCase, bbox_result: dict[str, Any]):
        """All returned grid-cell coordinates must lie near the queried bounding box.

        A half-pixel tolerance (~0.05 deg) is allowed because rasterio's from_bounds
        window includes full pixels that intersect the bbox, so pixel centers at the
        edge can sit slightly outside the requested extent.
        """
        _TOL = 0.05  # degrees; TROPOMI pixels are ~0.035 deg wide
        min_lat, max_lat, min_lon, max_lon = bbox_case.bbox
        for point in bbox_result["data"]:
            assert min_lat - _TOL <= point["latitude"] <= max_lat + _TOL, (
                f"latitude {point['latitude']} outside [{min_lat}, {max_lat}] (tol={_TOL})"
            )
            assert min_lon - _TOL <= point["longitude"] <= max_lon + _TOL, (
                f"longitude {point['longitude']} outside [{min_lon}, {max_lon}] (tol={_TOL})"
            )

    def test_data_has_multiple_points(self, bbox_case: _BboxCase, bbox_result: dict[str, Any]):
        """A bbox query over a 1 deg x 1 deg area must return more than one distinct grid cell."""
        if len(bbox_case.expected_vars) == 0:
            pytest.skip("no data expected for this case")
        assert len(bbox_result["data"]) > 1, (
            "expected multiple grid-cell points for a 1 deg x 1 deg bounding box"
        )

    def test_data_records_have_date_key(self, bbox_case: _BboxCase, bbox_result: dict[str, Any]):
        """Each record within a geo point must include an ISO 8601 date key."""
        for point in bbox_result["data"]:
            assert len(point["records"]) >= 1
            for record in point["records"]:
                assert "date" in record
                # YYYY-MM-DD
                assert len(record["date"]) == 10

    def test_data_includes_expected_variables(
        self, bbox_case: _BboxCase, bbox_result: dict[str, Any]
    ):
        """Each expected variable appears in at least one record across all geo points."""
        for var in bbox_case.expected_vars:
            found = any(
                var in record for point in bbox_result["data"] for record in point["records"]
            )
            assert found, f"{var!r} not found in any record"

    def test_data_has_expected_property_values(
        self, bbox_case: _BboxCase, bbox_result: dict[str, Any]
    ):
        """NO2 values over Yakima Valley fall within a plausible atmospheric range."""
        is_yakima_box = bbox_case.bbox == (_MIN_LAT, _MAX_LAT, _MIN_LON, _MAX_LON)
        if is_yakima_box and "OFFL-L2_NO2" in bbox_case.expected_vars:
            no2_values = [
                record["OFFL-L2_NO2"]
                for point in bbox_result["data"]
                for record in point["records"]
                if "OFFL-L2_NO2" in record
            ]
            assert len(no2_values) > 0
            for val in no2_values:
                # Tropospheric NO2 column is typically 0–0.001 mol/m2 over rural areas.
                # Small negative values (~-0.001) are valid satellite retrievals over
                # very clean air (measurement noise around the detection limit).
                assert -0.001 <= val <= 0.01, (
                    f"NO2 value {val:.2e} mol/m\u00b2 outside plausible range (-0.001–0.01)"
                )
