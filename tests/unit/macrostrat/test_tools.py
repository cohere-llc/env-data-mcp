"""Unit tests for env_data_mcp.sources.macrostrat (recorded response at the FRC, trimmed)."""

from __future__ import annotations

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import ToolResponse
from env_data_mcp.sources.macrostrat._constants import MACROSTRAT_BASE_URL
from env_data_mcp.sources.macrostrat.tools import macrostrat_at

# Recorded 2026-09-12 (geologic_units/map?lat=35.9748&lng=-84.277), trimmed to the fields read
_UNITS = {
    "success": {
        "v": 2,
        "license": "CC-BY 4.0",
        "data": [
            {
                "map_id": 2929121,
                "source_id": 133,
                "name": "Nolichucky Shale, and Maryville, Rogersville, and Rutledge Formations",
                "strat_name": "Nolichucky Shale; Maryville Formation; Rogersville Formation",
                "lith": "Major:{shale}, Minor:{limestone}, Incidental:{dolostone, siltstone}",
                "descrip": "(Cn) Nolichucky Shale - Pastel-colored flaky clay shale …",
                "comments": "East-Central sheet Original map source: Greene and Wolfe, 2000",
                "t_int_name": "Cambrian",
                "b_int_name": "Cambrian",
                "best_int_name": "Cambrian",
                "color": "#7FA056",
                "t_age": 499.95,
                "b_age": 511,
            },
            {
                "map_id": 1,
                "source_id": 2,
                "name": "coarser map unit",
                "strat_name": "",
                "lith": "",
                "b_age": 541,
                "t_age": 485,
            },
        ],
    }
}
_URL = f"{MACROSTRAT_BASE_URL}/geologic_units/map?lat=35.9748&lng=-84.277"


@pytest.fixture(autouse=True)
def _fresh():
    feeds.cache().clear()
    yield
    feeds.cache().clear()


def test_macrostrat_record(httpx_mock):
    httpx_mock.add_response(url=_URL, json=_UNITS)
    r = macrostrat_at(latitude=35.9748, longitude=-84.277)
    ToolResponse.model_validate(r)
    assert r["_meta"]["success"] is True and r["_meta"]["license"] == "CC BY 4.0"
    rec = r["data"][0]
    assert rec["name"].startswith("Nolichucky Shale") and rec["age_ma"] == [511, 499.95]
    assert rec["best_int_name"] == "Cambrian" and "shale" in rec["lith"]
    assert len(rec["units"]) == 2 and rec["api_license"] == "CC-BY 4.0"


def test_macrostrat_empty_is_success_and_errors_are_responses(httpx_mock):
    httpx_mock.add_response(
        url=f"{MACROSTRAT_BASE_URL}/geologic_units/map?lat=0.0&lng=-30.0",
        json={"success": {"v": 2, "license": "CC-BY 4.0", "data": []}},
    )
    r = macrostrat_at(latitude=0.0, longitude=-30.0)
    assert r["_meta"]["success"] is True and r["data"] == []
    httpx_mock.add_response(url=_URL, status_code=502)
    r = macrostrat_at(latitude=35.9748, longitude=-84.277)
    assert r["_meta"]["success"] is False and "502" in r["_meta"]["error"]
