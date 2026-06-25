"""Integration tests for the Sentinel 5-TROPOMI source adapter (live AWS access).

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests query the real AWS S3 bucket for TROPOMI data and require network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import httpx
import pytest

from env_data_mcp.sources.tropomi._query import _get_s3_file_paths
from env_data_mcp.sources.tropomi.constants import _PRODUCT_TYPES, DEFAULT_VARIABLES
from env_data_mcp.sources.tropomi.tools import tropomi_available_variables

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
        assert "rows_returned" in meta
        assert meta["rows_returned"] == len(var_info["data"])
        assert len(meta.get("license")) > 0 or len(meta.get("license_url")) > 0

    def test_contains_product_type(self, var_info: dict[str, Any]):
        """Test variable descriptions include the product type."""
        for key, val in var_info["data"].items():
            parts = key.split("-")
            assert len(parts) >= 2
            assert parts[0] in _PRODUCT_TYPES
            assert _PRODUCT_TYPES[parts[0]] in val["description"]


@dataclass(frozen=True)
class _S3PathTest:
    name: str
    variable_name: str
    start_date: str
    end_date: str
    geometry: str
    expect_results: bool = True
    # expected prefix in path filenames, e.g. "S5P_OFFL_L2__O3"
    expected_name_prefix: str = ""


# Southern California point / small bbox centred on ~(33.84 N, 116.49 W)
_SOCAL_POINT = "geography'SRID=4326;POINT(-116.4856 33.8434)'"
# 1° × 1° box around the same area; polygon must close (first == last vertex)
_SOCAL_POLYGON = (
    "geography'SRID=4326;POLYGON((-117.0 33.5,-116.0 33.5,-116.0 34.5,-117.0 34.5,-117.0 33.5))'"
)

_S3_PATH_TESTS: list[_S3PathTest] = [
    _S3PathTest(
        "point - ozone",
        variable_name="OFFL-L2_O3",
        start_date="2024-01-03",
        end_date="2024-01-05",
        geometry=_SOCAL_POINT,
        expected_name_prefix="S5P_OFFL_L2__O3",
    ),
    _S3PathTest(
        "polygon - methane",
        variable_name="OFFL-L2_CH4",
        start_date="2024-01-03",
        end_date="2024-01-05",
        geometry=_SOCAL_POLYGON,
        expected_name_prefix="S5P_OFFL_L2__CH4",
    ),
    _S3PathTest(
        "point - carbon monoxide",
        variable_name="OFFL-L2_CO",
        start_date="2024-01-03",
        end_date="2024-01-05",
        geometry=_SOCAL_POINT,
        expected_name_prefix="S5P_OFFL_L2__CO",
    ),
    _S3PathTest(
        "polygon - no results (future date)",
        variable_name="OFFL-L2_O3",
        start_date="2099-01-01",
        end_date="2099-01-03",
        geometry=_SOCAL_POLYGON,
        expect_results=False,
    ),
]


@pytest.fixture(scope="module", params=_S3_PATH_TESTS, ids=lambda c: c.name)
def s3_path_case(request) -> _S3PathTest:
    return request.param


@pytest.fixture(scope="module")
def s3_file_paths(s3_path_case: _S3PathTest) -> list[str]:
    return _get_s3_file_paths(
        variable_name=s3_path_case.variable_name,
        start_date=s3_path_case.start_date,
        end_date=s3_path_case.end_date,
        geometry_string=s3_path_case.geometry,
    )


class TestGetS3FilePaths:
    """Tests of the _get_s3_file_paths() query function."""

    def test_returns_valid_paths(self, s3_file_paths: list[str], s3_path_case: _S3PathTest):
        if s3_path_case.expect_results:
            assert len(s3_file_paths) > 0
        else:
            assert len(s3_file_paths) == 0
        for path in s3_file_paths:
            posix_path = PurePosixPath(path)
            assert len(posix_path.parts) > 1
            assert posix_path.suffix == ".nc"

    def test_paths_have_expected_product_prefix(
        self, s3_file_paths: list[str], s3_path_case: _S3PathTest
    ):
        """Each filename should start with the S5P product prefix for the variable."""
        if not s3_path_case.expected_name_prefix:
            pytest.skip("no expected_name_prefix defined for this case")
        for path in s3_file_paths:
            filename = PurePosixPath(path).name
            assert filename.startswith(s3_path_case.expected_name_prefix), (
                f"{filename!r} does not start with {s3_path_case.expected_name_prefix!r}"
            )

    def test_paths_are_unique(self, s3_file_paths: list[str]):
        """CDSE should not return duplicate paths."""
        assert len(s3_file_paths) == len(set(s3_file_paths))

    def test_invalid_variable_raises(self):
        """Passing an unknown variable name must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid TROPOMI variable name"):
            _get_s3_file_paths(
                variable_name="OFFL-L2_DOES_NOT_EXIST",
                start_date="2024-01-01",
                end_date="2024-01-02",
                geometry_string=_SOCAL_POINT,
            )

    def test_invalid_start_date_format_raises(self):
        """A non-ISO start date must raise ValueError before any network call."""
        with pytest.raises(ValueError, match="Invalid date"):
            _get_s3_file_paths(
                variable_name="OFFL-L2_O3",
                start_date="01/03/2024",
                end_date="2024-01-05",
                geometry_string=_SOCAL_POINT,
            )

    def test_invalid_end_date_format_raises(self):
        """A non-ISO end date must raise ValueError before any network call."""
        with pytest.raises(ValueError, match="Invalid date"):
            _get_s3_file_paths(
                variable_name="OFFL-L2_O3",
                start_date="2024-01-03",
                end_date="January 5 2024",
                geometry_string=_SOCAL_POINT,
            )

    def test_malformed_geometry_raises_http_error(self):
        """A geometry string that is not valid WKT must cause CDSE to return HTTP 400."""
        with pytest.raises(httpx.HTTPStatusError):
            _get_s3_file_paths(
                variable_name="OFFL-L2_O3",
                start_date="2024-01-03",
                end_date="2024-01-05",
                geometry_string="not-a-valid-geometry",
            )
