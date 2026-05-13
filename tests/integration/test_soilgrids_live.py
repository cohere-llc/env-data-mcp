"""Integration tests for SoilGrids — requires live ISRIC REST API access.

Run with: uv run pytest tests/integration/ -m integration
"""

from __future__ import annotations

import httpx
import pytest

from env_data_mcp.sources.soilgrids import _PROPERTIES, _SOILGRIDS_URL, soilgrids_query

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _require_soilgrids_api() -> None:
    """Skip every test in this module when the ISRIC REST API is unavailable.

    The API is in beta and ISRIC occasionally pauses it for maintenance.
    Rather than letting all tests fail with cryptic assertion errors, we
    make one inexpensive probe and skip gracefully.
    """
    try:
        r = httpx.get(
            _SOILGRIDS_URL,
            timeout=5,
            params={"lat": 0, "lon": 0, "property": "bdod", "depth": "0-5cm", "value": "mean"},
        )
        if r.status_code >= 500:
            pytest.skip(f"SoilGrids REST API returned HTTP {r.status_code} — service may be paused")
    except Exception as exc:
        pytest.skip(f"SoilGrids REST API not reachable: {exc}")


# Yakima Valley WA farmland: confirmed land point with SoilGrids coverage.
# Note: the river channel itself (46.2531882, -119.4768203) returns null values
# because SoilGrids excludes water bodies; this point is on adjacent cropland.
_LAT = 46.30
_LON = -119.50


@pytest.mark.integration
def test_soilgrids_query_live_returns_data():
    result = soilgrids_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is True
    assert isinstance(result["data"], dict)
    assert len(result["data"]) > 0


@pytest.mark.integration
def test_soilgrids_query_live_all_properties_present():
    result = soilgrids_query(latitude=_LAT, longitude=_LON)
    for prop in _PROPERTIES:
        assert prop in result["data"], f"Missing property: {prop}"
        assert f"{prop}_unit" in result["data"], f"Missing unit for: {prop}"


@pytest.mark.integration
def test_soilgrids_query_live_sand_plausible():
    """Sand at Yakima Valley (0–5 cm) should be a reasonable fraction."""
    result = soilgrids_query(latitude=_LAT, longitude=_LON)
    sand = result["data"].get("sand")
    assert sand is not None
    assert 0.0 < sand <= 100.0, f"Implausible sand={sand}"


@pytest.mark.integration
def test_soilgrids_query_live_phh2o_plausible():
    """Soil pH should be between 3 and 10."""
    result = soilgrids_query(latitude=_LAT, longitude=_LON)
    ph = result["data"].get("phh2o")
    assert ph is not None
    assert 3.0 <= ph <= 10.0, f"Implausible pH={ph}"


@pytest.mark.integration
def test_soilgrids_query_live_bdod_plausible():
    """Bulk density should be between 0.5 and 2.5 kg/dm³."""
    result = soilgrids_query(latitude=_LAT, longitude=_LON)
    bdod = result["data"].get("bdod")
    assert bdod is not None
    assert 0.5 <= bdod <= 2.5, f"Implausible bdod={bdod}"


@pytest.mark.integration
def test_soilgrids_query_live_meta_fields():
    result = soilgrids_query(latitude=_LAT, longitude=_LON)
    meta = result["_meta"]
    assert meta["source"] == "soilgrids"
    assert meta["auth_required"] is False
    assert meta["latency_s"] > 0
    assert meta["rows_returned"] == len(_PROPERTIES)
