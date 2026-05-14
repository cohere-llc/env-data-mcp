"""Unit tests for the OpenAQ source adapter.

All httpx calls are intercepted by pytest-httpx; no network access required.
"""

from __future__ import annotations

import re

import pytest

from env_data_mcp.sources.openaq import (
    _OPENAQ_BASE,
    LICENSE_INFO,
    VARIABLE_INFO,
    openaq_bbox_query,
    openaq_query,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_YAKIMA_LAT = 46.2531882
_YAKIMA_LON = -119.4768203
_API_KEY = "test-api-key-1234"

# Matches requests to the /locations endpoint and validates bbox= and limit=100
# are present (in any order), preventing regressions if the query format changes.
_LOCATIONS_URL_RE = re.compile(
    rf"{re.escape(_OPENAQ_BASE)}/locations\?"
    r"(?=[^#]*\bbbox=[^&]+)"
    r"(?=[^#]*\blimit=100(?:&|$))"
    r"[^#]*$"
)

_LOCATION_RESPONSE = {
    "results": [
        {
            "id": 999,
            "name": "Yakima Monitor",
            "sensors": [
                {"id": 111, "parameter": {"name": "pm25", "units": "µg/m³"}},
                {"id": 222, "parameter": {"name": "no2", "units": "µg/m³"}},
            ],
        }
    ]
}

_MEASUREMENT_RESPONSE_PM25 = {
    "results": [
        {
            "value": 12.5,
            "period": {"datetimeFrom": {"local": "2019-08-19T10:00:00-07:00"}},
            "coordinates": {"latitude": _YAKIMA_LAT, "longitude": _YAKIMA_LON},
        },
        {
            "value": 14.1,
            "period": {"datetimeFrom": {"local": "2019-08-19T11:00:00-07:00"}},
            "coordinates": {"latitude": _YAKIMA_LAT, "longitude": _YAKIMA_LON},
        },
    ]
}

_MEASUREMENT_RESPONSE_NO2 = {
    "results": [
        {
            "value": 5.0,
            "period": {"datetimeFrom": {"local": "2019-08-19T10:00:00-07:00"}},
            "coordinates": {"latitude": _YAKIMA_LAT, "longitude": _YAKIMA_LON},
        }
    ]
}

_EMPTY_MEASUREMENTS = {"results": []}


@pytest.fixture
def _set_api_key(monkeypatch):
    monkeypatch.setenv("OPENAQ_API_KEY", _API_KEY)


@pytest.fixture
def _unset_api_key(monkeypatch):
    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# No-auth fallback
# ---------------------------------------------------------------------------


def test_openaq_query_no_api_key_returns_auth_error(_unset_api_key):
    result = openaq_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["auth_required"] is True
    assert result["_meta"]["auth_present"] is False
    assert "OPENAQ_API_KEY" in result["_meta"]["error"]
    assert result["data"] == []


# ---------------------------------------------------------------------------
# Successful measurement fetch
# ---------------------------------------------------------------------------


def test_openaq_query_success(_set_api_key, httpx_mock):
    httpx_mock.add_response(
        url=_LOCATIONS_URL_RE,
        json=_LOCATION_RESPONSE,
    )
    httpx_mock.add_response(
        url=f"{_OPENAQ_BASE}/sensors/111/measurements?date_from=2019-08-19T00%3A00%3A00Z&date_to=2019-08-19T23%3A59%3A59Z&limit=100&page=1",
        json=_MEASUREMENT_RESPONSE_PM25,
    )
    httpx_mock.add_response(
        url=f"{_OPENAQ_BASE}/sensors/222/measurements?date_from=2019-08-19T00%3A00%3A00Z&date_to=2019-08-19T23%3A59%3A59Z&limit=100&page=1",
        json=_MEASUREMENT_RESPONSE_NO2,
    )

    result = openaq_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
        parameters=["pm25", "no2"],
    )

    assert result["_meta"]["success"] is True
    assert result["_meta"]["source"] == "openaq"
    assert result["_meta"]["rows_returned"] == 3
    assert result["_meta"]["auth_required"] is True
    assert result["_meta"]["auth_present"] is True


def test_openaq_query_meta_fields(_set_api_key, httpx_mock):
    httpx_mock.add_response(
        url=_LOCATIONS_URL_RE,
        json=_LOCATION_RESPONSE,
    )
    httpx_mock.add_response(
        url=f"{_OPENAQ_BASE}/sensors/111/measurements?date_from=2019-08-19T00%3A00%3A00Z&date_to=2019-08-19T23%3A59%3A59Z&limit=100&page=1",
        json=_MEASUREMENT_RESPONSE_PM25,
    )
    httpx_mock.add_response(
        url=f"{_OPENAQ_BASE}/sensors/222/measurements?date_from=2019-08-19T00%3A00%3A00Z&date_to=2019-08-19T23%3A59%3A59Z&limit=100&page=1",
        json=_EMPTY_MEASUREMENTS,
    )

    result = openaq_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
        parameters=["pm25", "no2"],
    )

    assert result["_meta"]["license"] == LICENSE_INFO["license"]
    assert result["_meta"]["license_url"] == LICENSE_INFO["license_url"]
    assert "pm25" in result["_meta"]["variable_info"]
    assert result["_meta"]["latency_s"] >= 0


