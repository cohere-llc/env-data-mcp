"""
MCP server entry point.

Registers all tool handlers via @mcp.tool() decorators in each source module.
Source modules are imported below.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "env-data-mcp",
    instructions=(
        "Environmental data server. Provides weather, water, soil, atmospheric, "
        "and biodiversity data from in situ and remote sensing sources. "
        "Tools are organized by data source. Every tool "
        "accepts location (latitude/longitude or bounding box) and datetime "
        "parameters and returns a structured result with a '_meta' block "
        "containing source, license, and query provenance information."
    ),
)

# Source modules register their tools against this mcp instance.
# Each import has side-effects: tool functions are decorated with @mcp.tool().
from env_data_mcp.sources import nasa_power
from env_data_mcp.sources import soilgrids
from env_data_mcp.sources import ssurgo
from env_data_mcp.sources import gbif
from env_data_mcp.sources import openaq
from env_data_mcp.sources import sentinel5p
from env_data_mcp.sources import oco2
from env_data_mcp.sources import emit
from env_data_mcp.sources import essdive


def main() -> None:
    mcp.run()
