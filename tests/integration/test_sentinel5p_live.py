"""Integration tests for the Sentinel-5P source adapter (live S3 access).

Marked ``@pytest.mark.integration`` — not run in CI unit-test jobs.
These tests read real S3 granule files from s3://meeo-s5p and require
network access plus significant bandwidth (each granule is ~100–160 MB).
Expect latency of 30–120 s per test depending on available bandwidth.
"""

from __future__ import annotations

import pytest
import s3fs

from env_data_mcp.sources.sentinel5p import sentinel5p_query

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

_BUCKET = "meeo-s5p"


@pytest.fixture(scope="module", autouse=True)
def _require_s5p_available():
    """Skip all tests if the meeo-s5p S3 bucket is not reachable."""
    try:
        fs = s3fs.S3FileSystem(anon=True)
        entries = fs.ls(f"{_BUCKET}/OFFL/", detail=False)
        if not entries:
            pytest.skip("meeo-s5p S3 bucket returned no products")
    except Exception as exc:
        pytest.skip(f"meeo-s5p S3 bucket not reachable: {exc}")


# ---------------------------------------------------------------------------
# Test parameters
# Yakima River sample date: 2019-08-19
# CO is the most commonly available product and least data-sparse.
# ---------------------------------------------------------------------------

_LAT = 46.2531882
_LON = -119.4768203
_DATE = "2019-08-19"
_PRODUCT = "CO"


@pytest.mark.integration
def test_sentinel5p_query_live_returns_success():
    result = sentinel5p_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        product=_PRODUCT,
    )
    assert result["_meta"]["success"] is True
    assert result["_meta"]["source"] == "sentinel5p"


@pytest.mark.integration
def test_sentinel5p_query_live_meta_fields():
    result = sentinel5p_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        product=_PRODUCT,
    )
    meta = result["_meta"]
    assert meta["auth_required"] is False
    assert meta["latency_s"] > 0
    assert meta["license"] != ""
    assert _PRODUCT in meta["variable_info"]


@pytest.mark.integration
def test_sentinel5p_query_live_record_schema():
    """If any granule covers the point, the record schema must be correct."""
    result = sentinel5p_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        product=_PRODUCT,
    )
    if result["data"]:
        rec = result["data"][0]
        assert "date" in rec
        assert "granule_id" in rec
        assert _PRODUCT in rec
        assert f"{_PRODUCT}_units" in rec
        # CO values are in mol m-2; typically 0.01–0.1 over land.
        assert 0 < rec[_PRODUCT] < 2.0


@pytest.mark.integration
def test_sentinel5p_query_live_invalid_product_graceful():
    result = sentinel5p_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        product="INVALID",
    )
    assert result["_meta"]["success"] is False
    assert result["data"] == []
