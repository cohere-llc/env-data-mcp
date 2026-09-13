"""MCP tool functions for the USGS earthquakes adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import bbox_params, cache, cache_key, feed_meta
from env_data_mcp.models import BboxInput, EventResponse
from env_data_mcp.server import mcp

from ._constants import LICENSE_INFO, SOURCE, TTL_S
from ._query import fetch_quakes, to_records


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return EventResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def usgs_quakes_events(
    *,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lon: float | None = None,
    max_lon: float | None = None,
    days: int = 1,
    min_magnitude: float = 2.5,
    limit: int = 1000,
) -> dict[str, Any]:
    """Earthquakes from the USGS FDSN event service (ANSS ComCat), last ``days`` days.

    Returns ``{data: [EventRecord, …], _meta}``: ``magnitude``/``magnitude_unit`` (e.g. ``ml``,
    ``mww``),
    ``severity`` = the PAGER alert level when issued (green/yellow/orange/red),
    ``properties.depth_km``,
    ``properties.tsunami``.  Cached for ``_meta.ttl_s`` (5 min).

    ### Args
    * __min_lat, max_lat, min_lon, max_lon__: Optional bounding box (WGS84). All four or none.
    * __days__: Look back this many days (1–30). Default 1.
    * __min_magnitude__: Minimum magnitude. Default 2.5.
    * __limit__: Maximum events (≤ 20000, the service's cap). Default 1000.
    """
    bbox_vals = (min_lat, max_lat, min_lon, max_lon)
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "days": days,
        "min_magnitude": min_magnitude,
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
        if days < 1 or days > 30:
            raise ValueError("days must be between 1 and 30")
        if limit < 1 or limit > 20000:
            raise ValueError("limit must be between 1 and 20000")
        features = fetch_quakes(bbox=bbox, days=days, min_magnitude=min_magnitude, limit=limit)
        data = to_records(features)
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
