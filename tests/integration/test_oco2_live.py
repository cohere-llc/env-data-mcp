"""Live integration tests for the OCO-2 source adapter.

These tests make real HTTP requests to NASA CMR and GES DISC.
They are skipped automatically when EARTHDATA_TOKEN is not set or is expired.

Run with:
    uv run pytest tests/integration/test_oco2_live.py -v
"""

from __future__ import annotations

import os

import pytest

from env_data_mcp.sources.oco2 import oco2_query

# ---------------------------------------------------------------------------
# Yakima River Valley — semi-arid agricultural land in Washington state
# Clear skies common in August → good OCO-2 retrievals
# ---------------------------------------------------------------------------
_LAT = 46.2531882
_LON = -119.4768203
_START = "2019-08-01"
_END = "2019-08-31"

_TOKEN = os.environ.get("EARTHDATA_TOKEN", "")


@pytest.fixture(scope="session", autouse=True)
def _require_token():
    if not _TOKEN:
        pytest.skip("EARTHDATA_TOKEN not set — skipping live OCO-2 tests")


@pytest.mark.integration
def test_oco2_query_yakima_returns_records():
    result = oco2_query(latitude=_LAT, longitude=_LON, start_date=_START, end_date=_END)
    meta = result["_meta"]

    # If the token was rejected, skip gracefully rather than fail
    if not meta.get("success") and not meta.get("auth_present"):
        pytest.skip(f"EarthData token rejected or expired: {meta.get('error')}")

    assert meta["success"] is True, f"Query failed: {meta.get('error')}"
    assert len(result["data"]) >= 1, "Expected at least one XCO2 record for August 2019"


@pytest.mark.integration
def test_oco2_query_yakima_xco2_plausible_range():
    result = oco2_query(latitude=_LAT, longitude=_LON, start_date=_START, end_date=_END)
    meta = result["_meta"]

    if not meta.get("success") and not meta.get("auth_present"):
        pytest.skip(f"EarthData token rejected or expired: {meta.get('error')}")

    if not result["data"]:
        pytest.skip("No records returned — possibly sparse coverage for this period")

    for rec in result["data"]:
        xco2 = rec["xco2"]
        assert 390.0 <= xco2 <= 430.0, (
            f"XCO2 value {xco2:.1f} ppm outside expected range 390–430 ppm "
            f"for August 2019 (granule {rec['granule_id']})"
        )


@pytest.mark.integration
def test_oco2_query_meta_fields():
    result = oco2_query(latitude=_LAT, longitude=_LON, start_date=_START, end_date=_END)
    meta = result["_meta"]

    if not meta.get("success") and not meta.get("auth_present"):
        pytest.skip(f"EarthData token rejected or expired: {meta.get('error')}")

    assert meta["source"] == "oco2"
    assert meta["auth_required"] is True
    assert meta["auth_present"] is True
    assert meta["latency_s"] > 0
    assert meta["license"] != ""
