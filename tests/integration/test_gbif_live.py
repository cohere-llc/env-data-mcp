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
        limit=1000,
        max_runtime_s=9999,
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
        limit=1000,
        max_runtime_s=9999,
    )
    meta = result["_meta"]
    assert meta["auth_required"] is False
    assert meta["latency_s"] > 0
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
        limit=1000,
        max_runtime_s=9999,
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
        limit=1000,
        max_runtime_s=9999,
    )
    if result["data"]:
        rec = result["data"][0]
        assert "decimalLatitude" in rec, "GBIF Parquet: decimalLatitude column renamed or removed"
        assert "decimalLongitude" in rec, "GBIF Parquet: decimalLongitude column renamed or removed"
        assert "eventDate" in rec, "GBIF Parquet: eventDate column renamed or removed"
        assert "species" in rec or "scientificName" in rec, (
            "GBIF Parquet: neither 'species' nor 'scientificName' present — schema may have changed"
        )


# ---------------------------------------------------------------------------
# Schema stability assertions (Step 4.4)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_gbif_schema_lat_lon_physical_range():
    result = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=100,
        max_runtime_s=9999,
    )
    for rec in result["data"]:
        lat = rec.get("decimalLatitude")
        lon = rec.get("decimalLongitude")
        if lat is not None:
            assert -90.0 <= lat <= 90.0, (
                f"GBIF: decimalLatitude={lat} outside physical range — fill value or unit change?"
            )
        if lon is not None:
            assert -180.0 <= lon <= 180.0, f"GBIF: decimalLongitude={lon} outside physical range"


@pytest.mark.integration
def test_gbif_schema_variable_info_present():
    result = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=100,
        max_runtime_s=9999,
    )
    meta = result["_meta"]
    assert "variable_info" in meta, "GBIF: _meta.variable_info missing"
    vi = meta["variable_info"]
    assert "decimalLatitude" in vi, "GBIF: variable_info missing decimalLatitude entry"
    assert "units" in vi["decimalLatitude"], (
        "GBIF: variable_info['decimalLatitude'] missing 'units'"
    )


@pytest.mark.integration
def test_gbif_schema_license_present():
    result = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2010-01-01",
        end_date="2021-12-31",
        limit=100,
        max_runtime_s=9999,
    )
    meta = result["_meta"]
    assert meta["license_url"] != "", "GBIF: _meta.license_url is empty"
    assert "latitude" in meta["query_params"], "GBIF: query_params missing latitude"
