"""Unit tests for env_data_mcp.sources.eia (keyed; response in the documented API v2 shape)."""

from __future__ import annotations

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import ToolResponse
from env_data_mcp.sources.eia._constants import EIA_BASE_URL, KEY_NAME, ROUTE
from env_data_mcp.sources.eia.tools import eia_plants_near

_KEY = "eia-test-key"
# two plants near the FRC (Kingston: two coal units; Bull Run: one), the latest period first
_PAGE = {
    "response": {
        "total": "4",
        "data": [
            {
                "period": "2026-06",
                "plantid": 3403,
                "plantName": "Kingston",
                "generatorid": "1",
                "stateid": "TN",
                "latitude": "35.8992",
                "longitude": "-84.5194",
                "energy_source_code": "BIT",
                "technology": "Conventional Steam Coal",
                "status": "OP",
                "nameplate-capacity-mw": "175",
            },
            {
                "period": "2026-06",
                "plantid": 3403,
                "plantName": "Kingston",
                "generatorid": "2",
                "stateid": "TN",
                "latitude": "35.8992",
                "longitude": "-84.5194",
                "energy_source_code": "BIT",
                "technology": "Conventional Steam Coal",
                "status": "OP",
                "nameplate-capacity-mw": "175",
            },
            {
                "period": "2026-06",
                "plantid": 3396,
                "plantName": "Bull Run",
                "generatorid": "1",
                "stateid": "TN",
                "latitude": "36.0214",
                "longitude": "-84.1569",
                "energy_source_code": "BIT",
                "technology": "Conventional Steam Coal",
                "status": "OP",
                "nameplate-capacity-mw": "950",
            },
            {
                "period": "2026-05",
                "plantid": 3403,
                "plantName": "Kingston",
                "generatorid": "1",
                "stateid": "TN",
                "latitude": "35.8992",
                "longitude": "-84.5194",
                "energy_source_code": "BIT",
                "technology": "Conventional Steam Coal",
                "status": "OP",
                "nameplate-capacity-mw": "175",
            },
        ],
    }
}


def _url(state: str = "TN") -> str:
    return (
        f"{EIA_BASE_URL}/{ROUTE}?frequency=monthly&data%5B0%5D=nameplate-capacity-mw"
        "&data%5B1%5D=latitude&data%5B2%5D=longitude&sort%5B0%5D%5Bcolumn%5D=period"
        f"&sort%5B0%5D%5Bdirection%5D=desc&length=5000&offset=0&facets%5Bstateid%5D%5B%5D={state}"
    )


@pytest.fixture(autouse=True)
def _fresh():
    feeds.cache().clear()
    feeds.reset_governors()
    yield
    feeds.cache().clear()
    feeds.reset_governors()


def test_no_key(monkeypatch):
    monkeypatch.delenv(KEY_NAME, raising=False)
    r = eia_plants_near(latitude=35.9748, longitude=-84.277, state="TN")
    ToolResponse.model_validate(r)
    assert (
        r["data"] == [] and r["_meta"]["auth_present"] is False and KEY_NAME in r["_meta"]["error"]
    )


def test_plants_near_aggregates_generators_and_uses_header(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, _KEY)
    httpx_mock.add_response(url=_url(), json=_PAGE)
    r = eia_plants_near(latitude=35.9748, longitude=-84.277, radius_km=40, state="TN")
    ToolResponse.model_validate(r)
    assert r["_meta"]["success"] is True and [p["name"] for p in r["data"]] == [
        "Bull Run",
        "Kingston",
    ]
    kingston = r["data"][1]
    assert kingston["nameplate_capacity_mw"] == 350.0 and kingston["n_generators"] == 2
    assert kingston["energy_sources"] == {"BIT": 350.0} and kingston["period"] == "2026-06"
    assert 20 < kingston["distance_km"] < 25
    req = httpx_mock.get_requests()[0]
    assert req.headers["X-Api-Key"] == _KEY and _KEY not in str(req.url) and _KEY not in str(r)
    # the state list is cached: a second radius query makes no HTTP call
    r2 = eia_plants_near(latitude=35.9748, longitude=-84.277, radius_km=15, state="TN")
    assert r2["_meta"]["cached"] is True and [p["name"] for p in r2["data"]] == ["Bull Run"]
    assert len(httpx_mock.get_requests()) == 1


def test_rejected_key_and_validation(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, _KEY)
    httpx_mock.add_response(
        url=_url(), status_code=403, json={"error": {"code": "API_KEY_INVALID"}}
    )
    r = eia_plants_near(latitude=35.9748, longitude=-84.277, state="TN")
    assert r["_meta"]["success"] is False and r["_meta"]["auth_present"] is False
    r = eia_plants_near(latitude=35.9748, longitude=-84.277, radius_km=9999, state="TN")
    assert r["_meta"]["success"] is False and "radius_km" in r["_meta"]["error"]
