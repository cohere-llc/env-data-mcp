"""MCP tool functions for the Sentinel 5-TROPOMI adapter."""

from __future__ import annotations

from typing import Any

from env_data_mcp.helpers import build_meta
from env_data_mcp.models import AvailableVariablesResponse
from env_data_mcp.server import mcp

from ._query import _get_variable_info
from .constants import LICENSE_INFO


def _validate_available_variables_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize available variables tool response."""
    return AvailableVariablesResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def tropomi_available_variables() -> dict[str, Any]:
    """Return a list of available TROPOMI variables with descriptions."""
    try:
        variable_info = _get_variable_info()
        return _validate_available_variables_response(
            {
                "data": {
                    key: {"description": val["description"], "units": val["units"]}
                    for key, val in variable_info.items()
                },
                "_meta": build_meta(
                    source="tropomi",
                    query_params={},
                    rows_returned=len(variable_info),
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                ),
            }
        )
    except Exception as e:
        return _validate_available_variables_response(
            {
                "data": {},
                "_meta": build_meta(
                    source="tropomi",
                    query_params={},
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(e),
                ),
            }
        )
