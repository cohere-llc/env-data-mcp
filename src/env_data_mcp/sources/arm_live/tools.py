"""ARM Live tool: the files ARM holds for a datastream over a date range."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.feeds import cache, cache_key, feed_meta, key_missing, read_key
from env_data_mcp.models import ToolResponse
from env_data_mcp.server import mcp

from ._constants import ARMLIVE_BASE_URL, KEY_NAME, LICENSE_INFO, SIGNUP_URL, SOURCE, TTL_S
from ._query import fetch_files, to_records


def _validate(response: dict[str, Any]) -> dict[str, Any]:
    return ToolResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def arm_live_files(
    *,
    datastream: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    """The files ARM holds for ``datastream`` between ``start`` and ``end`` (ARM Live data service).

    Needs ``ARM_LIVE_TOKEN`` (free ARM account; the value is ``user:token``). Returns
    ``{data: [{file, datastream, date, download}, …], _meta}``. The credential travels in the query
    string (ARM offers no header form) — every request log line is redacted. Without the
    credential: ``auth_required: True, auth_present: False`` and empty data.

    ### Args
    * __datastream__: An ARM datastream name, e.g. ``sgpmetE13.b1``.
    * __start, end__: Dates ``YYYY-MM-DD`` (inclusive).
    """
    query_params: dict[str, Any] = {
        "datastream": datastream,
        "start": start,
        "end": end,
        "key": KEY_NAME,
    }
    t0 = time.perf_counter()
    credential = read_key(KEY_NAME)
    if not credential:
        return _validate(
            key_missing(SOURCE, KEY_NAME, SIGNUP_URL, query_params, LICENSE_INFO, ttl_s=TTL_S)
        )
    try:
        if not datastream or len(datastream) > 64 or "/" in datastream:
            raise ValueError("datastream must be an ARM datastream name, e.g. sgpmetE13.b1")
        for d in (start, end):
            time.strptime(d, "%Y-%m-%d")
        # the cache key hashes the parameters, never the credential (KEYS.md §4b c)
        ck = cache_key(SOURCE, {"ds": datastream, "start": start, "end": end})
        hit = cache().get(ck)
        if hit is not None:
            data, fetched_at = hit
            cached = True
        else:
            body = fetch_files(credential=credential, datastream=datastream, start=start, end=end)
            data = to_records(body, datastream)
            fetched_at = cache().set(ck, data, TTL_S)
            cached = False
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
                    auth_required=True,
                    success=False,
                    error=str(exc),
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
                    auth_required=True,
                    success=False,
                    error=f"{exc.__class__.__name__}: {exc}",
                ),
            }
        )


__all__ = ["arm_live_files", "ARMLIVE_BASE_URL"]
