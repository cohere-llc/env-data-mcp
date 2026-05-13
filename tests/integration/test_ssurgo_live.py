"""Integration tests for SSURGO — requires live USDA SDA HTTP access.

Run with: uv run pytest tests/integration/ -m integration
"""

from __future__ import annotations

import pytest

from env_data_mcp.sources.ssurgo import _NO_COVERAGE_MSG, ssurgo_query

pytestmark = pytest.mark.integration

# Yakima River WA: confirmed US location with SSURGO coverage
_US_LAT = 46.2531882
_US_LON = -119.4768203

# Paris, France: outside SSURGO coverage
_NON_US_LAT = 48.8566
_NON_US_LON = 2.3522


@pytest.mark.integration
def test_ssurgo_query_live_us_point_returns_data():
    result = ssurgo_query(latitude=_US_LAT, longitude=_US_LON)
    assert result["_meta"]["success"] is True
    assert len(result["data"]) > 0


@pytest.mark.integration
def test_ssurgo_query_live_us_point_has_expected_columns():
    result = ssurgo_query(latitude=_US_LAT, longitude=_US_LON)
    row = result["data"][0]
    for col in ("mukey", "muname", "compname", "hzdepb_r", "sandtotal_r"):
        assert col in row, f"Missing column: {col}"


@pytest.mark.integration
def test_ssurgo_query_live_us_point_sand_plausible():
    """Sand fraction for Yakima Valley soils should be > 0."""
    result = ssurgo_query(latitude=_US_LAT, longitude=_US_LON)
    sand_vals = [
        float(r["sandtotal_r"]) for r in result["data"] if r.get("sandtotal_r") is not None
    ]
    assert len(sand_vals) > 0
    assert all(0.0 <= s <= 100.0 for s in sand_vals), f"Implausible sand values: {sand_vals}"


@pytest.mark.integration
def test_ssurgo_query_live_non_us_graceful_empty():
    result = ssurgo_query(latitude=_NON_US_LAT, longitude=_NON_US_LON)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


@pytest.mark.integration
def test_ssurgo_query_live_meta_fields():
    result = ssurgo_query(latitude=_US_LAT, longitude=_US_LON)
    meta = result["_meta"]
    assert meta["source"] == "ssurgo"
    assert meta["auth_required"] is False
    assert meta["latency_s"] > 0
