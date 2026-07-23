# hello_world.py — run with: uv run python hello_world.py
import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(
        command="uv",
        args=["run", "env-data-mcp"],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        raw_result = await session.call_tool(
            "nasa_power_merra2_point_query",
            arguments={
                "latitude": 46.253,
                "longitude": -119.477,
                "start_date": "2023-05-01",
                "end_date": "2023-05-03",
                "temporal_resolution": "daily",
            },
        )
        result = json.loads(raw_result.content[0].text)
        print(result)


asyncio.run(main())
