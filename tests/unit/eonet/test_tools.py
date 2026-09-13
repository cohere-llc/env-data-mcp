"""Unit tests for env_data_mcp.sources.eonet (recorded EONET v3 response, trimmed)."""

from __future__ import annotations

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import EventResponse
from env_data_mcp.sources.eonet._constants import EONET_BASE_URL
from env_data_mcp.sources.eonet.tools import eonet_events

# Recorded 2026-09-12 from https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=10&limit=4
# (trimmed)
_EONET_RESPONSE = {
    "title": "EONET Events",
    "events": [
        {
            "id": "EONET_24184",
            "title": "Tropical Storm Norbert",
            "description": None,
            "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_24184",
            "closed": None,
            "categories": [{"id": "severeStorms", "title": "Severe Storms"}],
            "sources": [
                {"id": "JTWC", "url": "https://www.metoc.navy.mil/jtwc/products/ep1426.tcw"}
            ],
            "geometry": [
                {
                    "magnitudeValue": 35.0,
                    "magnitudeUnit": "kts",
                    "date": "2026-09-10T06:00:00Z",
                    "type": "Point",
                    "coordinates": [-117.3, 16.4],
                },
                {
                    "magnitudeValue": 50.0,
                    "magnitudeUnit": "kts",
                    "date": "2026-09-12T12:00:00Z",
                    "type": "Point",
                    "coordinates": [-127.8, 17.2],
                },
            ],
        },
        {
            "id": "EONET_12618",
            "title": "Iceberg A84",
            "description": None,
            "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_12618",
            "closed": None,
            "categories": [{"id": "seaLakeIce", "title": "Sea and Lake Ice"}],
            "sources": [{"id": "NATICE", "url": "https://usicecenter.gov/pub/Iceberg_Tabular.csv"}],
            "geometry": [
                {
                    "magnitudeValue": 33.0,
                    "magnitudeUnit": "NM^2",
                    "date": "2026-09-11T00:00:00Z",
                    "type": "Point",
                    "coordinates": [-45.6, -75.1],
                }
            ],
        },
        {
            "id": "EONET_99999",
            "title": "Nameless polygon fire",
            "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_99999",
            "closed": "2026-09-11T00:00:00Z",
            "categories": [{"id": "wildfires", "title": "Wildfires"}],
            "sources": [],
            "geometry": [
                {
                    "date": "2026-09-09T00:00:00Z",
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-120.0, 40.0],
                            [-119.0, 40.0],
                            [-119.0, 41.0],
                            [-120.0, 41.0],
                            [-120.0, 40.0],
                        ]
                    ],
                }
            ],
        },
        {"id": "EONET_0", "title": "no geometry", "categories": [], "sources": [], "geometry": []},
        {
            "id": "EONET_BAD",
            "title": "swapped coordinates (seen live 2026-09-12)",
            "categories": [{"id": "wildfires", "title": "Wildfires"}],
            "sources": [],
            "geometry": [
                {"date": "2026-09-09T00:00:00Z", "type": "Point", "coordinates": [40.0, 99.07]}
            ],
        },
    ],
}


@pytest.fixture(autouse=True)
def _fresh():
    feeds.cache().clear()
    yield
    feeds.cache().clear()


def test_eonet_events_records_schema_and_kinds(httpx_mock):
    httpx_mock.add_response(
        url=f"{EONET_BASE_URL}/events?status=open&days=10&limit=4", json=_EONET_RESPONSE
    )
    r = eonet_events(days=10, limit=4)
    EventResponse.model_validate(r)
    assert r["_meta"]["success"] is True and r["_meta"]["source"] == "eonet"
    assert (
        r["_meta"]["ttl_s"] == 1800.0
        and r["_meta"]["cached"] is False
        and r["_meta"]["fetched_at"].endswith("Z")
    )
    assert r["_meta"]["auth_required"] is False and r["_meta"]["license"] == "Public domain (NASA)"
    assert len(r["data"]) == 3  # the geometry-less and the out-of-range events are dropped
    storm, ice, fire = r["data"]
    assert (
        storm["kind"] == "storm" and storm["lat"] == 17.2 and storm["lon"] == -127.8
    )  # the LATEST point
    assert storm["geometry"]["type"] == "LineString" and len(storm["geometry"]["coordinates"]) == 2
    assert storm["t_start"] == "2026-09-10T06:00:00Z" and storm["t_end"] is None
    assert storm["magnitude"] == 50.0 and storm["magnitude_unit"] == "kts"
    assert (
        storm["properties"]["category"] == "severeStorms"
        and storm["properties"]["n_geometries"] == 2
    )
    assert ice["kind"] == "ice" and ice["geometry"] is None
    assert (
        fire["kind"] == "fire"
        and fire["geometry"]["type"] == "Polygon"
        and fire["t_end"] == "2026-09-11T00:00:00Z"
    )
    assert fire["lat"] == pytest.approx(40.4) and fire["lon"] == pytest.approx(
        -119.6
    )  # the ring centroid
    assert all(rec["licence"] == "Public domain (NASA)" for rec in r["data"])


def test_eonet_bbox_order_and_ttl_cache(httpx_mock):
    # EONET wants minLon,maxLat,maxLon,minLat; the second identical call is served from the cache
    # (one HTTP call)
    httpx_mock.add_response(
        url=f"{EONET_BASE_URL}/events?status=open&days=7&limit=500&bbox=-90.0%2C40.0%2C-80.0%2C30.0",
        json=_EONET_RESPONSE,
    )
    r1 = eonet_events(min_lat=30.0, max_lat=40.0, min_lon=-90.0, max_lon=-80.0)
    r2 = eonet_events(min_lat=30.0, max_lat=40.0, min_lon=-90.0, max_lon=-80.0)
    assert r1["_meta"]["cached"] is False and r2["_meta"]["cached"] is True
    assert r2["_meta"]["fetched_at"] == r1["_meta"]["fetched_at"] and r2["data"] == r1["data"]
    assert len(httpx_mock.get_requests()) == 1


def test_eonet_bad_inputs_and_http_error_are_responses(httpx_mock):
    r = eonet_events(min_lat=30.0)  # a partial bbox
    assert (
        r["data"] == [] and r["_meta"]["success"] is False and "all be given" in r["_meta"]["error"]
    )
    r = eonet_events(status="nope")
    assert r["_meta"]["success"] is False and "status" in r["_meta"]["error"]
    httpx_mock.add_response(
        url=f"{EONET_BASE_URL}/events?status=open&days=7&limit=500", status_code=503
    )
    r = eonet_events()
    assert r["data"] == [] and r["_meta"]["success"] is False and "503" in r["_meta"]["error"]
    EventResponse.model_validate(r)
