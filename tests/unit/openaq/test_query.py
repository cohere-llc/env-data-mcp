"""Unit tests for env_data_mcp.sources.openaq._query."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import patch

import pytest

from env_data_mcp.sources.openaq._constants import (
    OPENAQ_BASE_URL,
    Location,
    Parameter,
    Sensor,
)
from env_data_mcp.sources.openaq._query import (
    _build_headers,
    _collect_unavailable_variables,
    _extract_location,
    _extract_parameter,
    _fetch_bbox_locations,
    _fetch_measurements,
    _fetch_parameters,
    _fetch_point_locations,
    _fetch_sensor_measurements,
    _get_client,
    get_variable_info,
    query_bbox,
    query_point,
)

from .conftest import (
    _API_KEY,
    _EMPTY_MEASUREMENTS,
    _LAT,
    _LOCATION_RESPONSE,
    _LON,
    _MEASUREMENT_RESPONSE_NO2,
    _MEASUREMENT_RESPONSE_PM25,
    _PARAMETERS_RESPONSE,
)

# ---------------------------------------------------------------------------
# get_variable_info
# ---------------------------------------------------------------------------


def test_get_variable_info(httpx_mock):
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/parameters",
        json=_PARAMETERS_RESPONSE,
    )
    result = get_variable_info(_API_KEY)
    assert result == {
        "pm25": {"description": "particulate matter <= 2.5 microns", "units": "ug/m3"},
        "no2": {"description": "nitrogen dioxide", "units": "ppb"},
        "o3": {"description": "ozone", "units": "ppb"},
    }


# ---------------------------------------------------------------------------
# query_point
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_point_query_mock")
def test_query_point(httpx_mock):
    results, unavailable = query_point(
        lat=_LAT,
        lon=_LON,
        start_date="2019-08-19",
        end_date="2019-08-19",
        radius_km=5.0,
        variables=["pm25", "o3", "no2"],
        api_key=_API_KEY,
    )
    assert unavailable == ["o3"]
    assert len(results) == 1
    assert results
    assert results[0]["geometry"]["type"] == "Point"
    assert results[0]["geometry"]["coordinates"] == [_LON, _LAT]
    assert results[0]["latitude"] == _LAT
    assert results[0]["longitude"] == _LON
    assert len(results[0]["records"]) == 3
    for rec in results[0]["records"]:
        assert "no2" in rec or "pm25" in rec
        if "no2" in rec:
            assert rec["datetime"] == _MEASUREMENT_RESPONSE_NO2["results"][0]["period"]
            assert rec["no2"] == 5.0
            assert rec["no2_units"] == "ppb"
        if "pm25" in rec:
            assert rec["datetime"] in [r["period"] for r in _MEASUREMENT_RESPONSE_PM25["results"]]
            assert rec["pm25"] in [12.5, 14.1]
            assert rec["pm25_units"] == "ug/m3"


# ---------------------------------------------------------------------------
# query_bbox
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_bbox_query_mock")
def test_query_bbox(httpx_mock):
    results, unavailable = query_bbox(
        min_lat=_LAT,
        max_lat=_LAT + 1.0,
        min_lon=_LON,
        max_lon=_LON + 1.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
        variables=["pm25", "o3", "no2"],
        api_key=_API_KEY,
    )
    assert unavailable == ["o3"]
    assert len(results) == 1
    assert results
    assert results[0]["geometry"]["type"] == "Point"
    assert results[0]["geometry"]["coordinates"] == [_LON, _LAT]
    assert results[0]["latitude"] == _LAT
    assert results[0]["longitude"] == _LON
    assert len(results[0]["records"]) == 3
    for rec in results[0]["records"]:
        assert "no2" in rec or "pm25" in rec
        if "no2" in rec:
            assert rec["datetime"] == _MEASUREMENT_RESPONSE_NO2["results"][0]["period"]
            assert rec["no2"] == 5.0
            assert rec["no2_units"] == "ppb"
        if "pm25" in rec:
            assert rec["datetime"] in [r["period"] for r in _MEASUREMENT_RESPONSE_PM25["results"]]
            assert rec["pm25"] in [12.5, 14.1]
            assert rec["pm25_units"] == "ug/m3"


# ---------------------------------------------------------------------------
# _build_headers
# ---------------------------------------------------------------------------


def test_build_headers():
    header = _build_headers(_API_KEY)
    assert header == {"X-API-Key": _API_KEY, "Accept": "application/json"}


# ---------------------------------------------------------------------------
# _extract_parameter
# ---------------------------------------------------------------------------


def test_extract_parameter():
    result = _extract_parameter(
        {
            "id": 1234,
            "name": "Foo",
            "description": "A meaningless placeholder",
            "units": "foobits",
        }
    )
    assert result == Parameter(
        id=1234,
        name="Foo",
        description="A meaningless placeholder",
        units="foobits",
    )


# ---------------------------------------------------------------------------
# _fetch_parameters
# ---------------------------------------------------------------------------


def test_fetch_parameters(httpx_mock, monkeypatch):
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/parameters",
        json=_PARAMETERS_RESPONSE,
    )
    with patch("env_data_mcp.sources.openaq._query._AVAILABLE_PARAMETERS", None):
        client = _get_client()
        result = _fetch_parameters(client, _API_KEY)
    assert len(result) == 3
    for id, param in result.items():
        assert id == param.id
        assert id in [111, 222, 333]
        assert param.name in ["pm25", "no2", "o3"]


def test_fetch_parameters_uses_cache(httpx_mock, monkeypatch):
    params: list[Parameter] = [
        Parameter(id=531, name="foo", description="foooo", units="foobits"),
        Parameter(id=312, name="bar", description="baaaar", units="millibars"),
    ]
    cached = MappingProxyType({p.id: p for p in params})
    with patch("env_data_mcp.sources.openaq._query._AVAILABLE_PARAMETERS", cached):
        client = _get_client()
        result = _fetch_parameters(client, _API_KEY)
    assert len(result) == 2
    for param in params:
        assert param in result.values()
        assert param.id in result
    assert len(httpx_mock.get_requests()) == 0


# ---------------------------------------------------------------------------
# _collect_unavailable_variables
# ---------------------------------------------------------------------------


def test_collect_unavailable_variables():
    results = [{"records": [{"pm25": 7}, {"o3": 2}]}, {"records": [{"no2": 4.2}]}]
    vars = ["o3", "no2", "pm10", "pm25", "foo"]
    unavail = _collect_unavailable_variables(results, vars)
    assert len(unavail) == 2
    for var in ["pm10", "foo"]:
        assert var in unavail


# ---------------------------------------------------------------------------
# _extract_location
# ---------------------------------------------------------------------------


def test_extract_location():
    data = _LOCATION_RESPONSE["results"][0]
    result: Location | None = _extract_location(data, [222, 333])
    assert result is not None
    assert result.id == 999
    assert result.name == "Yakima Monitor"
    assert result.lat == _LAT
    assert result.lon == _LON
    assert len(result.sensors) == 1
    assert result.sensors[0].id == 523
    assert result.sensors[0].parameter_id == 222

    result = _extract_location(data, [333])
    assert result is None

    result = _extract_location(data, [111, 222])
    assert result is not None
    assert result.id == 999
    assert result.lat == _LAT
    assert result.lon == _LON
    assert len(result.sensors) == 2
    pairs = [(sensor.id, sensor.parameter_id) for sensor in result.sensors]
    assert (523, 222) in pairs
    assert (312, 111) in pairs


# ---------------------------------------------------------------------------
# _fetch_point_locations
# ---------------------------------------------------------------------------


def test_fetch_point_locations(httpx_mock, monkeypatch):
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/locations?coordinates={_LAT},{_LON}&radius={5000.0}",
        json=_LOCATION_RESPONSE,
        is_reusable=True,
    )
    client = _get_client()
    locs = _fetch_point_locations(client, _API_KEY, _LAT, _LON, 5.0, [222, 333])
    assert len(locs) == 1
    assert locs[0].id == 999
    assert locs[0].lat == _LAT
    assert locs[0].lon == _LON
    assert len(locs[0].sensors) == 1
    assert locs[0].sensors[0].id == 523
    assert locs[0].sensors[0].parameter_id == 222

    locs = _fetch_point_locations(client, _API_KEY, _LAT, _LON, 5.0, [333, 444])
    assert len(locs) == 0


# ---------------------------------------------------------------------------
# _fetch_bbox_locations
# ---------------------------------------------------------------------------


def test_fetch_bbox_locations(httpx_mock, monkeypatch):
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/locations?bbox={_LON},{_LAT},{_LON + 1.0},{_LAT + 1.0}",
        json=_LOCATION_RESPONSE,
        is_reusable=True,
    )
    client = _get_client()
    locs = _fetch_bbox_locations(client, _API_KEY, _LAT, _LAT + 1.0, _LON, _LON + 1.0, [222, 333])
    assert len(locs) == 1
    assert locs[0].id == 999
    assert locs[0].lat == _LAT
    assert locs[0].lon == _LON
    assert len(locs[0].sensors) == 1
    assert locs[0].sensors[0].id == 523
    assert locs[0].sensors[0].parameter_id == 222

    locs = _fetch_bbox_locations(client, _API_KEY, _LAT, _LAT + 1.0, _LON, _LON + 1.0, [333, 444])
    assert len(locs) == 0


# ---------------------------------------------------------------------------
# _fetch_sensor_measurements
# ---------------------------------------------------------------------------


def test_fetch_sensor_measurements(httpx_mock, monkeypatch):
    monkeypatch.setattr("env_data_mcp.sources.openaq._query._AVAILABLE_PARAMETERS", None)
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/sensors/523/measurements?date_from=2019-08-19T00:00:00Z&date_to=2019-08-19T23:59:59Z",
        json=_MEASUREMENT_RESPONSE_NO2,
    )
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/sensors/312/measurements?date_from=2019-08-19T00:00:00Z&date_to=2019-08-19T23:59:59Z",
        json=_MEASUREMENT_RESPONSE_PM25,
    )
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/sensors/456/measurements?date_from=2019-08-19T00:00:00Z&date_to=2019-08-19T23:59:59Z",
        json=_EMPTY_MEASUREMENTS,
    )
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/parameters",
        json=_PARAMETERS_RESPONSE,
        is_reusable=True,
    )
    pm25 = Sensor(id=312, parameter_id=111)
    no2 = Sensor(id=523, parameter_id=222)
    o3 = Sensor(id=456, parameter_id=333)
    client = _get_client()
    results = _fetch_sensor_measurements(client, _API_KEY, no2, "2019-08-19", "2019-08-19")
    assert len(results) == 1
    assert results[0]["datetime"] == _MEASUREMENT_RESPONSE_NO2["results"][0]["period"]
    assert results[0]["no2"] == 5.0
    assert results[0]["no2_units"] == "ppb"

    results = _fetch_sensor_measurements(client, _API_KEY, pm25, "2019-08-19", "2019-08-19")
    assert len(results) == 2
    for res in results:
        assert res["datetime"] in [r["period"] for r in _MEASUREMENT_RESPONSE_PM25["results"]]
        assert res["pm25"] in [12.5, 14.1]
        assert res["pm25_units"] == "ug/m3"

    results = _fetch_sensor_measurements(client, _API_KEY, o3, "2019-08-19", "2019-08-19")
    assert len(results) == 0


# ---------------------------------------------------------------------------
# _fetch_measurements
# ---------------------------------------------------------------------------


def test_fetch_measurements(httpx_mock, monkeypatch):
    monkeypatch.setattr("env_data_mcp.sources.openaq._query._AVAILABLE_PARAMETERS", None)
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/sensors/523/measurements?date_from=2019-08-19T00:00:00Z&date_to=2019-08-19T23:59:59Z",
        json=_MEASUREMENT_RESPONSE_NO2,
    )
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/sensors/312/measurements?date_from=2019-08-19T00:00:00Z&date_to=2019-08-19T23:59:59Z",
        json=_MEASUREMENT_RESPONSE_PM25,
    )
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/sensors/456/measurements?date_from=2019-08-19T00:00:00Z&date_to=2019-08-19T23:59:59Z",
        json=_EMPTY_MEASUREMENTS,
    )
    httpx_mock.add_response(
        url=f"{OPENAQ_BASE_URL}/parameters",
        json=_PARAMETERS_RESPONSE,
        is_reusable=True,
    )
    locs = [
        Location(
            id=72,
            lat=_LAT,
            lon=_LON,
            sensors=[
                Sensor(id=312, parameter_id=111),
                Sensor(id=456, parameter_id=333),
            ],
            name="Yakima Monitor",
        ),
        Location(
            id=53,
            lat=_LAT + 1.0,
            lon=_LON + 1.0,
            sensors=[
                Sensor(id=523, parameter_id=222),
            ],
        ),
    ]
    client = _get_client()
    result = _fetch_measurements(
        client, _API_KEY, locations=locs, start_date="2019-08-19", end_date="2019-08-19"
    )
    assert len(result) == 2
    assert result[0]["station_id"] == 72
    assert result[0]["station_name"] == "Yakima Monitor"
    assert result[1]["station_id"] == 53
    assert result[1]["station_name"] is None
    assert result[0]["geometry"]["type"] == "Point"
    assert result[0]["geometry"]["coordinates"] == [_LON, _LAT]
    assert result[0]["latitude"] == _LAT
    assert result[0]["longitude"] == _LON
    assert len(result[0]["records"]) == 2
    for rec in result[0]["records"]:
        assert rec["datetime"] in [r["period"] for r in _MEASUREMENT_RESPONSE_PM25["results"]]
        assert rec["pm25"] in [12.5, 14.1]
        assert rec["pm25_units"] == "ug/m3"
    assert result[1]["geometry"]["type"] == "Point"
    assert result[1]["geometry"]["coordinates"] == [_LON + 1.0, _LAT + 1.0]
    assert result[1]["latitude"] == _LAT + 1.0
    assert result[1]["longitude"] == _LON + 1.0
    assert len(result[1]["records"]) == 1
    rec = result[1]["records"][0]
    assert rec["datetime"] == _MEASUREMENT_RESPONSE_PM25["results"][0]["period"]
    assert rec["no2"] == 5.0
    assert rec["no2_units"] == "ppb"
