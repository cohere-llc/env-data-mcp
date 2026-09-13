"""Unit tests for env_data_mcp.sources.arm (static site table, no network)."""

from __future__ import annotations

import pytest

from env_data_mcp.models import ToolResponse
from env_data_mcp.sources.arm.tools import arm_nearest


def test_nearest_site_from_the_frc():
    r = arm_nearest(latitude=35.9748, longitude=-84.277)
    ToolResponse.model_validate(r)
    assert r["_meta"]["success"] is True and len(r["data"]) == 1
    site = r["data"][0]
    assert site["code"] == "SGP" and 1180 < site["distance_km"] < 1230
    assert site["url"].startswith("https://www.arm.gov/") and "arm.gov" in r["_meta"]["license_url"]


def test_three_sites_ordered_and_validation():
    r = arm_nearest(latitude=70.0, longitude=-150.0, n=3)
    codes = [s["code"] for s in r["data"]]
    assert codes == ["NSA", "SGP", "ENA"] and r["data"][0]["distance_km"] < 400
    r = arm_nearest(latitude=70.0, longitude=-150.0, n=9)
    assert r["_meta"]["success"] is False and "n must" in r["_meta"]["error"]
    r = arm_nearest(latitude=95.0, longitude=0.0)
    assert r["_meta"]["success"] is False and r["data"] == []


@pytest.mark.parametrize("n", [1, 2, 3])
def test_n_sites(n):
    assert len(arm_nearest(latitude=0.0, longitude=0.0, n=n)["data"]) == n
