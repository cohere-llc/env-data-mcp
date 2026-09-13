"""Query logic for the CDS API v2 (https://cds.climate.copernicus.eu/how-to-api)."""

from __future__ import annotations

import io
import time
from typing import Any

import httpx

from ._constants import CDS_BASE_URL, DATASET, POLL_S, VARIABLES

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=120.0, headers={"Accept": "application/json"})
    return _client


def _headers(token: str) -> dict[str, str]:
    return {"PRIVATE-TOKEN": token}


def submit(*, token: str, variable: str, y0: int, y1: int, lat: float, lon: float) -> str:
    """POST the retrieve job; returns the job id.  ``area`` is a 0.25° box around the point so the
    result is one grid cell."""
    body = {
        "inputs": {
            "product_type": ["monthly_averaged_reanalysis"],
            "variable": [variable],
            "year": [str(y) for y in range(y0, y1 + 1)],
            "month": [f"{m:02d}" for m in range(1, 13)],
            "time": ["00:00"],
            "data_format": "netcdf",
            "download_format": "unarchived",
            "area": [lat + 0.125, lon - 0.125, lat - 0.125, lon + 0.125],  # N, W, S, E
        }
    }
    resp = _get_client().post(
        f"{CDS_BASE_URL}/processes/{DATASET}/execution", json=body, headers=_headers(token)
    )
    if resp.status_code in (401, 403):
        raise PermissionError(f"CDS rejected the token (HTTP {resp.status_code})")
    if resp.status_code == 404 and "licence" in resp.text.lower():
        raise PermissionError("CDS: the dataset licence must be accepted on the CDS website first")
    resp.raise_for_status()
    job_id = resp.json().get("jobID")
    if not job_id:
        raise RuntimeError("CDS returned no jobID")
    return str(job_id)


def status(*, token: str, job_id: str) -> str:
    resp = _get_client().get(f"{CDS_BASE_URL}/jobs/{job_id}", headers=_headers(token))
    if resp.status_code in (401, 403):
        raise PermissionError(f"CDS rejected the token (HTTP {resp.status_code})")
    resp.raise_for_status()
    return str(resp.json().get("status") or "unknown")


def wait(*, token: str, job_id: str, max_wait_s: float) -> str:
    """Poll until the job is finished or ``max_wait_s`` has passed; returns the last status."""
    deadline = time.monotonic() + max_wait_s
    st = status(token=token, job_id=job_id)
    while st in ("accepted", "running", "queued") and time.monotonic() < deadline:
        time.sleep(min(POLL_S, max(0.0, deadline - time.monotonic())))
        st = status(token=token, job_id=job_id)
    return st


def download(*, token: str, job_id: str) -> bytes:
    resp = _get_client().get(f"{CDS_BASE_URL}/jobs/{job_id}/results", headers=_headers(token))
    resp.raise_for_status()
    href = ((resp.json().get("asset") or {}).get("value") or {}).get("href")
    if not href:
        raise RuntimeError("CDS results carry no asset href")
    data = _get_client().get(href, headers=_headers(token), follow_redirects=True)
    data.raise_for_status()
    return data.content


def to_records(nc_bytes: bytes, variable: str, lat: float, lon: float) -> list[dict[str, Any]]:
    """The netCDF → one record per month at the nearest grid point: ``{time, value, units}``."""
    import numpy as np
    import xarray as xr

    short, units = VARIABLES[variable]
    with xr.open_dataset(io.BytesIO(nc_bytes), engine="h5netcdf") as ds:
        name = short if short in ds.data_vars else next(iter(ds.data_vars))
        da = ds[name]
        lat_name = "latitude" if "latitude" in da.dims else "lat"
        lon_name = "longitude" if "longitude" in da.dims else "lon"
        time_name = "valid_time" if "valid_time" in da.dims else "time"
        pt = da.sel({lat_name: lat, lon_name: lon}, method="nearest")
        if "expver" in pt.dims:
            pt = pt.isel(expver=0)
        times = pt[time_name].values
        vals = np.asarray(pt.values, dtype=float).reshape(-1)
        units = str(da.attrs.get("units") or units)
        out = []
        for t, v in zip(times, vals, strict=False):
            month = str(np.datetime_as_string(np.datetime64(t), unit="M"))
            out.append({"time": month, "value": None if np.isnan(v) else float(v), "units": units})
        return out
