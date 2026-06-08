import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command="uv", args=["run", "env-data-mcp"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        # result = await session.list_tools()
        result = await session.call_tool(
            "gbif_occurrence_bbox_query",
            arguments={
                # "latitude": 46.253,
                # "longitude": -119.477,
                "min_lat": 45.0,
                "max_lat": 47.0,
                "min_lon": -121.0,
                "max_lon": -116.0,
                # "radius_km": 1000.0,
                "start_date": "2023-05-01",
                "end_date": "2023-05-03",
                "max_runtime_s": 200.0,
                "limit": 1000,
            },
        )
        if result.structuredContent:
            print(result.structuredContent)
            print(f"number of records: {result.structuredContent['_meta']['rows_returned']}")
            for geom in result.structuredContent["data"]:
                print(f"{geom}")


asyncio.run(main())
