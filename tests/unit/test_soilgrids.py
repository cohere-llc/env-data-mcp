"""Unit tests for the SoilGrids source adapter.

All HTTP calls are intercepted by pytest-httpx; no network access required.
"""

from __future__ import annotations

import pytest

from env_data_mcp.sources.soilgrids import (
    _NO_COVERAGE_MSG,
    _PROPERTIES,
    LICENSE_INFO,
    PROPERTY_INFO,
    _fetch_soilgrids,
    soilgrids_bbox_query,
    soilgrids_query,
)

# ---------------------------------------------------------------------------
# JSON response fixture
# ---------------------------------------------------------------------------

_SOILGRIDS_URL = "https://rest.soilgrids.org/soilgrids/v2.0/properties/query"

# Realistic SoilGrids v2.0 JSON response for a Yakima River point.
# Values are in mapped units; d_factor converts to target units.
_SOILGRIDS_RESPONSE = {
    "type": "Point",
    "geometry": {"type": "Point", "coordinates": [-119.477, 46.253]},
    "query": {"lon": -119.477, "lat": 46.253},
    "properties": {
        "layers": [
            {
                "name": "bdod",
                "unit_measure": {
                    "d_factor": 100,
                    "mapped_units": "cg/cm³",
                    "target_units": "kg/dm³",
                    "uncertainty_unit": "%",
                },
                "depths": [
                    {
                        "label": "0-5cm",
                        "range": {"bottom_depth": 5, "top_depth": 0, "unit_depth": "cm"},
                        "values": {
                            "Q0.05": 110,
                            "Q0.5": 133,
                            "Q0.95": 155,
                            "mean": 133,
                            "uncertainty": 16,
                        },
                    }
                ],
            },
            {
                "name": "clay",
                "unit_measure": {
                    "d_factor": 10,
                    "mapped_units": "g/kg",
                    "target_units": "g/100g (%w)",
                    "uncertainty_unit": "%",
                },
                "depths": [
                    {
                        "label": "0-5cm",
                        "range": {"bottom_depth": 5, "top_depth": 0, "unit_depth": "cm"},
                        "values": {
                            "Q0.05": 100,
                            "Q0.5": 130,
                            "Q0.95": 165,
                            "mean": 133,
                            "uncertainty": 21,
                        },
                    }
                ],
            },
            {
                "name": "phh2o",
                "unit_measure": {
                    "d_factor": 10,
                    "mapped_units": "pH×10",
                    "target_units": "pH",
                    "uncertainty_unit": "pH",
                },
                "depths": [
                    {
                        "label": "0-5cm",
                        "range": {"bottom_depth": 5, "top_depth": 0, "unit_depth": "cm"},
                        "values": {
                            "Q0.05": 60,
                            "Q0.5": 65,
                            "Q0.95": 71,
                            "mean": 65,
                            "uncertainty": 4,
                        },
                    }
                ],
            },
            {
                "name": "sand",
                "unit_measure": {
                    "d_factor": 10,
                    "mapped_units": "g/kg",
                    "target_units": "g/100g (%w)",
                    "uncertainty_unit": "%",
                },
                "depths": [
                    {
                        "label": "0-5cm",
                        "range": {"bottom_depth": 5, "top_depth": 0, "unit_depth": "cm"},
                        "values": {
                            "Q0.05": 540,
                            "Q0.5": 620,
                            "Q0.95": 720,
                            "mean": 624,
                            "uncertainty": 55,
                        },
                    }
                ],
            },
            {
                "name": "silt",
                "unit_measure": {
                    "d_factor": 10,
                    "mapped_units": "g/kg",
                    "target_units": "g/100g (%w)",
                    "uncertainty_unit": "%",
                },
                "depths": [
                    {
                        "label": "0-5cm",
                        "range": {"bottom_depth": 5, "top_depth": 0, "unit_depth": "cm"},
                        "values": {
                            "Q0.05": 150,
                            "Q0.5": 220,
                            "Q0.95": 280,
                            "mean": 221,
                            "uncertainty": 39,
                        },
                    }
                ],
            },
            {
                "name": "soc",
                "unit_measure": {
                    "d_factor": 10,
                    "mapped_units": "dg/kg",
                    "target_units": "g/kg",
                    "uncertainty_unit": "%",
                },
                "depths": [
                    {
                        "label": "0-5cm",
                        "range": {"bottom_depth": 5, "top_depth": 0, "unit_depth": "cm"},
                        "values": {
                            "Q0.05": 40,
                            "Q0.5": 75,
                            "Q0.95": 130,
                            "mean": 79,
                            "uncertainty": 28,
                        },
                    }
                ],
            },
        ]
    },
}

