"""
MCP server entry point.

Registers all tool handlers via @mcp.tool() decorators in each source module.
Source modules are imported below as they are implemented (Phase 1+).
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "env-data-mcp",
    instructions=(
        "Environmental data server. Provides weather, soil, atmospheric, and "
        "satellite data for arbitrary locations and time windows. Every tool "
        "accepts location (latitude/longitude or bounding box) and datetime "
        "parameters and returns a structured result with a '_meta' block "
        "containing source, license, and query provenance information."
    ),
)

# Source modules register their tools against this mcp instance.
# Each import has side-effects: tool functions are decorated with @mcp.tool().
from env_data_mcp.sources import nasa_power  # Phase 1
from env_data_mcp.sources import soilgrids  # Phase 1
from env_data_mcp.sources import ssurgo  # Phase 1
from env_data_mcp.sources import gbif  # Phase 2
from env_data_mcp.sources import openaq  # Phase 2
from env_data_mcp.sources import sentinel5p  # Phase 2
from env_data_mcp.sources import oco2  # Phase 3
from env_data_mcp.sources import emit  # Phase 3
from env_data_mcp.sources import essdive  # Phase 3
# from env_data_mcp.sources import gee           # Phase 3


def main() -> None:
    mcp.run()
