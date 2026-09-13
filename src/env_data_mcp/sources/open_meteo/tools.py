"""MCP tool functions for the Open-Meteo adapter (gated: non-commercial terms)."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import cache, cache_key, feed_meta, nc_allowed
from env_data_mcp.models import EventResponse, PointInput
from env_data_mcp.server import mcp

from ._constants import LICENSE_INFO, NC_ENV, SOURCE, TTL_S
from ._query import fetch_forecast, to_record


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return EventResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def open_meteo_current(
    *, latitude: float, longitude: float, forecast_days: int = 7
) -> dict[str, Any]:
    """Current weather and a daily forecast at a point from Open-Meteo (non-commercial terms).

    GATED: Open-Meteo's free API is for non-commercial use.  Unless the operator has set
    ``ENV_DATA_ALLOW_NC=1`` the tool returns empty data with ``_meta.error = "gated: non-commercial
    terms …"`` and ``success: False`` — never an exception.  When allowed it returns one EventRecord
    (``kind = "weather"``, ``magnitude`` = 2 m temperature) with ``properties.current`` and
    ``properties.forecast_daily``.  Cached for ``_meta.ttl_s`` (15 min).

    ### Args
    * __latitude, longitude__: The point (WGS84).
    * __forecast_days__: 1–16 daily forecast days. Default 7.
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "forecast_days": forecast_days,
    }
    t0 = time.perf_counter()
    if not nc_allowed():
        return _validate(
            {
                "data": [],
                "_meta": feed_meta(
                    SOURCE,
                    query_params,
                    0,
                    0.0,
                    LICENSE_INFO,
                    ttl_s=TTL_S,
                    success=False,
                    error=(
                        "gated: non-commercial terms — Open-Meteo's free API is licensed for "
                        f"non-commercial use only; set {NC_ENV}=1 to attest non-commercial use "
                        "of this deployment"
                    ),
                ),
            }
        )
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
        pt = PointInput(latitude=latitude, longitude=longitude)
        if forecast_days < 1 or forecast_days > 16:
            raise ValueError("forecast_days must be between 1 and 16")
        payload = fetch_forecast(lat=pt.latitude, lon=pt.longitude, forecast_days=forecast_days)
        data = [to_record(payload, pt.latitude, pt.longitude)]
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
