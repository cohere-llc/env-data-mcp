"""Integration tests for the OpenAQ source adapter (live API).

Marked ``@pytest.mark.integration`` — not run in CI unit-test jobs.
These tests call the real OpenAQ v3 REST API.

Requires ``OPENAQ_API_KEY`` environment variable (free registration at
https://explore.openaq.org/register).  When the key is absent, all tests
are skipped gracefully.
"""

from __future__ import annotations

import os

import httpx
import pytest

from env_data_mcp.sources.openaq import openaq_query

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

_OPENAQ_HEALTH = "https://api.openaq.org/v3/locations"


@pytest.fixture(scope="module", autouse=True)
def _require_openaq_available():
    """Skip all tests if OPENAQ_API_KEY is absent or the API is unreachable."""
    api_key = os.environ.get("OPENAQ_API_KEY", "")
    if not api_key:
        pytest.skip("OPENAQ_API_KEY not set — skipping OpenAQ integration tests")
    try:
        r = httpx.get(
            _OPENAQ_HEALTH,
            params={"limit": 1},
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        if r.status_code >= 500:
            pytest.skip(f"OpenAQ API returned HTTP {r.status_code}")
        if r.status_code == 401:
            pytest.skip("OPENAQ_API_KEY is invalid (HTTP 401)")
    except Exception as exc:
        pytest.skip(f"OpenAQ API not reachable: {exc}")


# ---------------------------------------------------------------------------
# Test coordinates — Yakima River, Aug 2019
# ---------------------------------------------------------------------------

_LAT = 46.2531882
_LON = -119.4768203


@pytest.mark.integration
def test_openaq_query_live_success():
    """Success is defined as no exception and _meta.success = True.

    Data may be empty for sparse-coverage regions.
    """
    result = openaq_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=100.0,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=500,
    )
    assert result["_meta"]["success"] is True
    assert result["_meta"]["source"] == "openaq"


@pytest.mark.integration
def test_openaq_query_live_meta_fields():
    result = openaq_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=100.0,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=500,
    )
    meta = result["_meta"]
    assert meta["auth_required"] is True
    assert meta["auth_present"] is True
    assert meta["latency_s"] > 0
    assert meta["license"] != ""
    assert "capped" in meta


@pytest.mark.integration
def test_openaq_query_live_record_schema():
    result = openaq_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=100.0,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=500,
    )
    if result["data"]:
        rec = result["data"][0]
        assert "parameter" in rec
        assert "value" in rec
        assert "datetime" in rec
        assert rec["parameter"] in ["pm25", "pm10", "o3", "no2", "co"]


@pytest.mark.integration
def test_openaq_query_live_no_key_returns_auth_error(monkeypatch):
    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    result = openaq_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    assert result["_meta"]["success"] is False
    meta = result["_meta"]
    assert meta["auth_required"] is True
    assert meta["auth_present"] is False


# ---------------------------------------------------------------------------
# Schema stability assertions (Step 4.4)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_openaq_schema_record_fields():
    result = openaq_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=100.0,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=500,
    )
    for rec in result["data"]:
        assert "parameter" in rec, "OpenAQ: 'parameter' field missing — v3 schema may have changed"
        assert "value" in rec, "OpenAQ: 'value' field missing — upstream renamed it"
        assert "datetime" in rec, "OpenAQ: 'datetime' field missing"
        val = rec["value"]
        param = rec["parameter"]
        if param == "pm25":
            assert 0.0 <= val <= 2000.0, f"OpenAQ: pm25={val} outside plausible range"
        elif param == "co":
            assert 0.0 <= val <= 100.0, f"OpenAQ: co={val} outside plausible range (ppm)"


@pytest.mark.integration
def test_openaq_schema_variable_info_present():
    result = openaq_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=100.0,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=500,
    )
    meta = result["_meta"]
    assert "variable_info" in meta, "OpenAQ: _meta.variable_info missing"


@pytest.mark.integration
def test_openaq_schema_license_present():
    result = openaq_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=100.0,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=500,
    )
    meta = result["_meta"]
    assert meta["license"] != "", "OpenAQ: _meta.license is empty"
    assert meta["license_url"] != "", "OpenAQ: _meta.license_url is empty"
    assert "latitude" in meta["query_params"], "OpenAQ: query_params missing latitude"
    assert result["_meta"]["auth_required"] is True, "OpenAQ: should require an API key"
