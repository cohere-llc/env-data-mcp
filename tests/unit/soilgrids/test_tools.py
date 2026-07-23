"""Unit tests for env_data_mcp.sources.soilgrids.tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from env_data_mcp.helpers import check_runtime
from env_data_mcp.sources.soilgrids._query import VariableInfo
from env_data_mcp.sources.soilgrids.tools import (
    soilgrids_available_variables,
    soilgrids_bbox_query,
    soilgrids_point_query,
)

_MOCK_VAR_INFO_RAW = {
    "soc_0-5cm_mean": {
        "description": "Soil organic carbon; depth: 0-5cm; quantile: mean",
        "units": "g/kg",
    },
    "nitrogen_15-30cm_Q0.95": {
        "description": "Nitrogen; depth: 15-30cm; quantile: 95% quantile",
        "units": "g/kg",
    },
    "bdod_0-5cm_Q0.5": {
        "description": "Bulk density; depth: 0-5cm; quantile: median",
        "units": "kg/dm3",
    },
}


def _make_mock_var_info() -> dict:
    """Return a dict of coverage -> VariableInfo-like MagicMock objects."""
    result = {}
    for key, raw in _MOCK_VAR_INFO_RAW.items():
        vi = MagicMock()
        vi.description = raw["description"]
        vi.units = raw["units"]
        result[key] = vi
    return result


_MOCK_AVAILABLE_RESPONSE = {
    "data": _MOCK_VAR_INFO_RAW,
    "_meta": {
        "source": "soilgrids",
        "geometries_returned": 0,
        "total_records_returned": len(_MOCK_VAR_INFO_RAW),
        "latency_s": 0.0,
    },
}

_MOCK_QUERY_DATA = [
    {
        "geometry": {"type": "Point", "coordinates": [-116.688, 33.811]},
        "records": [
            {
                "soc_0-5cm_mean": 5.2,
                "nitrogen_15-30cm_Q0.95": 0.8,
                "bdod_0-5cm_Q0.5": 1.3,
            }
        ],
    }
]


# ---------------------------------------------------------------------------
# soilgrids_available_variables
# ---------------------------------------------------------------------------


def test_soilgrids_available_variables() -> None:
    """Tests soilgrids_available_variables returns expected results without live services."""
    mock_var_info = _make_mock_var_info()

    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.get_base_variable_list",
            return_value={"soc": None, "nitrogen": None, "bdod": None},
        ),
        patch(
            "env_data_mcp.sources.soilgrids.tools.get_variable_info",
            side_effect=lambda base: {k: v for k, v in mock_var_info.items() if k.startswith(base)},
        ),
    ):
        results = soilgrids_available_variables()

    assert "data" in results
    assert len(results["data"]) > 0
    assert "_meta" in results


def test_soil_grids_available_variables_handles_single_failure() -> None:
    """Tests a single raised exception from get_variable_info is silently handled."""

    def mock_get_variable_info(base: str) -> dict[str, VariableInfo]:
        if base == "foo":
            msg = "Some error"
            raise ValueError(msg)
        mock_info = MagicMock()
        mock_info.description = "the bar var"
        mock_info.units = "bars"
        return {"bar_var": mock_info}

    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.get_base_variable_list",
            return_value=["foo", "bar"],
        ),
        patch(
            "env_data_mcp.sources.soilgrids.tools.get_variable_info",
            side_effect=mock_get_variable_info,
        ),
    ):
        results = soilgrids_available_variables()
    assert "data" in results
    assert len(results["data"])
    assert "bar_var" in results["data"]


def test_soil_grids_available_variables_handles_empty_base_list() -> None:
    """Tests than an empty base list is sliently handled."""
    with (
        patch("env_data_mcp.sources.soilgrids.tools.get_base_variable_list", return_value=[]),
        patch("env_data_mcp.sources.soilgrids.tools.get_variable_info") as mock_get_info,
    ):
        results = soilgrids_available_variables()
    assert "data" in results
    assert len(results["data"]) == 0
    mock_get_info.assert_not_called()


# ---------------------------------------------------------------------------
# soilgrids_point_query
# ---------------------------------------------------------------------------

# test coordinates
_LAT: float = 33.8105
_LON: float = -116.6850


def test_soilgrids_point_query() -> None:
    """Tests soilgrids_point_query returns expected results without live services."""
    variables = ["soc_0-5cm_mean", "nitrogen_15-30cm_Q0.95", "oops", "bdod_0-5cm_Q0.5"]
    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.soilgrids_available_variables",
            return_value=_MOCK_AVAILABLE_RESPONSE,
        ),
        patch(
            "env_data_mcp.sources.soilgrids.tools.query_bbox",
            return_value=(_MOCK_QUERY_DATA, ["oops"]),
        ),
    ):
        results = soilgrids_point_query(
            latitude=_LAT,
            longitude=_LON,
            radius_km=1.0,
            variables=variables,
        )

    assert "data" in results
    assert len(results["data"]) > 0
    assert "_meta" in results
    assert results["_meta"]["variables"] == variables
    assert results["_meta"]["unavailable_variables"] == ["oops"]
    assert "oops" not in results["_meta"]["variable_info"]
    for var in [v for v in variables if v != "oops"]:
        assert var in results["_meta"]["variable_info"]


def test_soilgrids_point_query_handles_query_exception() -> None:
    """Tests that exceptions raised by query_bbox() are handled."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.soilgrids_available_variables",
            return_value=_MOCK_AVAILABLE_RESPONSE,
        ),
        patch("env_data_mcp.sources.soilgrids.tools.check_runtime", return_value=None),
        patch("env_data_mcp.sources.soilgrids.tools.query_bbox", side_effect=RuntimeError("boom")),
    ):
        results = soilgrids_point_query(
            latitude=_LAT,
            longitude=_LON,
            radius_km=1.0,
        )
    assert "data" in results
    assert len(results["data"]) == 0
    assert "_meta" in results
    assert not results["_meta"]["success"]
    assert results["_meta"]["error"] == "boom"


