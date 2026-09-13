"""Unit tests for env_data_mcp.sources.nws_alerts (recorded api.weather.gov alert, trimmed)."""

from __future__ import annotations

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import EventResponse
from env_data_mcp.sources.nws_alerts._constants import NWS_BASE_URL
from env_data_mcp.sources.nws_alerts.tools import nws_alerts_at

# Recorded 2026-09-12 from /alerts/active?area=TX (one zone-based alert, geometry null), trimmed
_ALERT = {
    "id": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.57321e81.001.1",
    "type": "Feature",
    "geometry": None,
    "properties": {
        "@id": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.57321e81.001.1",
        "id": "urn:oid:2.49.0.1.840.0.57321e81.001.1",
        "areaDesc": "Coryell",
        "affectedZones": ["https://api.weather.gov/zones/forecast/TXZ157"],
        "sent": "2026-09-12T11:47:00-05:00",
        "effective": "2026-09-12T11:47:00-05:00",
        "onset": "2026-09-12T13:00:00-05:00",
        "expires": "2026-09-12T20:00:00-05:00",
        "ends": "2026-09-12T20:00:00-05:00",
        "status": "Actual",
        "messageType": "Alert",
        "category": "Met",
        "severity": "Moderate",
        "certainty": "Likely",
        "urgency": "Expected",
        "event": "Heat Advisory",
        "senderName": "NWS Fort Worth TX",
        "headline": "Heat Advisory issued September 12 at 11:47AM CDT until September 12 at 8:00PM",
        "instruction": "Take extra precautions when outside.",
    },
}
_POLY_ALERT = {
    "id": "x",
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [[-84.4, 35.9], [-84.2, 35.9], [-84.2, 36.1], [-84.4, 36.1], [-84.4, 35.9]]
        ],
    },
    "properties": {
        "@id": "https://api.weather.gov/alerts/x",
        "id": "x",
        "event": "Severe Thunderstorm Warning",
        "headline": "Severe Thunderstorm Warning",
        "severity": "Severe",
        "onset": "2026-09-12T18:00:00-04:00",
        "expires": "2026-09-12T18:45:00-04:00",
        "urgency": "Immediate",
        "certainty": "Observed",
    },
}


@pytest.fixture(autouse=True)
def _fresh():
    feeds.cache().clear()
    yield
    feeds.cache().clear()


def test_alerts_at_point_zone_based_and_polygon(httpx_mock):
    httpx_mock.add_response(
        url=f"{NWS_BASE_URL}/alerts/active?status=actual&message_type=alert%2Cupdate&point=31.4000%2C-97.8000",
        json={"type": "FeatureCollection", "features": [_ALERT, _POLY_ALERT]},
    )
    r = nws_alerts_at(latitude=31.4, longitude=-97.8)
    EventResponse.model_validate(r)
    assert r["_meta"]["success"] is True and r["_meta"]["ttl_s"] == 600.0 and len(r["data"]) == 2
    z, poly = r["data"]
    assert z["kind"] == "alert" and z["severity"] == "Moderate" and z["geometry"] is None
    assert z["lat"] == 31.4 and z["lon"] == -97.8 and z["properties"]["location_is_query_point"]
    assert z["t_start"] == "2026-09-12T13:00:00-05:00" and z["t_end"] == "2026-09-12T20:00:00-05:00"
    assert z["properties"]["event"] == "Heat Advisory" and z["properties"]["zones"] == [
        "https://api.weather.gov/zones/forecast/TXZ157"
    ]
    assert poly["geometry"]["type"] == "Polygon" and poly["lat"] == pytest.approx(35.98)
    assert poly["severity"] == "Severe" and not poly["properties"]["location_is_query_point"]
    # the User-Agent the NWS asks for
    assert "env-data-mcp" in httpx_mock.get_requests()[0].headers["User-Agent"]


def test_alerts_area_empty_and_validation(httpx_mock):
    httpx_mock.add_response(
        url=f"{NWS_BASE_URL}/alerts/active?status=actual&message_type=alert%2Cupdate&area=TN",
        json={"type": "FeatureCollection", "features": []},
    )
    r = nws_alerts_at(area="TN")
    assert r["_meta"]["success"] is True and r["data"] == []  # empty ≠ errored
    r = nws_alerts_at()
    assert r["_meta"]["success"] is False and "point" in r["_meta"]["error"]
    r = nws_alerts_at(latitude=31.4)
    assert r["_meta"]["success"] is False and "both" in r["_meta"]["error"]
