"""REST Client for GBIF adapter."""

from __future__ import annotations

import httpx

from env_data_mcp.helpers import get_by_path

from .constants import _QUERY_RESULT_SCHEMAS, _QueryType

# ---------------------------------------------------------------------------
# Session-level caches
# ---------------------------------------------------------------------------

# available variables by query type -> { query_type: { variable: {" description": str } }
_VARIABLE_INFO_CACHE: dict[_QueryType, dict[str, dict[str, str]]] = {}

# ---------------------------------------------------------------------------
# Client functions
# ---------------------------------------------------------------------------


def _get_variable_info(query_type: _QueryType) -> dict[str, dict[str, str]]:
    """Discover available variables for a specific GBIF query type.

    :param query_type: GBIF query type
    :return: dict keyed on variable with `description`
    """
    if query_type in _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE[query_type]
    with httpx.Client(timeout=30) as client:
        resp = client.get(_QUERY_RESULT_SCHEMAS[query_type]["url"])
        resp.raise_for_status()
        info = get_by_path(resp.json(), _QUERY_RESULT_SCHEMAS[query_type]["path"], {})
    return {
        key: {"description": val.get("description", ""), "units": ""} for key, val in info.items()
    }
