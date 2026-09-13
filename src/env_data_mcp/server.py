"""
MCP server entry point.

Registers all tool handlers via @mcp.tool() decorators in each source module.
Source modules are imported below.
"""

import argparse

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except ImportError:
    # mcp 2.x renamed FastMCP -> MCPServer (same tool() decorator and run()); see
    # https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver
    # A consumer whose resolver picks mcp 2.x (pipx, a fresh venv) must still import the tools.
    from mcp.server.mcpserver import MCPServer as FastMCP

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
from env_data_mcp.sources import tropomi
from env_data_mcp.sources import openaq
from env_data_mcp.sources import oco2
from env_data_mcp.sources import emit
from env_data_mcp.sources import essdive

# feeds (live events) + point accessors
from env_data_mcp.sources import eonet
from env_data_mcp.sources import usgs_quakes
from env_data_mcp.sources import nasa_firms
from env_data_mcp.sources import nws_alerts
from env_data_mcp.sources import usgs_water
from env_data_mcp.sources import open_meteo
from env_data_mcp.sources import daymet
from env_data_mcp.sources import macrostrat
from env_data_mcp.sources import elevation_3dep
from env_data_mcp.sources import arm
from env_data_mcp.sources import eia
from env_data_mcp.sources import era5_cds

# GUI dashboard
from env_data_mcp.dashboard import launch_gui


def main() -> None:
    parser = argparse.ArgumentParser("Environmental Data MCP Server")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch a GUI instead of stdio mode",
    )
    args = parser.parse_args()

    if args.gui:
        print("Launching GUI. Press CTRL+C to exit.")
        launch_gui()
    else:
        mcp.run()


if __name__ == "__main__":
    main()
