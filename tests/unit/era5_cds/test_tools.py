"""Unit tests for env_data_mcp.sources.era5_cds (keyed; the CDS job lifecycle, mocked)."""

from __future__ import annotations

import io

import numpy as np
import pytest
import xarray as xr

from env_data_mcp import feeds
from env_data_mcp.models import ToolResponse
from env_data_mcp.sources.era5_cds import _query
from env_data_mcp.sources.era5_cds._constants import CDS_BASE_URL, DATASET, KEY_NAME
from env_data_mcp.sources.era5_cds.tools import era5_monthly_at

_TOKEN = "cds-test-token"
_EXEC = f"{CDS_BASE_URL}/processes/{DATASET}/execution"
_JOB = "abc-123"


def _nc_bytes() -> bytes:
    """A tiny ERA5-shaped netCDF: t2m over 2 × 2 grid points × 3 months."""
    times = np.array(["2020-01-01", "2020-02-01", "2020-03-01"], dtype="datetime64[ns]")
    lats = np.array([36.0, 35.75])
    lons = np.array([-84.5, -84.25])
    t2m = np.zeros((3, 2, 2)) + 280.0
    t2m[:, 0, 1] = [275.15, 276.15, 281.15]  # nearest to the FRC (35.9748, -84.277): 36.0, -84.25
    ds = xr.Dataset(
        {"t2m": (("valid_time", "latitude", "longitude"), t2m, {"units": "K"})},
        coords={"valid_time": times, "latitude": lats, "longitude": lons},
    )
    buf = io.BytesIO()
    ds.to_netcdf(buf, engine="h5netcdf")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    feeds.cache().clear()
    monkeypatch.setattr(_query, "POLL_S", 0.0)
    yield
    feeds.cache().clear()


def test_no_key(monkeypatch):
    monkeypatch.delenv(KEY_NAME, raising=False)
    r = era5_monthly_at(latitude=35.9748, longitude=-84.277)
    ToolResponse.model_validate(r)
    assert (
        r["data"] == [] and r["_meta"]["auth_present"] is False and KEY_NAME in r["_meta"]["error"]
    )


def test_job_completes_and_series_is_sampled_at_the_nearest_point(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, _TOKEN)
    httpx_mock.add_response(
        url=_EXEC, method="POST", status_code=201, json={"jobID": _JOB, "status": "accepted"}
    )
    httpx_mock.add_response(url=f"{CDS_BASE_URL}/jobs/{_JOB}", json={"status": "running"})
    httpx_mock.add_response(url=f"{CDS_BASE_URL}/jobs/{_JOB}", json={"status": "successful"})
    httpx_mock.add_response(
        url=f"{CDS_BASE_URL}/jobs/{_JOB}/results",
        json={"asset": {"value": {"href": "https://object-store.example/era5.nc"}}},
    )
    httpx_mock.add_response(url="https://object-store.example/era5.nc", content=_nc_bytes())
    r = era5_monthly_at(
        latitude=35.9748, longitude=-84.277, start_year=2020, end_year=2020, max_wait_s=5
    )
    ToolResponse.model_validate(r)
    assert r["_meta"]["success"] is True and r["_meta"]["job"] == {
        "id": _JOB,
        "status": "successful",
    }
    assert [rec["time"] for rec in r["data"]] == ["2020-01", "2020-02", "2020-03"]
    assert r["data"][0]["value"] == 275.15 and r["data"][0]["units"] == "K"
    post = httpx_mock.get_requests(method="POST")[0]
    assert post.headers["PRIVATE-TOKEN"] == _TOKEN and _TOKEN not in str(post.url)
    body = post.read().decode()
    assert '"variable":["2m_temperature"]' in body and '"year":["2020"]' in body
    assert _TOKEN not in str(r)
    # cached for the same series
    r2 = era5_monthly_at(latitude=35.9748, longitude=-84.277, start_year=2020, end_year=2020)
    assert r2["_meta"]["cached"] is True


def test_queued_answer_and_resume_with_job_id(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, _TOKEN)
    httpx_mock.add_response(
        url=_EXEC, method="POST", status_code=201, json={"jobID": _JOB, "status": "accepted"}
    )
    httpx_mock.add_response(
        url=f"{CDS_BASE_URL}/jobs/{_JOB}", json={"status": "accepted"}, is_reusable=True
    )
    r = era5_monthly_at(
        latitude=35.9748, longitude=-84.277, start_year=2020, end_year=2020, max_wait_s=0
    )
    assert r["_meta"]["success"] is False and r["_meta"]["error"].startswith("queued:")
    assert r["_meta"]["job"]["id"] == _JOB and _JOB in r["_meta"]["error"]
    # resuming with job_id does NOT submit again
    r = era5_monthly_at(
        latitude=35.9748,
        longitude=-84.277,
        start_year=2020,
        end_year=2020,
        max_wait_s=0,
        job_id=_JOB,
    )
    assert (
        r["_meta"]["job"]["status"] == "accepted"
        and len(httpx_mock.get_requests(method="POST")) == 1
    )


def test_rejected_token_and_validation(httpx_mock, monkeypatch):
    monkeypatch.setenv(KEY_NAME, _TOKEN)
    httpx_mock.add_response(url=_EXEC, method="POST", status_code=401, json={"detail": "bad token"})
    r = era5_monthly_at(latitude=35.9748, longitude=-84.277, start_year=2020, end_year=2020)
    assert r["_meta"]["success"] is False and r["_meta"]["auth_present"] is False
    r = era5_monthly_at(latitude=35.9748, longitude=-84.277, variable="nope")
    assert r["_meta"]["success"] is False and "variable" in r["_meta"]["error"]
    r = era5_monthly_at(latitude=35.9748, longitude=-84.277, start_year=1900, end_year=1950)
    assert r["_meta"]["success"] is False and "years" in r["_meta"]["error"]
