"""Unit tests for env_data_mcp.sources.nasa_firms (keyed; CSV in the documented column layout)."""

from __future__ import annotations

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import EventResponse
from env_data_mcp.sources.nasa_firms._constants import FIRMS_BASE_URL, KEY_NAME
from env_data_mcp.sources.nasa_firms.tools import nasa_firms_fires

_KEY = "test-map-key-0000"
# the area API's CSV layout (VIIRS NRT), two detections
_CSV = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,"
    "version,bright_ti5,frp,daynight\n"
    "35.9612,-84.2811,331.2,0.39,0.36,2026-09-12,0715,N,VIIRS,n,2.0NRT,294.1,4.7,N\n"
    "36.0101,-84.3002,367.0,0.41,0.37,2026-09-12,1832,N,VIIRS,h,2.0NRT,301.3,12.9,D\n"
)
_URL = f"{FIRMS_BASE_URL}/{_KEY}/VIIRS_SNPP_NRT/-84.5,35.8,-84.0,36.2/1"


@pytest.fixture(autouse=True)
def _fresh():
    feeds.cache().clear()
    feeds.reset_governors()
    yield
    feeds.cache().clear()
    feeds.reset_governors()


def test_no_key_is_a_response_with_auth_flags(monkeypatch):
    monkeypatch.delenv(KEY_NAME, raising=False)
    r = nasa_firms_fires(min_lat=35.8, max_lat=36.2, min_lon=-84.5, max_lon=-84.0)
    EventResponse.model_validate(r)
    assert r["data"] == [] and r["_meta"]["auth_required"] is True
    assert r["_meta"]["auth_present"] is False and r["_meta"]["success"] is False
    assert KEY_NAME in r["_meta"]["error"] and r["_meta"]["query_params"]["key"] == KEY_NAME


def test_fires_records_quota_and_cache(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, _KEY)
    httpx_mock.add_response(url=_URL, text=_CSV)
    r = nasa_firms_fires(min_lat=35.8, max_lat=36.2, min_lon=-84.5, max_lon=-84.0)
    EventResponse.model_validate(r)
    assert r["_meta"]["success"] is True and len(r["data"]) == 2
    a, b = r["data"]
    assert a["kind"] == "fire" and a["t_start"] == "2026-09-12T07:15:00Z"
    assert a["magnitude"] == 4.7 and a["magnitude_unit"] == "MW" and a["severity"] == "nominal"
    assert b["severity"] == "high" and b["properties"]["daynight"] == "D"
    assert r["_meta"]["quota"]["limit"] == 5000 and r["_meta"]["quota"]["used"] == 1
    # the key never appears in the response
    assert _KEY not in str(r)
    # cached: no second HTTP call, the quota is not charged again
    r2 = nasa_firms_fires(min_lat=35.8, max_lat=36.2, min_lon=-84.5, max_lon=-84.0)
    assert r2["_meta"]["cached"] is True and r2["_meta"]["quota"]["used"] == 1
    assert len(httpx_mock.get_requests()) == 1


def test_quota_refuses_at_the_limit(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, _KEY)
    from env_data_mcp.sources.nasa_firms import tools as t

    monkeypatch.setattr(t, "QUOTA_LIMIT", 2)
    httpx_mock.add_response(
        url=f"{FIRMS_BASE_URL}/{_KEY}/VIIRS_SNPP_NRT/-84.5,35.8,-84.0,36.2/1", text=_CSV
    )
    httpx_mock.add_response(
        url=f"{FIRMS_BASE_URL}/{_KEY}/VIIRS_SNPP_NRT/-84.5,35.8,-84.0,36.2/2", text=_CSV
    )
    assert nasa_firms_fires(min_lat=35.8, max_lat=36.2, min_lon=-84.5, max_lon=-84.0, days=1)[
        "_meta"
    ]["success"]
    assert nasa_firms_fires(min_lat=35.8, max_lat=36.2, min_lon=-84.5, max_lon=-84.0, days=2)[
        "_meta"
    ]["success"]
    r3 = nasa_firms_fires(min_lat=35.8, max_lat=36.2, min_lon=-84.5, max_lon=-84.0, days=3)
    assert r3["_meta"]["success"] is False and "quota" in r3["_meta"]["error"]
    assert r3["_meta"]["quota"]["remaining"] == 0 and len(httpx_mock.get_requests()) == 2


def test_invalid_key_and_bad_inputs(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, _KEY)
    httpx_mock.add_response(url=_URL, text="Invalid MAP_KEY.\n")
    r = nasa_firms_fires(min_lat=35.8, max_lat=36.2, min_lon=-84.5, max_lon=-84.0)
    assert r["_meta"]["success"] is False and r["_meta"]["auth_present"] is False
    assert "rejected" in r["_meta"]["error"]
    r = nasa_firms_fires(min_lat=35.8, max_lat=36.2, min_lon=-84.5, max_lon=-84.0, days=30)
    assert r["_meta"]["success"] is False and "days" in r["_meta"]["error"]
    r = nasa_firms_fires(min_lat=35.8, max_lat=36.2, min_lon=-84.5, max_lon=-84.0, product="nope")
    assert r["_meta"]["success"] is False and "product" in r["_meta"]["error"]