_SLOW_WARN = check_runtime("_test", n_days=1, area_deg2=1.0e9, max_runtime_s=0.001)
assert _SLOW_WARN is not None


def test_soilgrids_point_query_handles_slow_query() -> None:
    """Tests that a slow-query returns expected results and doesn't call query_bbox()."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.soilgrids_available_variables",
            return_value=_MOCK_AVAILABLE_RESPONSE,
        ),
        patch("env_data_mcp.sources.soilgrids.tools.check_runtime", return_value=_SLOW_WARN),
        patch("env_data_mcp.sources.soilgrids.tools.query_bbox") as mock_qbbox,
    ):
        results = soilgrids_point_query(latitude=_LAT, longitude=_LON, radius_km=1.0)
    mock_qbbox.assert_not_called()
    assert results["_meta"]["success"] is False
    assert results["_meta"]["slow_query_warning"] is True
    assert results["data"] == []


def test_soilgrids_point_query_handles_invalid_coordinate() -> None:
    """Tests that an invalid coordinate is handled."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.soilgrids_available_variables",
            return_value=_MOCK_AVAILABLE_RESPONSE,
        ),
        patch("env_data_mcp.sources.soilgrids.tools.check_runtime", return_value=None),
        patch("env_data_mcp.sources.soilgrids.tools.query_bbox") as mock_qbbox,
    ):
        results = soilgrids_point_query(latitude=_LAT, longitude=999, radius_km=1.0)
    mock_qbbox.assert_not_called()
    assert results["_meta"]["success"] is False
    assert results["data"] == []


# ---------------------------------------------------------------------------
# soilgrids_bbox_query
# ---------------------------------------------------------------------------

_BBOX = {
    "min_lat": 33.8105,
    "max_lat": 33.8136,
    "min_lon": -116.6900,
    "max_lon": -116.6850,
}


def test_soilgrids_bbox_query() -> None:
    """Tests soilgrids_bbox_query returns expected results without live services."""
    variables = ["soc_0-5cm_mean", "nitrogen_15-30cm_Q0.95", "oops", "bdod_0-5cm_Q0.5"]
    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.soilgrids_available_variables",
            return_value=_MOCK_AVAILABLE_RESPONSE,
        ),
        patch(
            "env_data_mcp.sources.soilgrids.tools.query_bbox",
            return_value=(_MOCK_QUERY_DATA, ["oops"]),
        ),
    ):
        results = soilgrids_bbox_query(
            **_BBOX,
            variables=variables,
        )

    assert "data" in results
    assert len(results["data"]) > 0
    assert "_meta" in results
    assert results["_meta"]["variables"] == variables
    assert results["_meta"]["unavailable_variables"] == ["oops"]
    assert "oops" not in results["_meta"]["variable_info"]
    for var in [v for v in variables if v != "oops"]:
        assert var in results["_meta"]["variable_info"]


def test_soilgrids_bbox_query_handles_query_exception() -> None:
    """Tests that exceptions raised by query_bbox() are handled."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.soilgrids_available_variables",
            return_value=_MOCK_AVAILABLE_RESPONSE,
        ),
        patch("env_data_mcp.sources.soilgrids.tools.check_runtime", return_value=None),
        patch("env_data_mcp.sources.soilgrids.tools.query_bbox", side_effect=RuntimeError("boom")),
    ):
        results = soilgrids_bbox_query(
            **_BBOX,
        )
    assert "data" in results
    assert len(results["data"]) == 0
    assert "_meta" in results
    assert not results["_meta"]["success"]
    assert results["_meta"]["error"] == "boom"


_SLOW_WARN = check_runtime("_test", n_days=1, area_deg2=1.0e9, max_runtime_s=0.001)
assert _SLOW_WARN is not None


def test_soilgrids_bbox_query_handles_slow_query() -> None:
    """Tests that a slow-query returns expected results and doesn't call query_bbox()."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.soilgrids_available_variables",
            return_value=_MOCK_AVAILABLE_RESPONSE,
        ),
        patch("env_data_mcp.sources.soilgrids.tools.check_runtime", return_value=_SLOW_WARN),
        patch("env_data_mcp.sources.soilgrids.tools.query_bbox") as mock_qbbox,
    ):
        results = soilgrids_bbox_query(**_BBOX)
    mock_qbbox.assert_not_called()
    assert results["_meta"]["success"] is False
    assert results["_meta"]["slow_query_warning"] is True
    assert results["data"] == []


def test_soilgrids_bbox_query_handles_invalid_coordinate() -> None:
    """Tests that an invalid coordinate is handled."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids.tools.soilgrids_available_variables",
            return_value=_MOCK_AVAILABLE_RESPONSE,
        ),
        patch("env_data_mcp.sources.soilgrids.tools.check_runtime", return_value=None),
        patch("env_data_mcp.sources.soilgrids.tools.query_bbox") as mock_qbbox,
    ):
        results = soilgrids_bbox_query(**{**_BBOX, "min_lat": 82.0})
    mock_qbbox.assert_not_called()
    assert results["_meta"]["success"] is False
    assert results["data"] == []
