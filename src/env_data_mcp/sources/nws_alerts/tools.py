"""MCP tool functions for the NWS alerts adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import cache, cache_key, feed_meta
from env_data_mcp.models import EventResponse, PointInput
from env_data_mcp.server import mcp

from ._constants import LICENSE_INFO, SOURCE, TTL_S
from ._query import fetch_alerts, to_records


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return EventResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def nws_alerts_at(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    area: str | None = None,
) -> dict[str, Any]:
    """Active NWS alerts (watches, warnings, advisories) at a point, or for a state / marine area.

    Returns ``{data: [EventRecord, …], _meta}``: ``kind = "alert"``, ``severity`` (Extreme /
    Severe /
    Moderate / Minor / Unknown), ``t_start`` (onset) and ``t_end`` (ends or expires), the alert
    polygon when the NWS issues one (zone-based alerts have none: ``lat``/``lon`` are then the
    query point and ``properties.location_is_query_point`` is true).  Cached for ``_meta.ttl_s``
    (10 min).  US only.

    ### Args
    * __latitude, longitude__: The point (WGS84). Give both, or ``area``.
    * __area__: A state or marine area code (``TN``, ``GM``, …) instead of a point.
    """
    query_params: dict[str, Any] = {"latitude": latitude, "longitude": longitude, "area": area}
    t0 = time.perf_counter()
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
                ),
            }
        )
    try:
        if latitude is not None or longitude is not None:
            if latitude is None or longitude is None:
                raise ValueError("latitude and longitude must both be given")
            pt = PointInput(latitude=latitude, longitude=longitude)
            latitude, longitude = pt.latitude, pt.longitude
        elif not area:
            raise ValueError("give a point (latitude, longitude) or an area code")
        collection = fetch_alerts(lat=latitude, lon=longitude, area=area)
        data = to_records(collection, latitude, longitude)
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
                    success=False,
                    error=str(exc),
                ),
            }
        )
