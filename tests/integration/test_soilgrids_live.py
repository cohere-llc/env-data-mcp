"""Integration tests for SoilGrids — requires live ISRIC WebCoverageService access.

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests call the real SoilGrids web services and require network access.
"""

from __future__ import annotations

from http import HTTPStatus

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
    """Skip tests if the GBIF API is unreachable."""
    try:
        r = httpx.get(_LAYERS_INFO_URL, timeout=10)
        if r.status_code != HTTPStatus.OK:
            pytest.skip(f"SoilGrids layer description URL returned HTTP {r.status_code}")
        r = httpx.get(_WEB_MAP_SERVICE_URL, timeout=10)
        if r.status_code != HTTPStatus.OK:
            pytest.skip(f"SoilGrids map service URL returned HTTP {r.status_code}")
    except Exception as e:
        pytest.skip(f"SoilGrids URLs not reachable: {e}")


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


def test_returns_expected():
    """soil_data_available_variables tool returns expected results."""
    var_info = soilgrids_available_variables()

    # returns non-empty dict
    assert isinstance(var_info, dict)
    assert len(var_info) > 0
    assert "data" in var_info

    # expected variables present
    assert "nitrogen_15-30cm_mean" in var_info["data"]
    nitro_info = var_info["data"]["nitrogen_15-30cm_mean"]
    assert "description" in nitro_info
    assert "Nitrogen" in nitro_info["description"]
    assert "units" in nitro_info
    assert len(nitro_info["units"]) > 0

    # all default variables present
    for var in DEFAULT_VARIABLES:
        assert var in var_info["data"]
        assert "description" in var_info["data"][var]
        assert len(var_info["data"][var]["description"])
        assert "units" in var_info["data"][var]


# Test coordinates - Yakima Valley, WA
_LAT = 46.2531882
_LON = -119.4768203


@pytest.mark.parametrize(
    "requested_vars,expected_vars,unavailable_vars",
    [
        pytest.param(None, DEFAULT_VARIABLES, [], id="default"),
        pytest.param(
            ["soc_0-5cm_Q0.95", "silt_0-5cm_uncertainty"],
            ["soc_0-5cm_Q0.95", "silt_0-5cm_uncertainty"],
            [],
            id="some non-standard",
        ),
        pytest.param(
            ["foo", "soc_15-30cm_Q0.5"], ["soc_15-30cm_Q0.5"], ["foo"], id="some unavailable"
        ),
        pytest.param(["bar", "baz", "qux"], [], ["bar", "baz", "qux"], id="all unavailable"),
    ],
)
def test_soilgrids_query_returns_values_for_default_variables(
    requested_vars: list[str] | None, expected_vars: list[str], unavailable_vars: list[str]
):
    """soilgrids_query returns results for Yakima Valley, WA."""
    if requested_vars is None:
        result = soilgrids_query(
            latitude=_LAT,
            longitude=_LON,
            radius_km=1.0,
        )
    else:
        result = soilgrids_query(
            latitude=_LAT,
            longitude=_LON,
            radius_km=1.0,
            variables=requested_vars,
        )
    # check metadata
    assert result["_meta"]["success"]
    assert result["_meta"]["error"] is None
    if len(expected_vars) > 0:
        assert result["_meta"]["latency_s"] > 1.0  # should take at least a second
    assert result["_meta"]["source"] == "soilgrids"
    if len(expected_vars) > 0:
        assert result["_meta"]["rows_returned"] > 0
    else:
        assert result["_meta"]["rows_returned"] == 0
    assert len(result["_meta"]["unavailable_variables"]) == len(unavailable_vars)
    for var in unavailable_vars:
        assert var in result["_meta"]["unavailable_variables"]
    if requested_vars is None:
        requested_vars = DEFAULT_VARIABLES
    assert len(result["_meta"]["variables"]) == len(requested_vars)
    for var in requested_vars:
        assert var in result["_meta"]["variables"]
    assert len(result["_meta"]["variable_info"]) == len(expected_vars)
    for var in expected_vars:
        assert var in result["_meta"]["variable_info"]
        assert "description" in result["_meta"]["variable_info"][var]
        assert "units" in result["_meta"]["variable_info"][var]

    # check returned data
    assert len(result["data"]) == result["_meta"]["rows_returned"]
    points_in_box = False
    for point in result["data"]:
        if point["in_bbox"]:
            points_in_box = True
        assert len(point["records"][0].items()) == len(expected_vars)
        for var in expected_vars:
            assert var in point["records"][0]
    assert points_in_box or len(expected_vars) == 0


