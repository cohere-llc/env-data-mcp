"""Unit tests for env_data_mcp.sources.elevation_3dep (recorded EPQS JSON at the FRC)."""

from __future__ import annotations

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import ToolResponse
from env_data_mcp.sources.elevation_3dep._constants import EPQS_URL
from env_data_mcp.sources.elevation_3dep.tools import elevation_3dep

_EPQS = {
    "location": {"x": -84.277, "y": 35.9748, "spatialReference": {"wkid": 4326}},
    "locationId": 0,
    "value": "300.703552246",
    "rasterId": 74102,
    "resolution": 1,
}
_URL = f"{EPQS_URL}?x=-84.277&y=35.9748&units=Meters&wkid=4326"


@pytest.fixture(autouse=True)
def _fresh():
    feeds.cache().clear()
    yield
    feeds.cache().clear()


def test_elevation_record_and_cache(httpx_mock):
    httpx_mock.add_response(url=_URL, json=_EPQS)
    r = elevation_3dep(latitude=35.9748, longitude=-84.277)
    ToolResponse.model_validate(r)
    assert r["_meta"]["success"] is True and r["data"][0]["elevation_m"] == 300.704
    assert r["data"][0]["resolution_m"] == 1 and r["data"][0]["raster_id"] == 74102
    r2 = elevation_3dep(latitude=35.9748, longitude=-84.277)
    assert r2["_meta"]["cached"] is True and len(httpx_mock.get_requests()) == 1


def test_elevation_nodata_and_error(httpx_mock):
    httpx_mock.add_response(
        url=f"{EPQS_URL}?x=-30.0&y=0.0&units=Meters&wkid=4326",
        json={"value": "-1000000", "rasterId": 0, "resolution": 0},
    )
    r = elevation_3dep(latitude=0.0, longitude=-30.0)
    assert (
        r["_meta"]["success"] is True and r["data"] == []
    )  # outside coverage: empty, not an error
    httpx_mock.add_response(url=_URL, status_code=504)
    r = elevation_3dep(latitude=35.9748, longitude=-84.277)
    assert r["_meta"]["success"] is False and "504" in r["_meta"]["error"]
