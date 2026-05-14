"""Integration tests for the GBIF source adapter (live S3 access).

Marked ``@pytest.mark.integration`` — not run in CI unit-test jobs.
These tests call the real GBIF Open Data S3 bucket and require network access.
"""

from __future__ import annotations

import pytest
import s3fs

from env_data_mcp.sources.gbif import gbif_occurrences

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

_GBIF_BUCKET = "gbif-open-data-us-east-1"


@pytest.fixture(scope="module", autouse=True)
def _require_gbif_available():
    """Skip all tests if the GBIF S3 bucket is not reachable."""
    try:
        fs = s3fs.S3FileSystem(anon=True)
        entries = fs.ls(f"{_GBIF_BUCKET}/occurrence/", detail=False)
        if not entries:
            pytest.skip("GBIF S3 bucket returned no partitions")
    except Exception as exc:
        pytest.skip(f"GBIF S3 bucket not reachable: {exc}")


# ---------------------------------------------------------------------------
# Test coordinates — Yakima Valley, WA (known biodiversity hotspot)
# ---------------------------------------------------------------------------

_LAT = 46.2531882
_LON = -119.4768203


@pytest.mark.integration
def test_gbif_occurrences_live_returns_success():
    result = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
    )
    assert result["_meta"]["success"] is True
    assert result["_meta"]["source"] == "gbif"


@pytest.mark.integration
def test_gbif_occurrences_live_meta_fields():
    result = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
    )
    meta = result["_meta"]
    assert meta["auth_required"] is False
    assert meta["latency_s"] > 0
    assert "partition_date" in meta
    assert "capped" in meta
    assert meta["license_url"] != ""


@pytest.mark.integration
def test_gbif_occurrences_live_license_populated():
    result = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
    )
    # License must be non-empty whether records exist or not.
    assert result["_meta"]["license"] != ""


@pytest.mark.integration
def test_gbif_occurrences_live_record_schema():
    result = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
    )
    if result["data"]:
        rec = result["data"][0]
        assert "decimalLatitude" in rec
        assert "decimalLongitude" in rec
        assert "eventDate" in rec
