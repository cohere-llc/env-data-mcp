"""Unit tests for env_data_mcp.sources.open_meteo (gated; recorded forecast at the FRC, trimmed)."""

from __future__ import annotations

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import EventResponse
from env_data_mcp.sources.open_meteo._constants import NC_ENV, OPEN_METEO_BASE_URL
from env_data_mcp.sources.open_meteo.tools import open_meteo_current

# Recorded 2026-09-12 (trimmed to the variables the adapter requests)
_FORECAST = {
    "latitude": 35.97577,
    "longitude": -84.27208,
    "elevation": 314.0,
    "current_units": {
        "time": "iso8601",
        "temperature_2m": "°C",
        "relative_humidity_2m": "%",
        "precipitation": "mm",
        "wind_speed_10m": "km/h",
        "wind_direction_10m": "°",
        "weather_code": "wmo code",
    },
    "current": {
        "time": "2026-09-12T17:45",
        "interval": 900,
        "temperature_2m": 27.0,
        "relative_humidity_2m": 76,
        "precipitation": 0.0,
        "wind_speed_10m": 3.7,
        "wind_direction_10m": 210,
        "weather_code": 3,
    },
    "daily_units": {
        "time": "iso8601",
        "temperature_2m_max": "°C",
        "temperature_2m_min": "°C",
        "precipitation_sum": "mm",
        "weather_code": "wmo code",
    },
    "daily": {
        "time": ["2026-09-12", "2026-09-13"],
        "temperature_2m_max": [28.7, 31.2],
        "temperature_2m_min": [22.1, 20.1],
        "precipitation_sum": [59.6, 0.0],
        "weather_code": [61, 2],
    },
}
_URL = (
    f"{OPEN_METEO_BASE_URL}/forecast?latitude=35.9748&longitude=-84.277"
    "&current=temperature_2m%2Crelative_humidity_2m%2Cprecipitation%2Cwind_speed_10m%2Cwind_direction_10m%2Cweather_code"
    "&daily=temperature_2m_max%2Ctemperature_2m_min%2Cprecipitation_sum%2Cweather_code&forecast_days=2&timezone=UTC"
)


@pytest.fixture(autouse=True)
def _fresh():
    feeds.cache().clear()
    yield
    feeds.cache().clear()


def test_gated_without_the_nc_attestation(monkeypatch):
    monkeypatch.delenv(NC_ENV, raising=False)
    r = open_meteo_current(latitude=35.9748, longitude=-84.277)
    EventResponse.model_validate(r)
    assert r["data"] == [] and r["_meta"]["success"] is False
    assert (
        r["_meta"]["error"].startswith("gated: non-commercial terms")
        and NC_ENV in r["_meta"]["error"]
    )
    assert "NON-COMMERCIAL" in r["_meta"]["license"]


def test_current_and_forecast_when_allowed(httpx_mock, monkeypatch):
    monkeypatch.setenv(NC_ENV, "1")
    httpx_mock.add_response(url=_URL, json=_FORECAST)
    r = open_meteo_current(latitude=35.9748, longitude=-84.277, forecast_days=2)
    EventResponse.model_validate(r)
    assert r["_meta"]["success"] is True and len(r["data"]) == 1
    rec = r["data"][0]
    assert rec["kind"] == "weather" and rec["magnitude"] == 27.0 and rec["magnitude_unit"] == "°C"
    assert rec["t_start"] == "2026-09-12T17:45Z" and rec["lat"] == 35.97577
    assert rec["properties"]["current"]["relative_humidity_2m"] == 76
    assert rec["properties"]["forecast_daily"][0] == {
        "time": "2026-09-12",
        "temperature_2m_max": 28.7,
        "temperature_2m_min": 22.1,
        "precipitation_sum": 59.6,
        "weather_code": 61,
    }
    r2 = open_meteo_current(latitude=35.9748, longitude=-84.277, forecast_days=2)
    assert r2["_meta"]["cached"] is True and len(httpx_mock.get_requests()) == 1
    r = open_meteo_current(latitude=35.9748, longitude=-84.277, forecast_days=99)
    assert r["_meta"]["success"] is False and "forecast_days" in r["_meta"]["error"]
