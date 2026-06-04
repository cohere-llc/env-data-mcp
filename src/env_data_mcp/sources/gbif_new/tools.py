"""MCP tool functions for the GBIF adapter."""

from __future__ import annotations

from typing import Any

from env_data_mcp.helpers import build_meta
from env_data_mcp.models import AvailableVariablesResponse
from env_data_mcp.server import mcp

from ._client import _get_variable_info
from .constants import LICENSE_INFO, _QueryType


def _validate_available_variables_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize available variables tool reponses."""
    return AvailableVariablesResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def gbif_occurrence_available_variables() -> dict[str, Any]:
    """Return a list of available GBIF Occurrence variables with descriptions."""
    variable_info = _get_variable_info(_QueryType.OCCURRENCE)
    return _validate_available_variables_response(
        {
            "data": variable_info,
            "_meta": build_meta(
                source="gbif",
                query_params={},
                rows_returned=len(variable_info),
                latency_s=0.0,
                license_info=LICENSE_INFO,
            ),
        }
    )
