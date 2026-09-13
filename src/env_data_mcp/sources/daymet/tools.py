"""MCP tool functions for the Daymet single-pixel adapter."""

from __future__ import annotations

import datetime
import time
from typing import Any

from env_data_mcp.feeds import cache, cache_key, feed_meta
from env_data_mcp.helpers import parse_date
from env_data_mcp.models import PointInput, ToolResponse
from env_data_mcp.server import mcp

from ._constants import DEFAULT_VARIABLES, FIRST_YEAR, LICENSE_INFO, SOURCE, TTL_S, VARIABLES
from ._query import fetch_pixel, to_record


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return ToolResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def daymet_at(
    *,
    latitude: float,
    longitude: float,
    date: str,
    variables: list[str] | tuple[str, ...] = DEFAULT_VARIABLES,
) -> dict[str, Any]:
    """Daily weather at a 1 km Daymet pixel on one date (tmax, tmin, precipitation, …).

    Returns ``{data: [record], _meta}`` — one record ``{date, tmax_degC, tmin_degC, prcp_mm_day,
    elevation_m, …}`` (``None`` for a variable Daymet did not return).  Daymet covers North
    America from 1980 to the last complete calendar year; a date outside that answers with
    ``success: False``.  Cached for 24 h.

    ### Args
    * __latitude, longitude__: The point (WGS84).
    * __date__: ISO date ``YYYY-MM-DD`` (Daymet uses a 365-day year: Dec 31 of leap years is
          dropped by the source).
    * __variables__: Any of ``tmax tmin prcp srad vp swe dayl``. Default tmax, tmin, prcp.
    """
    variables = list(variables)
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "date": date,
        "variables": variables,
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
        pt = PointInput(latitude=latitude, longitude=longitude)
        d = parse_date(date)
        last_full_year = datetime.date.today().year - 1
        if d.year < FIRST_YEAR or d.year > last_full_year:
            raise ValueError(f"Daymet covers {FIRST_YEAR}–{last_full_year}; {date} is outside")
        bad = [v for v in variables if v not in VARIABLES]
        if bad or not variables:
            raise ValueError(f"variables must be among {', '.join(VARIABLES)}; got {bad}")
        payload = fetch_pixel(lat=pt.latitude, lon=pt.longitude, date=date, variables=variables)
        data = [to_record(payload, date, variables)]
        fetched_at = cache().set(key, data, TTL_S)
        return _validate(
            {
                "data": data,
                "_meta": feed_meta(
                    SOURCE,
                    query_params,
                    1,
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
