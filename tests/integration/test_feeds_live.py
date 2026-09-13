"""Live smoke tests for the ``feeds`` family and the point accessors (one call each at the FRC).

Marked ``@pytest.mark.integration`` — not run in the CI unit-test jobs.  Keyed tools skip when
their key is absent; the gated tool (Open-Meteo) skips unless ``ENV_DATA_ALLOW_NC=1``.
The reference point is the Oak Ridge Field Research Center, Tennessee (35.9748, -84.277).
"""

from __future__ import annotations

import os

import pytest

from env_data_mcp.models import EventResponse, ToolResponse
from env_data_mcp.sources.arm import arm_nearest
from env_data_mcp.sources.daymet import daymet_at
from env_data_mcp.sources.eia import eia_plants_near
from env_data_mcp.sources.elevation_3dep import elevation_3dep
from env_data_mcp.sources.eonet import eonet_events
from env_data_mcp.sources.era5_cds import era5_monthly_at
from env_data_mcp.sources.macrostrat import macrostrat_at
from env_data_mcp.sources.nasa_firms import nasa_firms_fires
from env_data_mcp.sources.nws_alerts import nws_alerts_at
from env_data_mcp.sources.open_meteo import open_meteo_current
from env_data_mcp.sources.usgs_quakes import usgs_quakes_events
from env_data_mcp.sources.usgs_water import usgs_water_latest

FRC = {"latitude": 35.9748, "longitude": -84.277}
FRC_BOX = {"min_lat": 35.8, "max_lat": 36.2, "min_lon": -84.6, "max_lon": -84.0}

pytestmark = pytest.mark.integration


def _ok(r: dict) -> None:
    assert r["_meta"]["success"] is True, r["_meta"]["error"]
    assert r["_meta"]["ttl_s"] >= 0 and r["_meta"]["fetched_at"].endswith("Z")


@pytest.mark.smoke
def test_eonet_live():
    r = eonet_events(days=30, status="all", limit=50)
    EventResponse.model_validate(r)
    _ok(r)
    assert len(r["data"]) > 0 and all(rec["kind"] for rec in r["data"])


@pytest.mark.smoke
def test_usgs_quakes_live():
    r = usgs_quakes_events(days=7, min_magnitude=4.5, limit=50)
    EventResponse.model_validate(r)
    _ok(r)
    assert len(r["data"]) > 0 and r["data"][0]["magnitude"] >= 4.5


@pytest.mark.smoke
def test_nws_alerts_live():
    r = nws_alerts_at(**FRC)
    EventResponse.model_validate(r)
    _ok(r)  # an empty list is a valid answer (no alert at the FRC right now)


@pytest.mark.smoke
def test_usgs_water_live():
    r = usgs_water_latest(**FRC_BOX, parameter_code="00060", limit=5)
    EventResponse.model_validate(r)
    _ok(r)
    assert r["_meta"]["quota"]["limit"] in (50, 1000)


@pytest.mark.smoke
@pytest.mark.skipif(not os.environ.get("NASA_FIRMS_MAP_KEY"), reason="NASA_FIRMS_MAP_KEY not set")
def test_nasa_firms_live():
    r = nasa_firms_fires(min_lat=30.0, max_lat=40.0, min_lon=-125.0, max_lon=-115.0, days=2)
    EventResponse.model_validate(r)
    _ok(r)
    assert r["_meta"]["quota"]["used"] >= 1


@pytest.mark.smoke
@pytest.mark.skipif(os.environ.get("ENV_DATA_ALLOW_NC") != "1", reason="ENV_DATA_ALLOW_NC != 1")
def test_open_meteo_live():
    r = open_meteo_current(**FRC)
    EventResponse.model_validate(r)
    _ok(r)
    assert r["data"][0]["magnitude"] is not None


@pytest.mark.smoke
def test_daymet_live():
    r = daymet_at(**FRC, date="2024-07-01")
    ToolResponse.model_validate(r)
    _ok(r)
    assert r["data"][0]["tmax_degC"] > 20


@pytest.mark.smoke
def test_macrostrat_live():
    r = macrostrat_at(**FRC)
    ToolResponse.model_validate(r)
    _ok(r)
    assert "Shale" in (r["data"][0]["name"] or "") or r["data"][0]["b_age"] > 400


@pytest.mark.smoke
def test_elevation_3dep_live():
    r = elevation_3dep(**FRC)
    ToolResponse.model_validate(r)
    _ok(r)
    assert 250 < r["data"][0]["elevation_m"] < 350


@pytest.mark.smoke
def test_arm_nearest_live():
    r = arm_nearest(**FRC)
    ToolResponse.model_validate(r)
    _ok(r)
    assert r["data"][0]["code"] == "SGP"


@pytest.mark.smoke
@pytest.mark.skipif(not os.environ.get("EIA_API_KEY"), reason="EIA_API_KEY not set")
def test_eia_plants_live():
    r = eia_plants_near(**FRC, radius_km=50, state="TN")
    ToolResponse.model_validate(r)
    _ok(r)
    assert any("Kingston" in (p["name"] or "") for p in r["data"])


@pytest.mark.smoke
@pytest.mark.skipif(not os.environ.get("CDS_API_KEY"), reason="CDS_API_KEY not set")
def test_era5_live():
    r = era5_monthly_at(**FRC, start_year=2020, end_year=2020, max_wait_s=120)
    ToolResponse.model_validate(r)
    if r["_meta"]["success"]:
        assert len(r["data"]) == 12
    else:
        assert r["_meta"]["error"].startswith("queued:")
