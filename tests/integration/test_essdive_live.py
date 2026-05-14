"""Live integration tests for the ESS-DIVE source adapter.

These tests make real HTTP requests to the ESS-DIVE API at
https://api.ess-dive.lbl.gov/packages.

They are skipped automatically when ESSDIVE_TOKEN is not set.

Run with:
    uv run pytest tests/integration/test_essdive_live.py -v
"""

from __future__ import annotations

import os

import httpx
import pytest

from env_data_mcp.sources.essdive import essdive_bbox_query, essdive_query

# ---------------------------------------------------------------------------
# Yakima River Valley — PNNL / WHONDRS study area; known ESS-DIVE datasets
# ---------------------------------------------------------------------------
_LAT = 46.2531882
_LON = -119.4768203
_RADIUS_KM = 50.0
_BBOX_MIN_LAT = 45.5
_BBOX_MAX_LAT = 47.0
_BBOX_MIN_LON = -120.5
_BBOX_MAX_LON = -118.5

_TOKEN = os.environ.get("ESSDIVE_TOKEN", "")

_ESS_DIVE_HEALTH_URL = "https://api.ess-dive.lbl.gov/packages?pageSize=1&isPublic=true"


@pytest.fixture(scope="session", autouse=True)
def _require_token_and_api():
    if not _TOKEN:
        pytest.skip("ESSDIVE_TOKEN not set — skipping live ESS-DIVE tests")
    # Check service availability
    try:
        r = httpx.get(
            _ESS_DIVE_HEALTH_URL,
            headers={"Authorization": f"Bearer {_TOKEN}", "Accept": "application/json"},
            timeout=10,
        )
        if r.status_code >= 500:
            pytest.skip(f"ESS-DIVE API returned HTTP {r.status_code} — service may be down")
    except Exception as exc:
        pytest.skip(f"ESS-DIVE API not reachable: {exc}")


@pytest.mark.integration
def test_essdive_query_yakima_returns_records():
    result = essdive_query(latitude=_LAT, longitude=_LON, radius_km=_RADIUS_KM)
    meta = result["_meta"]

    if not meta.get("success") and meta.get("auth_present"):
        pytest.skip(f"ESS-DIVE token rejected or expired: {meta.get('error')}")

    assert meta["success"] is True, f"Query failed: {meta.get('error')}"
    assert len(result["data"]) >= 1, (
        f"Expected ≥1 ESS-DIVE dataset within {_RADIUS_KM} km of Yakima River"
    )


@pytest.mark.integration
def test_essdive_query_record_schema():
    result = essdive_query(latitude=_LAT, longitude=_LON, radius_km=_RADIUS_KM)
    meta = result["_meta"]

    if not meta.get("success"):
        pytest.skip(f"Query failed: {meta.get('error')}")

    if not result["data"]:
        pytest.skip("No records returned — schema check skipped")

    for rec in result["data"]:
        assert "id" in rec, "Record missing 'id'"
        assert "doi" in rec, "Record missing 'doi'"
        assert "title" in rec, "Record missing 'title'"
        assert "license" in rec, "Record missing 'license'"
        assert "temporal_start" in rec, "Record missing 'temporal_start'"
        assert "keywords" in rec, "Record missing 'keywords'"
        assert "variables_measured" in rec, "Record missing 'variables_measured'"
        assert "url" in rec, "Record missing 'url'"
        assert isinstance(rec["keywords"], list), "'keywords' should be a list"
        assert isinstance(rec["variables_measured"], list), "'variables_measured' should be a list"


@pytest.mark.integration
def test_essdive_bbox_query_yakima():
    result = essdive_bbox_query(
        min_lat=_BBOX_MIN_LAT,
        max_lat=_BBOX_MAX_LAT,
        min_lon=_BBOX_MIN_LON,
        max_lon=_BBOX_MAX_LON,
    )
    meta = result["_meta"]

    if not meta.get("success") and meta.get("auth_present"):
        pytest.skip(f"ESS-DIVE token rejected or expired: {meta.get('error')}")

    assert meta["success"] is True, f"Bbox query failed: {meta.get('error')}"
    assert meta["query_params"]["min_lat"] == _BBOX_MIN_LAT
    assert meta["query_params"]["max_lon"] == _BBOX_MAX_LON


@pytest.mark.integration
def test_essdive_query_meta_fields():
    result = essdive_query(latitude=_LAT, longitude=_LON, radius_km=_RADIUS_KM)
    meta = result["_meta"]

    if not meta.get("success"):
        pytest.skip(f"Query failed: {meta.get('error')}")

    assert meta["source"] == "essdive"
    assert meta["auth_required"] is True
    assert meta["auth_present"] is True
    assert "ess-dive.lbl.gov" in meta["license_url"]
    assert meta["rows_returned"] == len(result["data"])
    assert meta["latency_s"] > 0
    assert "latitude" in meta["query_params"]
    assert meta["license"] != ""
