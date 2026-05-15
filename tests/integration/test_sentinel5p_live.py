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


@pytest.fixture(scope="module")
def _s5p_result():
    """Run the standard CO query once per module; all tests below share it."""
    return sentinel5p_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        product=_PRODUCT,
    )


@pytest.mark.integration
def test_sentinel5p_query_live_returns_success(_s5p_result):
    assert _s5p_result["_meta"]["success"] is True
    assert _s5p_result["_meta"]["source"] == "sentinel5p"


@pytest.mark.integration
def test_sentinel5p_query_live_meta_fields(_s5p_result):
    meta = _s5p_result["_meta"]
    assert meta["auth_required"] is False
    assert meta["latency_s"] > 0
    assert meta["license"] != ""
    assert _PRODUCT in meta["variable_info"]


@pytest.mark.integration
def test_sentinel5p_query_live_record_schema(_s5p_result):
    """If any granule covers the point, the record schema must be correct."""
    if _s5p_result["data"]:
        rec = _s5p_result["data"][0]
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


# ---------------------------------------------------------------------------
# Schema stability assertions (Step 4.4)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sentinel5p_schema_co_physical_range(_s5p_result):
    """CO column density over land is typically 0.01–0.1 mol m⁻²."""
    for rec in _s5p_result["data"]:
        val = rec.get(_PRODUCT)
        if val is not None:
            assert 0.0 < val < 2.0, (
                f"Sentinel-5P CO={val} outside expected range — fill value leaked or unit changed?"
            )


@pytest.mark.integration
def test_sentinel5p_schema_variable_info_present(_s5p_result):
    meta = _s5p_result["_meta"]
    assert "variable_info" in meta, "Sentinel-5P: _meta.variable_info missing"
    vi = meta["variable_info"]
    assert _PRODUCT in vi, f"Sentinel-5P: variable_info missing {_PRODUCT} entry"
    assert "units" in vi[_PRODUCT], f"Sentinel-5P: variable_info[{_PRODUCT!r}] missing 'units'"
    assert "description" in vi[_PRODUCT], (
        f"Sentinel-5P: variable_info[{_PRODUCT!r}] missing 'description'"
    )


@pytest.mark.integration
def test_sentinel5p_schema_license_present(_s5p_result):
    meta = _s5p_result["_meta"]
    assert meta["license"] != "", "Sentinel-5P: _meta.license is empty"
    assert meta["license_url"] != "", "Sentinel-5P: _meta.license_url is empty"
    assert "latitude" in meta["query_params"], "Sentinel-5P: query_params missing latitude"


@pytest.mark.integration
def test_sentinel5p_schema_record_units_field(_s5p_result):
    """Each record must include a *_units field matching the product name."""
    for rec in _s5p_result["data"]:
        units_key = f"{_PRODUCT}_units"
        assert units_key in rec, (
            f"Sentinel-5P: record missing '{units_key}' — upstream may have dropped units field"
        )
