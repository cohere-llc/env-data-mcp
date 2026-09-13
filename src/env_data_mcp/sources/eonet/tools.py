"""MCP tool functions for the NASA EONET adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import bbox_params, cache, cache_key, feed_meta
from env_data_mcp.models import BboxInput, EventResponse
from env_data_mcp.server import mcp

from ._constants import LICENSE_INFO, SOURCE, TTL_S
from ._query import fetch_events, to_records


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return EventResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def eonet_events(
    *,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lon: float | None = None,
    max_lon: float | None = None,
    days: int = 7,
    status: str = "open",
    category: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Natural events from NASA EONET v3 (wildfires, severe storms, volcanoes, floods, sea/lake ice,
    …).

    Returns ``{data: [EventRecord, …], _meta}``.  Each record carries the event's latest point
    (``lat``/``lon``),
    its track as a LineString or its polygon when EONET gives one, ``t_start`` (first geometry),
    ``t_end``
    (``closed`` date or null), ``magnitude``/``magnitude_unit`` when EONET reports one (e.g. storm
    wind in kts),
    and ``properties`` with the category and source links.  Results are cached for ``_meta.ttl_s``
    (30 min).

    ### Args
    * __min_lat, max_lat, min_lon, max_lon__: Optional bounding box (WGS84). All four or none.
    * __days__: Look back this many days (EONET ``days``). Default 7.
    * __status__: ``open`` (default), ``closed`` or ``all``.
    * __category__: Optional EONET category id (``wildfires``, ``severeStorms``, ``volcanoes``,
    ``floods``,
          ``seaLakeIce``, ``drought``, ``dustHaze``, ``landslides``, ``earthquakes``, ``snow``,
          ``tempExtremes``,
          ``manmade``, ``waterColor``).
    * __limit__: Maximum events to return (EONET ``limit``). Default 500.
    """
    bbox_vals = (min_lat, max_lat, min_lon, max_lon)
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "days": days,
        "status": status,
        "category": category,
        "limit": limit,
    }
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
        bbox: dict[str, float] | None = None
        if any(v is not None for v in bbox_vals):
            if any(v is None for v in bbox_vals):
                raise ValueError("min_lat, max_lat, min_lon and max_lon must all be given, or none")
            b = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)  # type: ignore[arg-type]
            bbox = bbox_params(b.min_lat, b.max_lat, b.min_lon, b.max_lon)
        if status not in ("open", "closed", "all"):
            raise ValueError("status must be one of open, closed, all")
        if days < 1 or days > 365:
            raise ValueError("days must be between 1 and 365")
        events = fetch_events(days=days, status=status, bbox=bbox, category=category, limit=limit)
        data = to_records(events)
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
