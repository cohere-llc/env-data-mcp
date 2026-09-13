"""MCP tool functions for the EIA adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import (
    cache,
    cache_key,
    feed_meta,
    governor,
    key_missing,
    quota_refused,
    read_key,
)
from env_data_mcp.models import PointInput, ToolResponse
from env_data_mcp.server import mcp

from ._constants import (
    KEY_NAME,
    LICENSE_INFO,
    QUOTA_LIMIT,
    QUOTA_WINDOW_S,
    SIGNUP_URL,
    SOURCE,
    TTL_S,
)
from ._query import fetch_generators, plants_near
from ._states import states_near


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return ToolResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def eia_plants_near(
    *,
    latitude: float,
    longitude: float,
    radius_km: float = 50.0,
    state: str | None = None,
) -> dict[str, Any]:
    """Operating power plants within ``radius_km`` of a point (EIA-860M via the EIA API v2).

    Needs ``EIA_API_KEY`` (free).  Returns ``{data: [record, …], _meta}`` — one record per plant:
    ``name``, ``plant_id``, ``lat``/``lon``, ``distance_km``, ``nameplate_capacity_mw`` (sum over
    generators), ``energy_sources`` and ``technologies`` (MW by code), ``period`` (the data
    month).  The generator list is pulled PER STATE — ``state`` when given, else every state
    whose bounding box the search circle touches (usually one or two; a point outside the US
    answers empty) — and each state's list is cached 24 h.  Without the key: ``auth_required:
    True, auth_present: False`` and empty data.

    ### Args
    * __latitude, longitude__: The point (WGS84).
    * __radius_km__: Search radius, 1–500 km. Default 50.
    * __state__: Two-letter state code to narrow the pull (recommended), e.g. ``TN``.
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": radius_km,
        "state": state,
        "key": KEY_NAME,
    }
    t0 = time.perf_counter()
    api_key = read_key(KEY_NAME)
    if not api_key:
        return _validate(
            key_missing(SOURCE, KEY_NAME, SIGNUP_URL, query_params, LICENSE_INFO, ttl_s=TTL_S)
        )
    gov = governor(SOURCE, QUOTA_LIMIT, QUOTA_WINDOW_S)
    try:
        pt = PointInput(latitude=latitude, longitude=longitude)
        if radius_km < 1 or radius_km > 500:
            raise ValueError("radius_km must be between 1 and 500")
        states = [state.upper()] if state else states_near(pt.latitude, pt.longitude, radius_km)
        rows: list[dict] = []
        fetched_at: str | None = None
        cached = True
        for st in states:
            list_key = cache_key(SOURCE, {"state": st})
            hit = cache().get(list_key)
            if hit is not None:
                st_rows, st_at = hit
            else:
                cached = False
                allowed, quota = gov.try_acquire()
                if not allowed:
                    return _validate(
                        quota_refused(
                            SOURCE,
                            query_params,
                            LICENSE_INFO,
                            quota,
                            ttl_s=TTL_S,
                            auth_required=True,
                        )
                    )
                st_rows = fetch_generators(api_key=api_key, state=st)
                st_at = cache().set(list_key, st_rows, TTL_S)
            rows.extend(st_rows)
            fetched_at = fetched_at or st_at
        query_params["states"] = states
        data = plants_near(rows, pt.latitude, pt.longitude, radius_km)
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
                    cached=cached,
                    quota=gov.snapshot(),
                    auth_required=True,
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
                    quota=gov.snapshot(),
                    auth_required=True,
                    success=False,
                    error=str(exc),
                ),
            }
        )
