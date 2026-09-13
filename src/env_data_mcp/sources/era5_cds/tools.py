"""MCP tool functions for the ERA5 (CDS) adapter — a queued job, honestly reported."""

from __future__ import annotations

import datetime
import time
from typing import Any

from env_data_mcp.feeds import cache, cache_key, feed_meta, key_missing, read_key
from env_data_mcp.models import PointInput, ToolResponse
from env_data_mcp.server import mcp

from ._constants import FIRST_YEAR, KEY_NAME, LICENSE_INFO, SIGNUP_URL, SOURCE, TTL_S, VARIABLES
from ._query import download, submit, to_records, wait


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return ToolResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def era5_monthly_at(
    *,
    latitude: float,
    longitude: float,
    variable: str = "2m_temperature",
    start_year: int = 1991,
    end_year: int = 2020,
    max_wait_s: float = 30.0,
    job_id: str | None = None,
) -> dict[str, Any]:
    """ERA5 monthly means at the nearest 0.25° grid point, via a CDS retrieve job.

    Needs ``CDS_API_KEY`` (a CDS Personal Access Token; the dataset licence must be accepted once
    on the CDS site).  THE QUEUE: the tool submits a job and waits up to ``max_wait_s``; if the job
    is still queued it answers ``success: False`` with ``_meta.job = {id, status}`` and an error
    beginning ``queued:`` — call again with ``job_id=<id>`` to keep waiting on that job.  When
    finished it returns one record per month ``{time: "YYYY-MM", value, units}`` and caches the
    series for 30 days.

    ### Args
    * __latitude, longitude__: The point (WGS84).
    * __variable__: A CDS variable name: ``2m_temperature`` (default), ``total_precipitation``,
          ``10m_u_component_of_wind``, ``10m_v_component_of_wind``, ``surface_pressure``,
          ``2m_dewpoint_temperature``, ``volumetric_soil_water_layer_1``, ``snow_depth``.
    * __start_year, end_year__: Inclusive years, 1940 → the current year. Default 1991–2020.
    * __max_wait_s__: How long to wait for the CDS queue this call (0–600 s). Default 30.
    * __job_id__: A job id from an earlier ``queued:`` answer, to resume waiting.
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "variable": variable,
        "start_year": start_year,
        "end_year": end_year,
        "max_wait_s": max_wait_s,
        "job_id": job_id,
        "key": KEY_NAME,
    }
    t0 = time.perf_counter()
    token = read_key(KEY_NAME)
    if not token:
        return _validate(
            key_missing(SOURCE, KEY_NAME, SIGNUP_URL, query_params, LICENSE_INFO, ttl_s=TTL_S)
        )
    series_key = cache_key(
        SOURCE,
        {
            "latitude": round(latitude, 3),
            "longitude": round(longitude, 3),
            "variable": variable,
            "y0": start_year,
            "y1": end_year,
        },
    )
    hit = cache().get(series_key)
    if hit is not None:
        data, fetched_at = hit
        return _validate(
            {
                "data": data,
                "_meta": feed_meta(
                    SOURCE,
                    query_params,
                    len(data),
                    time.perf_counter() - t0,
                    LICENSE_INFO,
                    ttl_s=TTL_S,
                    fetched_at=fetched_at,
                    cached=True,
                    auth_required=True,
                ),
            }
        )
    try:
        pt = PointInput(latitude=latitude, longitude=longitude)
        if variable not in VARIABLES:
            raise ValueError(f"variable must be one of {', '.join(VARIABLES)}")
        this_year = datetime.date.today().year
        if not (FIRST_YEAR <= start_year <= end_year <= this_year):
            raise ValueError(
                f"years must satisfy {FIRST_YEAR} ≤ start_year ≤ end_year ≤ {this_year}"
            )
        if max_wait_s < 0 or max_wait_s > 600:
            raise ValueError("max_wait_s must be between 0 and 600")
        jid = job_id or submit(
            token=token,
            variable=variable,
            y0=start_year,
            y1=end_year,
            lat=pt.latitude,
            lon=pt.longitude,
        )
        st = wait(token=token, job_id=jid, max_wait_s=max_wait_s)
        if st in ("accepted", "running", "queued"):
            meta = feed_meta(
                SOURCE,
                query_params,
                0,
                time.perf_counter() - t0,
                LICENSE_INFO,
                ttl_s=TTL_S,
                auth_required=True,
                success=False,
                error=(
                    f"queued: CDS job {jid} is {st} after {max_wait_s:.0f} s — call again with "
                    f"job_id='{jid}' to keep waiting (the CDS queue can take minutes)"
                ),
            )
            meta["job"] = {"id": jid, "status": st}
            return _validate({"data": [], "_meta": meta})
        if st != "successful":
            raise RuntimeError(f"CDS job {jid} ended with status {st}")
        data = to_records(download(token=token, job_id=jid), variable, pt.latitude, pt.longitude)
        fetched_at = cache().set(series_key, data, TTL_S)
        meta = feed_meta(
            SOURCE,
            query_params,
            len(data),
            time.perf_counter() - t0,
            LICENSE_INFO,
            ttl_s=TTL_S,
            fetched_at=fetched_at,
            auth_required=True,
        )
        meta["job"] = {"id": jid, "status": st}
        return _validate({"data": data, "_meta": meta})
    except PermissionError as exc:
        return _validate(
            {
                "data": [],
                "_meta": feed_meta(
                    SOURCE,
                    query_params,
                    0,
                    time.perf_counter() - t0,
                    LICENSE_INFO,
                    ttl_s=TTL_S,
                    auth_required=True,
                    auth_present=False,
                    success=False,
                    error=f"{exc} — check {KEY_NAME}",
                ),
            }
        )
    except Exception as exc:
        return _validate(
            {
                "data": [],
                "_meta": feed_meta(
                    SOURCE,
                    query_params,
                    0,
                    time.perf_counter() - t0,
                    LICENSE_INFO,
                    ttl_s=TTL_S,
                    auth_required=True,
                    success=False,
                    error=str(exc),
                ),
            }
        )
