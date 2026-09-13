"""MCP tool functions for the Macrostrat adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import cache, cache_key, feed_meta
from env_data_mcp.models import PointInput, ToolResponse
from env_data_mcp.server import mcp

from ._constants import LICENSE_INFO, SOURCE, TTL_S
from ._query import fetch_units, to_record


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return ToolResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def macrostrat_at(*, latitude: float, longitude: float) -> dict[str, Any]:
    """The mapped geologic unit under a point: name, lithology, age (Ma), interval (Macrostrat).

    Returns ``{data: [record], _meta}`` — one record for the finest-scale unit (``name``,
    ``strat_name``, ``lith``, ``b_age``/``t_age`` in Ma, ``b_int_name``/``t_int_name``,
    ``descrip``) with every unit at the point in ``units``; ``data`` is empty (``success: True``)
    where no map covers the point (open ocean).  Cached for 7 days.

    ### Args
    * __latitude, longitude__: The point (WGS84).
    """
    query_params: dict[str, Any] = {"latitude": latitude, "longitude": longitude}
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
        pt = PointInput(latitude=latitude, longitude=longitude)
        rec = to_record(fetch_units(lat=pt.latitude, lon=pt.longitude))
        data = [rec] if rec else []
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
