"""MCP tool functions for the NASA FIRMS adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import (
    bbox_params,
    cache,
    cache_key,
    feed_meta,
    governor,
    key_missing,
    quota_refused,
    read_key,
)
from env_data_mcp.models import BboxInput, EventResponse
from env_data_mcp.server import mcp

from ._constants import (
    DEFAULT_PRODUCT,
    KEY_NAME,
    LICENSE_INFO,
    PRODUCTS,
    QUOTA_LIMIT,
    QUOTA_WINDOW_S,
    SIGNUP_URL,
    SOURCE,
    TTL_S,
)
from ._query import fetch_csv, to_records


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return EventResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def nasa_firms_fires(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    days: int = 1,
    product: str = DEFAULT_PRODUCT,
    date: str | None = None,
) -> dict[str, Any]:
    """Active fire detections from NASA FIRMS for a bounding box, last ``days`` days.

    Needs ``NASA_FIRMS_MAP_KEY`` (free).  Returns ``{data: [EventRecord, …], _meta}``, one record
    per detection (``magnitude`` = fire radiative power in MW, ``severity`` = confidence class),
    ``_meta.quota`` (5,000 transactions per 10 min, counted here) and ``_meta.ttl_s`` (30 min).
    Without the key: ``auth_required: True, auth_present: False`` and empty data — never an
    exception.

    ### Args
    * __min_lat, max_lat, min_lon, max_lon__: Bounding box, WGS84 (FIRMS accepts up to 10° × 10°
          per call comfortably; larger boxes return more rows and count once against the quota).
    * __days__: 1–10 days (FIRMS' cap for the area API). Default 1.
    * __product__: ``VIIRS_SNPP_NRT`` (default), ``VIIRS_NOAA20_NRT``, ``VIIRS_NOAA21_NRT``,
          ``MODIS_NRT`` or ``LANDSAT_NRT``.
    * __date__: Optional start date ``YYYY-MM-DD`` (the window then runs ``days`` from that date).
    """
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "days": days,
        "product": product,
        "date": date,
        "key": KEY_NAME,  # the NAME of the credential, never its value
    }
    t0 = time.perf_counter()
    map_key = read_key(KEY_NAME)
    if not map_key:
        return _validate(
            key_missing(SOURCE, KEY_NAME, SIGNUP_URL, query_params, LICENSE_INFO, ttl_s=TTL_S)
        )
    gov = governor(SOURCE, QUOTA_LIMIT, QUOTA_WINDOW_S)
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
                    auth_required=True,
                ),
            }
        )
    try:
        b = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)
        if days < 1 or days > 10:
            raise ValueError("days must be between 1 and 10")
        if product not in PRODUCTS:
            raise ValueError(f"product must be one of {', '.join(PRODUCTS)}")
        allowed, quota = gov.try_acquire()
        if not allowed:
            return _validate(
                quota_refused(
                    SOURCE, query_params, LICENSE_INFO, quota, ttl_s=TTL_S, auth_required=True
                )
            )
        text = fetch_csv(
            map_key=map_key,
            product=product,
            bbox=bbox_params(b.min_lat, b.max_lat, b.min_lon, b.max_lon),
            days=days,
            date=date,
        )
        data = to_records(text, product)
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
