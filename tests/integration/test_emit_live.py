"""Live integration tests for the EMIT L2B Minerals source adapter.

These tests make real HTTP requests to NASA CMR and LP DAAC OPeNDAP.
They are skipped automatically when EARTHDATA_TOKEN is not set or is expired.

EMIT launched August 2022; queries before that date will return no data.

Run with:
    uv run pytest tests/integration/test_emit_live.py -v
"""

from __future__ import annotations

import os

import pytest

from env_data_mcp.sources.emit import emit_query

# ---------------------------------------------------------------------------
# Yakima River Valley, Washington — arid/semi-arid land with detectable
# mineral signatures.  Using late 2022 to ensure EMIT is operational.
# ---------------------------------------------------------------------------
_LAT = 46.2531882
_LON = -119.4768203
_START = "2022-09-01"
_END = "2022-11-30"

_TOKEN = os.environ.get("EARTHDATA_TOKEN", "")


@pytest.fixture(scope="session", autouse=True)
def _require_token():
    if not _TOKEN:
        pytest.skip("EARTHDATA_TOKEN not set — skipping live EMIT tests")


@pytest.mark.integration
def test_emit_query_returns_successfully():
    """Query completes without exception; success flag is True."""
    result = emit_query(latitude=_LAT, longitude=_LON, start_date=_START, end_date=_END)
    meta = result["_meta"]

    if not meta.get("success") and not meta.get("auth_present"):
        pytest.skip(f"EarthData token rejected or expired: {meta.get('error')}")

    assert meta["success"] is True, f"Query failed: {meta.get('error')}"


@pytest.mark.integration
def test_emit_query_record_schema():
    """If data is returned, each record must have required fields."""
    result = emit_query(latitude=_LAT, longitude=_LON, start_date=_START, end_date=_END)
    meta = result["_meta"]

    if not meta.get("success") and not meta.get("auth_present"):
        pytest.skip(f"EarthData token rejected or expired: {meta.get('error')}")

    if not result["data"]:
        pytest.skip("No EMIT granules cover this location+period — sparse coverage expected")

    required_fields = {
        "mineral_name",
        "abundance",
        "latitude",
        "longitude",
        "acquisition_date",
        "granule_id",
    }
    for rec in result["data"]:
        missing = required_fields - set(rec.keys())
        assert not missing, f"Record missing fields: {missing}"
        assert 0.0 < rec["abundance"] <= 1.0, f"Abundance out of range: {rec['abundance']}"
        assert isinstance(rec["mineral_name"], str) and rec["mineral_name"]


@pytest.mark.integration
def test_emit_query_meta_fields():
    result = emit_query(latitude=_LAT, longitude=_LON, start_date=_START, end_date=_END)
    meta = result["_meta"]

    if not meta.get("success") and not meta.get("auth_present"):
        pytest.skip(f"EarthData token rejected or expired: {meta.get('error')}")

    assert meta["source"] == "emit"
    assert meta["auth_required"] is True
    assert meta["auth_present"] is True
    assert meta["latency_s"] > 0
    assert meta["license"] != ""
