import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(
        command="uv",
        args=["run", "env-data-mcp"],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(
            "ssurgo_soil_profile_available_variables",
            arguments={
                "latitude": 46.253,
                "longitude": -119.477,
                "start_date": "2023-05-01",
                "end_date": "2023-05-03",
                "temporal_resolution": "daily",
            },
        )
        print(result)


asyncio.run(main())
