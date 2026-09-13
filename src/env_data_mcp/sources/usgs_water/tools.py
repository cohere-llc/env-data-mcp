"""MCP tool functions for the USGS Water Data adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import (
    bbox_params,
    cache,
    cache_key,
    feed_meta,
    governor,
    quota_refused,
    read_key,
)
from env_data_mcp.models import BboxInput, EventResponse
from env_data_mcp.server import mcp

from ._constants import KEY_NAME, LICENSE_INFO, QUOTA_KEYED, QUOTA_KEYLESS, SOURCE, TTL_S
from ._query import fetch_latest, to_records


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return EventResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def usgs_water_latest(
    *,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lon: float | None = None,
    max_lon: float | None = None,
    site: str | None = None,
    parameter_code: str = "00060",
    limit: int = 100,
) -> dict[str, Any]:
    """Latest instantaneous values from USGS monitoring locations (discharge, gage height, …).

    Keyless at 50 requests/hour; with ``USGS_WATERDATA_API_KEY`` (free) 1,000/hour — the tier in
    force is in ``_meta.quota``.  Returns ``{data: [EventRecord, …], _meta}``: one record per
    location with ``magnitude`` = the latest value, ``magnitude_unit``, ``t_start`` = its time (a
    location whose latest value is years old is reported as is — check ``t_start``).  Cached for
    ``_meta.ttl_s`` (15 min).  US only.

    ### Args
    * __min_lat, max_lat, min_lon, max_lon__: Bounding box (WGS84). All four, or ``site``.
    * __site__: A monitoring location id (``03536320`` or ``USGS-03536320``) instead of a box.
    * __parameter_code__: NWIS parameter code. Default ``00060`` (discharge). Others: ``00065``
          gage height, ``00010`` water temperature, ``00300`` dissolved oxygen, ``00400`` pH,
          ``00095`` specific conductance, ``63680`` turbidity, ``72019`` depth to water.
    * __limit__: Maximum locations (1–1000). Default 100.
    """
    bbox_vals = (min_lat, max_lat, min_lon, max_lon)
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "site": site,
        "parameter_code": parameter_code,
        "limit": limit,
    }
    t0 = time.perf_counter()
    api_key = read_key(KEY_NAME)
    limit_q, window_q = QUOTA_KEYED if api_key else QUOTA_KEYLESS
    gov = governor(SOURCE, limit_q, window_q)
    key = cache_key(SOURCE, query_params)
    hit = cache().get(key)
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
                    quota=gov.snapshot(),
                    auth_present=bool(api_key),
                ),
            }
        )
    try:
        bbox: dict[str, float] | None = None
        if any(v is not None for v in bbox_vals):
            if any(v is None for v in bbox_vals):
                raise ValueError("min_lat, max_lat, min_lon and max_lon must all be given, or none")
            b = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)  # type: ignore[arg-type]
            bbox = bbox_params(b.min_lat, b.max_lat, b.min_lon, b.max_lon)
        if bbox is None and not site:
            raise ValueError("give a bounding box or a site id")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        allowed, quota = gov.try_acquire()
        if not allowed:
            return _validate(
                quota_refused(
                    SOURCE,
                    query_params,
                    LICENSE_INFO,
                    quota,
                    ttl_s=TTL_S,
                    auth_present=bool(api_key),
                )
            )
        collection = fetch_latest(
            bbox=bbox, site=site, parameter_code=parameter_code, limit=limit, api_key=api_key
        )
        data = to_records(collection, parameter_code)
        fetched_at = cache().set(key, data, TTL_S)
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
                    quota=quota,
                    auth_present=bool(api_key),
                ),
            }
        )
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
                    quota=gov.snapshot(),
                    auth_required=False,  # an OPTIONAL key was present and rejected
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
                    quota=gov.snapshot(),
                    auth_present=bool(api_key),
                    success=False,
                    error=str(exc),
                ),
            }
        )