def test_openaq_query_variable_info_contains_units(_set_api_key, httpx_mock):
    httpx_mock.add_response(
        url=_LOCATIONS_URL_RE,
        json={"results": []},
    )
    result = openaq_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
        parameters=["pm25"],
    )
    # Even on zero results the variable_info should be populated.
    assert result["_meta"]["variable_info"]["pm25"]["units"] == VARIABLE_INFO["pm25"]["units"]


# ---------------------------------------------------------------------------
# Sparse-coverage fallback (no stations)
# ---------------------------------------------------------------------------


def test_openaq_query_no_stations_returns_success_empty(_set_api_key, httpx_mock):
    httpx_mock.add_response(
        url=_LOCATIONS_URL_RE,
        json={"results": []},
    )
    result = openaq_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] is not None  # Descriptive message about sparse coverage.


# ---------------------------------------------------------------------------
# HTTP error propagated as structured failure
# ---------------------------------------------------------------------------


def test_openaq_query_http_error_returns_structured(_set_api_key, httpx_mock):
    httpx_mock.add_response(
        url=_LOCATIONS_URL_RE,
        status_code=500,
        text="Internal Server Error",
    )
    result = openaq_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    assert result["_meta"]["success"] is False
    assert result["data"] == []


# ---------------------------------------------------------------------------
# query_params echoed
# ---------------------------------------------------------------------------


def test_openaq_query_params_echoed(_set_api_key, httpx_mock):
    httpx_mock.add_response(
        url=_LOCATIONS_URL_RE,
        json={"results": []},
    )
    result = openaq_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-20",
        parameters=["pm25"],
    )
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == _YAKIMA_LAT
    assert qp["radius_km"] == 50.0
    assert qp["parameters"] == ["pm25"]


# ---------------------------------------------------------------------------
# Row cap
# ---------------------------------------------------------------------------


def test_openaq_query_capped_flag_set(_set_api_key, httpx_mock):
    # Build a response with exactly limit rows.
    limit = 5
    loc_response = {
        "results": [
            {
                "id": 1,
                "name": "Station",
                "sensors": [{"id": 10, "parameter": {"name": "pm25", "units": "µg/m³"}}],
            }
        ]
    }
    meas_response = {
        "results": [
            {
                "value": float(i),
                "period": {"datetimeFrom": {"local": f"2019-08-19T{i:02d}:00:00-07:00"}},
                "coordinates": {"latitude": _YAKIMA_LAT, "longitude": _YAKIMA_LON},
            }
            for i in range(limit)
        ]
    }
    httpx_mock.add_response(
        url=_LOCATIONS_URL_RE,
        json=loc_response,
    )
    httpx_mock.add_response(
        url=f"{_OPENAQ_BASE}/sensors/10/measurements?date_from=2019-08-19T00%3A00%3A00Z&date_to=2019-08-19T23%3A59%3A59Z&limit={limit}&page=1",
        json=meas_response,
    )

    result = openaq_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
        parameters=["pm25"],
        limit=limit,
    )

    assert result["_meta"]["capped"] is True


# ---------------------------------------------------------------------------
# openaq_bbox_query delegates correctly
# ---------------------------------------------------------------------------


def test_openaq_bbox_query_delegates(_set_api_key, httpx_mock):
    """bbox_query should produce a valid response with correct source."""
    # Intercept any /locations request.
    httpx_mock.add_response(
        method="GET",
        json={"results": []},
    )
    result = openaq_bbox_query(
        min_lat=46.0,
        max_lat=46.5,
        min_lon=-119.8,
        max_lon=-119.2,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    assert result["_meta"]["source"] == "openaq"
    assert result["_meta"]["success"] is True


# ---------------------------------------------------------------------------
# _fetch_locations — polar clamping avoids division by zero (line 122)
# ---------------------------------------------------------------------------


def test_openaq_query_near_pole_no_division_error(_set_api_key, httpx_mock):
    """Querying at lat=90 must not raise ZeroDivisionError."""
    httpx_mock.add_response(method="GET", json={"results": []})
    # Should complete without error; polar lat is clamped to 89.9 internally.
    result = openaq_query(
        latitude=90.0,
        longitude=0.0,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    assert result["_meta"]["success"] is True
