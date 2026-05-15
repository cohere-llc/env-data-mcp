"""Integration tests for NASA POWER — requires live S3/Zarr access.

Run with: uv run pytest tests/integration/ -m integration
"""

from __future__ import annotations

import pytest

from env_data_mcp.sources.nasa_power import (
    DEFAULT_VARIABLES,
    nasa_power_query,
)

pytestmark = pytest.mark.integration

# Yakima River WA: confirmed coverage in NASA POWER 1981–present
_LAT = 46.2531882
_LON = -119.4768203
_DATE = "2019-08-19"


@pytest.mark.integration
def test_nasa_power_query_live_returns_data():
    result = nasa_power_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        variables=["T2M", "PRECTOTCORR"],
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["date"] == _DATE


@pytest.mark.integration
def test_nasa_power_query_live_t2m_plausible():
    """T2M on 2019-08-19 at Yakima WA should be a summer temperature (> 5 °C)."""
    result = nasa_power_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        variables=["T2M"],
    )
    t2m = result["data"][0]["T2M"]
    assert 5.0 < t2m < 50.0, f"Implausible T2M={t2m}"


@pytest.mark.integration
def test_nasa_power_query_live_all_default_variables():
    result = nasa_power_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
    )
    assert result["_meta"]["success"] is True
    row = result["data"][0]
    found = [v for v in DEFAULT_VARIABLES if v in row]
    assert len(found) > 0, "No default variables returned"


@pytest.mark.integration
def test_nasa_power_query_live_multi_day():
    result = nasa_power_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2019-08-15",
        end_date="2019-08-21",
        variables=["T2M"],
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 7


@pytest.mark.integration
def test_nasa_power_query_live_meta_fields():
    result = nasa_power_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        variables=["T2M"],
    )
    meta = result["_meta"]
    assert meta["source"] == "nasa_power"
    assert meta["auth_required"] is False
    assert meta["latency_s"] > 0


# ---------------------------------------------------------------------------
# Schema stability assertions (Step 4.4)
# These fail immediately if NASA POWER renames a variable, changes units,
# or alters the _meta contract.  They are the primary upstream-change detector.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_nasa_power_schema_t2m_field_present():
    result = nasa_power_query(
        latitude=_LAT, longitude=_LON, start_date=_DATE, end_date=_DATE, variables=["T2M"]
    )
    row = result["data"][0]
    assert "T2M" in row, "NASA POWER: T2M variable missing — upstream may have renamed it"
    assert "T2M_units" in row, "NASA POWER: T2M_units field missing — units no longer echoed"


@pytest.mark.integration
def test_nasa_power_schema_t2m_units_celsius():
    result = nasa_power_query(
        latitude=_LAT, longitude=_LON, start_date=_DATE, end_date=_DATE, variables=["T2M"]
    )
    row = result["data"][0]
    assert row["T2M_units"] == "C", (
        f"NASA POWER: T2M units changed to {row['T2M_units']!r} — expected 'C' (Celsius)"
    )


@pytest.mark.integration
def test_nasa_power_schema_t2m_physical_range():
    result = nasa_power_query(
        latitude=_LAT, longitude=_LON, start_date=_DATE, end_date=_DATE, variables=["T2M"]
    )
    row = result["data"][0]
    t2m = row["T2M"]
    assert -90.0 <= t2m <= 60.0, (
        f"NASA POWER: T2M={t2m} outside physical range — fill value leaked or unit changed?"
    )


@pytest.mark.integration
def test_nasa_power_schema_prectotcorr_physical_range():
    result = nasa_power_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        variables=["PRECTOTCORR"],
    )
    row = result["data"][0]
    assert "PRECTOTCORR" in row, "NASA POWER: PRECTOTCORR variable missing"
    prec = row["PRECTOTCORR"]
    assert 0.0 <= prec <= 500.0, (
        f"NASA POWER: PRECTOTCORR={prec} outside physical range (0–500 mm/day)"
    )


@pytest.mark.integration
def test_nasa_power_schema_variable_info_present():
    result = nasa_power_query(
        latitude=_LAT, longitude=_LON, start_date=_DATE, end_date=_DATE, variables=["T2M"]
    )
    meta = result["_meta"]
    assert "variable_info" in meta, "NASA POWER: _meta.variable_info missing"
    vi = meta["variable_info"]
    assert "T2M" in vi, "NASA POWER: variable_info missing T2M entry"
    assert "units" in vi["T2M"], "NASA POWER: variable_info['T2M'] missing 'units' key"
    assert "description" in vi["T2M"], "NASA POWER: variable_info['T2M'] missing 'description' key"


@pytest.mark.integration
def test_nasa_power_schema_license_present():
    result = nasa_power_query(
        latitude=_LAT, longitude=_LON, start_date=_DATE, end_date=_DATE, variables=["T2M"]
    )
    meta = result["_meta"]
    assert meta["license"] != "", "NASA POWER: _meta.license is empty"
    assert meta["license_url"] != "", "NASA POWER: _meta.license_url is empty"
    assert "latitude" in meta["query_params"], "NASA POWER: query_params missing latitude"
