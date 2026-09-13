"""Unit tests for env_data_mcp.sources.usgs_water (recorded OGC API response, trimmed)."""

from __future__ import annotations

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import EventResponse
from env_data_mcp.sources.usgs_water._constants import KEY_NAME, WATER_BASE_URL
from env_data_mcp.sources.usgs_water.tools import usgs_water_latest

# Recorded 2026-09-12 at the FRC: latest-continuous/items?bbox=…&parameter_code=00060&limit=2
_WATER = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "time_series_id": "0a94fe9380d54106aeed5b3dec714a3b",
                "monitoring_location_id": "USGS-03536320",
                "parameter_code": "00060",
                "statistic_id": "00011",
                "time": "1995-10-10T03:55:00+00:00",
                "value": "0.06",
                "unit_of_measure": "ft^3/s",
                "approval_status": "Approved",
                "qualifier": None,
                "last_modified": "2025-09-05T12:50:41.037136+00:00",
            },
            "id": "0d27e413-3224-49e8-9e49-ffb723dfab09",
            "geometry": {"type": "Point", "coordinates": [-84.3055289156988, 35.9323165148117]},
        }
    ],
    "numberReturned": 1,
}
_URL = (
    f"{WATER_BASE_URL}/collections/latest-continuous/items"
    "?parameter_code=00060&limit=100&f=json&bbox=-84.6%2C35.8%2C-84.0%2C36.2"
)


@pytest.fixture(autouse=True)
def _fresh():
    feeds.cache().clear()
    feeds.reset_governors()
    yield
    feeds.cache().clear()
    feeds.reset_governors()


def test_latest_values_keyless_tier(httpx_mock, monkeypatch):
    monkeypatch.delenv(KEY_NAME, raising=False)
    httpx_mock.add_response(url=_URL, json=_WATER)
    r = usgs_water_latest(min_lat=35.8, max_lat=36.2, min_lon=-84.6, max_lon=-84.0)
    EventResponse.model_validate(r)
    assert r["_meta"]["success"] is True and r["_meta"]["auth_required"] is False
    assert r["_meta"]["quota"]["limit"] == 50 and r["_meta"]["quota"]["used"] == 1
    rec = r["data"][0]
    assert rec["kind"] == "water" and rec["magnitude"] == 0.06 and rec["magnitude_unit"] == "ft^3/s"
    assert rec["t_start"] == "1995-10-10T03:55:00+00:00"  # an old latest value, reported as is
    assert rec["properties"]["monitoring_location_id"] == "USGS-03536320"
    assert rec["url"].endswith("/03536320/") and rec["properties"]["parameter"].startswith(
        "discharge"
    )
    assert "X-Api-Key" not in httpx_mock.get_requests()[0].headers


def test_keyed_tier_uses_header_and_never_echoes_the_key(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, "wd-test-key")
    httpx_mock.add_response(url=_URL, json=_WATER)
    r = usgs_water_latest(min_lat=35.8, max_lat=36.2, min_lon=-84.6, max_lon=-84.0)
    assert r["_meta"]["quota"]["limit"] == 1000 and r["_meta"]["auth_present"] is True
    req = httpx_mock.get_requests()[0]
    assert req.headers["X-Api-Key"] == "wd-test-key" and "wd-test-key" not in str(req.url)
    assert "wd-test-key" not in str(r)


def test_site_query_rejected_key_and_quota(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, "bad")
    httpx_mock.add_response(
        url=f"{WATER_BASE_URL}/collections/latest-continuous/items?parameter_code=00065&limit=5&f=json&monitoring_location_id=USGS-03536320",
        status_code=403,
        json={"error": {"code": "API_KEY_INVALID"}},
    )
    r = usgs_water_latest(site="03536320", parameter_code="00065", limit=5)
    assert r["_meta"]["success"] is False and r["_meta"]["auth_present"] is False
    assert "403" in r["_meta"]["error"]
    r = usgs_water_latest()
    assert r["_meta"]["success"] is False and "bounding box" in r["_meta"]["error"]
    monkeypatch.delenv(KEY_NAME, raising=False)
    from env_data_mcp.sources.usgs_water import tools as t

    monkeypatch.setattr(t, "QUOTA_KEYLESS", (1, 3600))
    httpx_mock.add_response(url=_URL, json=_WATER)
    assert usgs_water_latest(min_lat=35.8, max_lat=36.2, min_lon=-84.6, max_lon=-84.0)["_meta"][
        "success"
    ]
    r = usgs_water_latest(min_lat=35.8, max_lat=36.2, min_lon=-84.6, max_lon=-84.0, limit=7)
    assert r["_meta"]["success"] is False and "quota" in r["_meta"]["error"]