# Test coordinates - Yakima Valley, WA
_MIN_LAT = 46.244
_MAX_LAT = 46.262
_MIN_LON = -119.490
_MAX_LON = -119.463


@pytest.mark.parametrize(
    "requested_vars,expected_vars,unavailable_vars",
    [
        pytest.param(None, DEFAULT_VARIABLES, [], id="default"),
        pytest.param(
            ["soc_0-5cm_Q0.95", "silt_0-5cm_uncertainty"],
            ["soc_0-5cm_Q0.95", "silt_0-5cm_uncertainty"],
            [],
            id="some non-standard",
        ),
        pytest.param(
            ["foo", "soc_15-30cm_Q0.5"], ["soc_15-30cm_Q0.5"], ["foo"], id="some unavailable"
        ),
        pytest.param(["bar", "baz", "qux"], [], ["bar", "baz", "qux"], id="all unavailable"),
    ],
)
def test_soilgrids_bbox_query_returns_values_for_default_variables(
    requested_vars: list[str] | None, expected_vars: list[str], unavailable_vars: list[str]
):
    """soilgrids_query returns results for Yakima Valley, WA."""
    if requested_vars is None:
        result = soilgrids_bbox_query(
            min_lat=_MIN_LAT,
            max_lat=_MAX_LAT,
            min_lon=_MIN_LON,
            max_lon=_MAX_LON,
        )
    else:
        result = soilgrids_bbox_query(
            min_lat=_MIN_LAT,
            max_lat=_MAX_LAT,
            min_lon=_MIN_LON,
            max_lon=_MAX_LON,
            variables=requested_vars,
        )
    # check metadata
    assert result["_meta"]["success"]
    assert result["_meta"]["error"] is None
    if len(expected_vars) > 0:
        assert result["_meta"]["latency_s"] > 1.0  # should take at least a second
    assert result["_meta"]["source"] == "soilgrids"
    if len(expected_vars) > 0:
        assert result["_meta"]["rows_returned"] > 0
    else:
        assert result["_meta"]["rows_returned"] == 0
    assert len(result["_meta"]["unavailable_variables"]) == len(unavailable_vars)
    for var in unavailable_vars:
        assert var in result["_meta"]["unavailable_variables"]
    if requested_vars is None:
        requested_vars = DEFAULT_VARIABLES
    assert len(result["_meta"]["variables"]) == len(requested_vars)
    for var in requested_vars:
        assert var in result["_meta"]["variables"]
    assert len(result["_meta"]["variable_info"]) == len(expected_vars)
    for var in expected_vars:
        assert var in result["_meta"]["variable_info"]
        assert "description" in result["_meta"]["variable_info"][var]
        assert "units" in result["_meta"]["variable_info"][var]

    # check returned data
    assert len(result["data"]) == result["_meta"]["rows_returned"]
    points_in_box = False
    for point in result["data"]:
        if point["in_bbox"]:
            assert _MIN_LAT <= point["latitude"] <= _MAX_LAT
            assert _MIN_LON <= point["longitude"] <= _MAX_LON
            points_in_box = True
        else:
            assert (
                point["latitude"] < _MIN_LAT
                or point["latitude"] > _MAX_LAT
                or point["longitude"] < _MIN_LON
                or point["longitude"] > _MAX_LON
            )
        assert len(point["records"][0].items()) == len(expected_vars)
        for var in expected_vars:
            assert var in point["records"][0]
    assert points_in_box or len(expected_vars) == 0
