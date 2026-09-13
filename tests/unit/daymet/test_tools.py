"""Unit tests for env_data_mcp.sources.daymet (recorded single-pixel JSON at the FRC)."""

from __future__ import annotations

import pytest

from env_data_mcp import feeds
from env_data_mcp.models import ToolResponse
from env_data_mcp.sources.daymet._constants import DAYMET_BASE_URL
from env_data_mcp.sources.daymet.tools import daymet_at

# Recorded 2026-09-12 (start=end=2024-07-01, vars=tmax,tmin,prcp, format=json), trimmed
_PIXEL = {
    "loc": [35.9748, -84.277],
    "Tile": "11208",
    "Elevation": "324 m",
    "LCC": [1354929.94, -564747.14],
    "citation": "Thornton et al. 2022 …",
    "data": {
        "year": [2024.0],
        "yday": [183.0],
        "prcp (mm/day)": [0.0],
        "tmax (deg c)": [30.579999923706055],
        "tmin (deg c)": [20.100000381469727],
    },
}
_URL = (
    f"{DAYMET_BASE_URL}?lat=35.9748&lon=-84.277&vars=tmax%2Ctmin%2Cprcp"
    "&start=2024-07-01&end=2024-07-01&format=json"
)


@pytest.fixture(autouse=True)
def _fresh():
    feeds.cache().clear()
    yield
    feeds.cache().clear()


def test_daymet_record_and_cache(httpx_mock):
    httpx_mock.add_response(url=_URL, json=_PIXEL)
    r = daymet_at(latitude=35.9748, longitude=-84.277, date="2024-07-01")
    ToolResponse.model_validate(r)
    assert r["_meta"]["success"] is True and r["_meta"]["ttl_s"] == 86400.0
    rec = r["data"][0]
    assert rec["date"] == "2024-07-01" and rec["tmax_degC"] == pytest.approx(30.58, abs=0.01)
    assert rec["tmin_degC"] == pytest.approx(20.1, abs=0.01) and rec["prcp_mm_day"] == 0.0
    assert rec["elevation_m"] == 324.0 and rec["tile"] == "11208"
    r2 = daymet_at(latitude=35.9748, longitude=-84.277, date="2024-07-01")
    assert r2["_meta"]["cached"] is True and len(httpx_mock.get_requests()) == 1


def test_daymet_validation():
    r = daymet_at(latitude=35.9748, longitude=-84.277, date="1975-01-01")
    assert r["_meta"]["success"] is False and "covers" in r["_meta"]["error"]
    r = daymet_at(latitude=35.9748, longitude=-84.277, date="2024-07-01", variables=["nope"])
    assert r["_meta"]["success"] is False and "variables" in r["_meta"]["error"]
    r = daymet_at(latitude=35.9748, longitude=-84.277, date="not-a-date")
    assert r["_meta"]["success"] is False and "Invalid date" in r["_meta"]["error"]
