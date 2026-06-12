"""MCP tool functions for the SoilGrids adapter."""

from __future__ import annotations

from typing import Any

from env_data_mcp.helpers import build_meta
from env_data_mcp.models import AvailableVariablesResponse
from env_data_mcp.server import mcp

from ._query import get_variable_info
from .constants import LICENSE_INFO


def _validate_available_variable_response(response: dict[str, Any]) -> dict[str, Any]:
    return AvailableVariablesResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def soilgrids_available_variables() -> dict[str, Any]:
    """Return a list of available SoilGrids variables with descriptions and units."""
    var_info_raw = get_variable_info()
    var_info = {
        key: {"description": val.description, "units": val.units}
        for key, val in var_info_raw.items()
    }
    return _validate_available_variable_response(
        {
            "data": var_info,
            "_meta": build_meta(
                source="soilgrids",
                query_params={},
                rows_returned=len(var_info),
                latency_s=0.0,
                license_info=LICENSE_INFO,
            ),
        }
    )