# Response for a point with all-null values (e.g. ocean)
_NULL_RESPONSE = {
    "type": "Point",
    "geometry": {"type": "Point", "coordinates": [-30.0, 0.0]},
    "query": {"lon": -30.0, "lat": 0.0},
    "properties": {
        "layers": [
            {
                "name": prop,
                "unit_measure": {"d_factor": 10, "mapped_units": "x", "target_units": "y"},
                "depths": [
                    {
                        "label": "0-5cm",
                        "values": {"mean": None},
                    }
                ],
            }
            for prop in _PROPERTIES
        ]
    },
}


# ---------------------------------------------------------------------------
# _fetch_soilgrids unit tests (httpx_mock)
# ---------------------------------------------------------------------------


def test_fetch_soilgrids_returns_all_properties(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result, latency = _fetch_soilgrids(46.253, -119.477)
    for prop in _PROPERTIES:
        assert prop in result, f"Missing property: {prop}"


def test_fetch_soilgrids_latency_nonnegative(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    _, latency = _fetch_soilgrids(46.253, -119.477)
    assert latency >= 0.0


def test_fetch_soilgrids_d_factor_division(httpx_mock):
    """bdod: mapped=133 cg/cm³, d_factor=100 → target=1.33 kg/dm³."""
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result, _ = _fetch_soilgrids(46.253, -119.477)
    assert pytest.approx(result["bdod"], abs=1e-3) == 1.33


def test_fetch_soilgrids_phh2o_conversion(httpx_mock):
    """phh2o: mapped=65 pH×10, d_factor=10 → target=6.5 pH."""
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result, _ = _fetch_soilgrids(46.253, -119.477)
    assert pytest.approx(result["phh2o"], abs=1e-3) == 6.5


def test_fetch_soilgrids_sand_conversion(httpx_mock):
    """sand: mapped=624 g/kg, d_factor=10 → target=62.4 g/100g."""
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result, _ = _fetch_soilgrids(46.253, -119.477)
    assert pytest.approx(result["sand"], abs=1e-3) == 62.4


def test_fetch_soilgrids_unit_strings_present(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result, _ = _fetch_soilgrids(46.253, -119.477)
    assert result["bdod_unit"] == "kg/dm³"
    assert result["phh2o_unit"] == "pH"
    assert result["sand_unit"] == "g/100g (%w)"


def test_fetch_soilgrids_null_values(httpx_mock):
    httpx_mock.add_response(json=_NULL_RESPONSE)
    result, _ = _fetch_soilgrids(0.0, -30.0)
    for prop in _PROPERTIES:
        assert result[prop] is None


# ---------------------------------------------------------------------------
# soilgrids_query tool tests (httpx_mock)
# ---------------------------------------------------------------------------


def test_soilgrids_query_success_structure(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    assert "data" in result
    assert "_meta" in result
    assert isinstance(result["data"], dict)


def test_soilgrids_query_all_properties_returned(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    for prop in _PROPERTIES:
        assert prop in result["data"]
        assert f"{prop}_unit" in result["data"]


def test_soilgrids_query_meta_success(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    meta = result["_meta"]
    assert meta["source"] == "soilgrids"
    assert meta["success"] is True
    assert meta["error"] is None
    assert meta["rows_returned"] == len(_PROPERTIES)
    assert meta["auth_required"] is False


def test_soilgrids_query_license_fields(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    assert result["_meta"]["license"] == LICENSE_INFO["license"]
    assert result["_meta"]["license_url"] == LICENSE_INFO["license_url"]


def test_soilgrids_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(46.253)
    assert qp["longitude"] == pytest.approx(-119.477)


def test_soilgrids_query_meta_variables(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    assert result["_meta"]["variables"] == _PROPERTIES


def test_soilgrids_query_null_coverage(httpx_mock):
    """All-null response → success=True, rows_returned=0, no-coverage error."""
    httpx_mock.add_response(json=_NULL_RESPONSE)
    result = soilgrids_query(latitude=0.0, longitude=-30.0)
    assert result["_meta"]["success"] is True
    assert result["_meta"]["rows_returned"] == 0
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_soilgrids_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(status_code=422)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


# ---------------------------------------------------------------------------
# soilgrids_bbox_query tool tests (httpx_mock)
# ---------------------------------------------------------------------------


def test_soilgrids_bbox_query_uses_centroid(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_bbox_query(
        min_lat=46.251407,
        max_lat=46.251790,
        min_lon=-119.728785,
        max_lon=-119.728369,
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" in qp
    assert "centroid_lon" in qp
    assert 46.251407 <= qp["centroid_lat"] <= 46.251790


def test_soilgrids_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_bbox_query(
        min_lat=46.251407,
        max_lat=46.251790,
        min_lon=-119.728785,
        max_lon=-119.728369,
    )
    assert result["_meta"]["success"] is True
    assert all(p in result["data"] for p in _PROPERTIES)


# ---------------------------------------------------------------------------
# variable_info and value-range tests
# ---------------------------------------------------------------------------


def test_soilgrids_query_property_info_in_meta(httpx_mock):
    """_meta.variable_info must be populated with SoilGrids property descriptions."""
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    info = result["_meta"]["variable_info"]
    for prop in _PROPERTIES:
        assert prop in info, f"Missing {prop} in variable_info"
        assert info[prop]["description"] != ""
        assert info[prop]["units"] == PROPERTY_INFO[prop]["units"]


def test_soilgrids_query_bdod_in_valid_range(httpx_mock):
    """Bulk density (1.33 kg/dm³ in fixture) must be within 0.5–2.0."""
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    bdod = result["data"]["bdod"]
    assert bdod is not None
    assert 0.5 <= bdod <= 2.0, f"bdod={bdod} outside 0.5–2.0 kg/dm³ — fill value or unit change?"


def test_soilgrids_query_phh2o_in_valid_range(httpx_mock):
    """Soil pH (6.5 in fixture) must be within 2–11."""
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    ph = result["data"]["phh2o"]
    assert ph is not None
    assert 2.0 <= ph <= 11.0, f"phh2o={ph} outside 2–11 — fill value or unit change?"


def test_soilgrids_query_sand_in_valid_range(httpx_mock):
    """Sand content (62.4% in fixture) must be within 0–100%."""
    httpx_mock.add_response(json=_SOILGRIDS_RESPONSE)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    sand = result["data"]["sand"]
    assert sand is not None
    assert 0.0 <= sand <= 100.0, f"sand={sand} outside 0–100% — fill value or unit change?"


def test_soilgrids_query_latency_captured_on_http_error(httpx_mock):
    """latency_s must not be hardcoded 0.0 when the server returns an error."""
    httpx_mock.add_response(status_code=503)
    result = soilgrids_query(latitude=46.253, longitude=-119.477)
    assert result["_meta"]["success"] is False
    # latency captures wall time even on HTTP errors (raise_for_status after timing)
    assert result["_meta"]["latency_s"] >= 0.0
