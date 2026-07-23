"""On-disk variable cache for the GBIF adapter.

The MCP server serves ``gbif_*_available_variables`` from the committed
:file:`variables.json` shipped alongside this module, never from the network.
The live-fetch path is used only by the refresh script and its drift
integration test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from env_data_mcp.helpers import get_by_path, load_json_cache
from env_data_mcp.scripts.refresh_variable_caches import VariableCacheEntry, register

from .constants import _QUERY_RESULT_SCHEMAS, _QueryType

_VARIABLES_PATH = Path(__file__).parent / "variables.json"

# Session-level cache populated lazily on the first _get_variable_info call.
_VARIABLE_INFO_CACHE: dict[_QueryType, dict[str, dict[str, str]]] = {}


# ---------------------------------------------------------------------------
# Live discovery (used by the refresh script only)
# ---------------------------------------------------------------------------


def _fetch_variable_info_live(query_type: _QueryType) -> dict[str, dict[str, str]]:
    """Discover variables for *query_type* by fetching the GBIF OpenAPI schema."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(_QUERY_RESULT_SCHEMAS[query_type]["url"])
        resp.raise_for_status()
        info = get_by_path(resp.json(), _QUERY_RESULT_SCHEMAS[query_type]["path"], {})
    return {
        key: {"description": val.get("description", key) or key, "units": ""}
        for key, val in info.items()
    }


def _fetch_all_variable_info_live() -> dict[str, dict[str, dict[str, str]]]:
    """Fetch variable info for every GBIF query type.

    Returns a JSON-serialisable ``{query_type_value: {variable: {...}}}`` dict
    suitable for writing to :data:`_VARIABLES_PATH`.
    """
    return {qt.value: _fetch_variable_info_live(qt) for qt in _QueryType}


# ---------------------------------------------------------------------------
# Disk-backed lookup (used by the MCP server runtime)
# ---------------------------------------------------------------------------


def _load_all_variable_info_from_disk() -> dict[str, dict[str, dict[str, str]]]:
    """Return the on-disk cache as a JSON-shaped dict."""
    data: Any = load_json_cache(_VARIABLES_PATH)
    return data


def _get_variable_info(query_type: _QueryType) -> dict[str, dict[str, str]]:
    """Return cached variable info for *query_type*, loading from disk once."""
    if query_type in _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE[query_type]
    all_info = _load_all_variable_info_from_disk()
    for qt in _QueryType:
        if qt.value in all_info:
            _VARIABLE_INFO_CACHE[qt] = all_info[qt.value]
    if query_type not in _VARIABLE_INFO_CACHE:
        msg = f"No variable info for GBIF query type {query_type!r}"
        raise KeyError(msg)
    return _VARIABLE_INFO_CACHE[query_type]


# ---------------------------------------------------------------------------
# Registration with the refresh script
# ---------------------------------------------------------------------------


register(
    VariableCacheEntry(
        name="gbif",
        cache_path=_VARIABLES_PATH,
        fetch_live=_fetch_all_variable_info_live,
        load_disk=_load_all_variable_info_from_disk,
    )
)
