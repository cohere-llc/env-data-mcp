"""MCP tool functions for the ARM adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import feed_meta
from env_data_mcp.models import PointInput, ToolResponse
from env_data_mcp.server import mcp

from ._constants import LICENSE_INFO, SOURCE, TTL_S
from ._query import nearest


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return ToolResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def arm_nearest(*, latitude: float, longitude: float, n: int = 1) -> dict[str, Any]:
    """The nearest DOE ARM fixed observatory to a point, with its distance (km).

    Returns ``{data: [record, …], _meta}`` — ``{code, name, lat, lon, distance_km, url, since}``
    for the ``n`` nearest of SGP (Oklahoma), NSA (Alaska), ENA (Azores).  No network call; ARM's
    measurement data need a free ARM account (see ``_meta.license_url``).

    ### Args
    * __latitude, longitude__: The point (WGS84).
    * __n__: How many sites (1–3). Default 1.
    """
    query_params: dict[str, Any] = {"latitude": latitude, "longitude": longitude, "n": n}
    t0 = time.perf_counter()
    try:
        pt = PointInput(latitude=latitude, longitude=longitude)
        if n < 1 or n > 3:
            raise ValueError("n must be between 1 and 3")
        data = nearest(pt.latitude, pt.longitude, n)
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
