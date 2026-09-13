"""Unit tests for env_data_mcp.sources.usgs_quakes (recorded FDSN GeoJSON, trimmed)."""

from __future__ import annotations

import datetime

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import EventResponse
from env_data_mcp.sources.usgs_quakes import _query, tools
from env_data_mcp.sources.usgs_quakes.tools import usgs_quakes_events

# Recorded 2026-09-12 (California, M ≥ 2.5, limit 3); trimmed to the fields the adapter reads
_FDSN_RESPONSE = {
    "type": "FeatureCollection",
    "metadata": {"status": 200, "api": "2.7.0", "limit": 3},
    "features": [
        {
            "type": "Feature",
            "properties": {
                "mag": 2.64,
                "place": "4 km ESE of Inglewood, CA",
                "time": 1789212739200,
                "updated": 1789227177528,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/ci41545920",
                "felt": 22,
                "alert": None,
                "status": "automatic",
                "tsunami": 0,
                "magType": "ml",
                "type": "earthquake",
                "title": "M 2.6 - 4 km ESE of Inglewood, CA",
            },
            "geometry": {"type": "Point", "coordinates": [-118.303166666667, 33.939, 18.79]},
            "id": "ci41545920",
        },
        {
            "type": "Feature",
            "properties": {
                "mag": 3.40807971450025,
                "place": "26 km ESE of Avalon, CA",
                "time": 1789211638640,
                "updated": 1789228191146,
                "url": "https://earthquake.usgs.gov/earthquakes/eventpage/ci41545880",
                "felt": 7,
                "alert": "green",
                "status": "reviewed",
                "tsunami": 0,
                "magType": "mw",
                "type": "earthquake",
                "title": "M 3.4 - 26 km ESE of Avalon, CA",
            },
            "geometry": {"type": "Point", "coordinates": [-118.09, 33.28, 9.5]},
            "id": "ci41545880",
        },
    ],
}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    feeds.cache().clear()
    # a fixed clock so the recorded URL matches: the tool module bound `fetch_quakes` by name
    fixed = datetime.datetime(2026, 9, 13, 0, 0, 0, tzinfo=datetime.UTC)
    monkeypatch.setattr(
        tools, "fetch_quakes", lambda **kw: _query.fetch_quakes(**{**kw, "now": fixed})
    )
    yield
    feeds.cache().clear()


def test_quakes_records_and_pager_severity(httpx_mock):
    httpx_mock.add_response(
        url="https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2026-09-12T00%3A00%3A00&endtime=2026-09-13T00%3A00%3A00&minmagnitude=2.5&limit=1000&orderby=time&minlatitude=32.0&maxlatitude=42.0&minlongitude=-125.0&maxlongitude=-114.0",
        json=_FDSN_RESPONSE,
    )
    r = usgs_quakes_events(min_lat=32.0, max_lat=42.0, min_lon=-125.0, max_lon=-114.0, days=1)
    EventResponse.model_validate(r)
    assert r["_meta"]["success"] is True and r["_meta"]["ttl_s"] == 300.0 and len(r["data"]) == 2
    a, b = r["data"]
    assert (
        a["kind"] == "quake"
        and a["id"] == "ci41545920"
        and a["magnitude"] == 2.64
        and a["magnitude_unit"] == "ml"
    )
    assert (
        a["lat"] == pytest.approx(33.939)
        and a["lon"] == pytest.approx(-118.3032)
        and a["properties"]["depth_km"] == 18.79
    )
    assert a["t_start"] == "2026-09-12T11:32:19Z" and a["t_end"] is None and a["severity"] is None
    assert b["severity"] == "green" and b["properties"]["status"] == "reviewed"
    assert (
        a["url"].startswith("https://earthquake.usgs.gov/")
        and a["licence"] == "Public domain (USGS)"
    )


def test_quakes_validation_and_cache(httpx_mock):
    r = usgs_quakes_events(days=99)
    assert r["_meta"]["success"] is False and "days" in r["_meta"]["error"] and r["data"] == []
    httpx_mock.add_response(
        url="https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2026-09-12T00%3A00%3A00&endtime=2026-09-13T00%3A00%3A00&minmagnitude=4.5&limit=10&orderby=time",
        json=_FDSN_RESPONSE,
    )
    r1 = usgs_quakes_events(days=1, min_magnitude=4.5, limit=10)
    r2 = usgs_quakes_events(days=1, min_magnitude=4.5, limit=10)
    assert (
        r1["_meta"]["cached"] is False
        and r2["_meta"]["cached"] is True
        and len(httpx_mock.get_requests()) == 1
    )
