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
