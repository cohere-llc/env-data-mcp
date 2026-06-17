"""Unit tests for env_data_mcp.sources.soilgrids.tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from env_data_mcp.sources.soilgrids.tools import (
    soilgrids_available_variables,
    soilgrids_bbox_query,
    soilgrids_query,
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
        "rows_returned": len(_MOCK_VAR_INFO_RAW),
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


# ---------------------------------------------------------------------------
# soilgrids_query
# ---------------------------------------------------------------------------


def test_soilgrids_query() -> None:
    """Tests soilgrids_query returns expected results without live services."""
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
        results = soilgrids_query(
            latitude=33.8105,
            longitude=-116.6850,
            radius_km=1.0,
            variables=variables,
        )

    assert "data" in results
    assert len(results["data"]) > 0
    assert "_meta" in results
    assert "unavailable_variables" in results["_meta"]
    assert results["_meta"]["unavailable_variables"] == ["oops"]


# ---------------------------------------------------------------------------
# soilgrids_bbox_query
# ---------------------------------------------------------------------------


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
            min_lat=33.8105,
            max_lat=33.8136,
            min_lon=-116.6900,
            max_lon=-116.6850,
            variables=variables,
        )

    assert "data" in results
    assert len(results["data"]) > 0
    assert "_meta" in results
    assert "unavailable_variables" in results["_meta"]
    assert results["_meta"]["unavailable_variables"] == ["oops"]
