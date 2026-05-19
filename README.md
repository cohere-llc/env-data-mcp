# env-data-mcp

[![CI](https://github.com/cohere-llc/env-data-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/cohere-llc/env-data-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/cohere-llc/env-data-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/cohere-llc/env-data-mcp)

MCP server that exposes environmental data — weather, soil, atmospheric composition,
and satellite observations — as tools callable by any MCP-compatible AI assistant or
workflow.  Tools accept a location (point or bounding box) and a date range and return
structured JSON with the data and a `_meta` block that includes the data licence,
latency, and enough provenance information to reproduce the query.

**Status:** Prototype complete — 9 sources operational (NASA POWER, SSURGO, SoilGrids,
GBIF, Sentinel-5P, OCO-2, EMIT, ESS-DIVE, OpenAQ). CI matrix on Python 3.11/3.12,
nightly integration tests, schema stability assertions.

---

## Quick start

```bash
git clone https://github.com/cohere-llc/env-data-mcp.git
cd env-data-mcp
uv sync

# Start the server (stdio transport; runs until killed with Ctrl-C)
uv run env-data-mcp
```

The server prints no output on start; an MCP client connects via stdio.

### Hello-world example

With the server running, verify it works with this self-contained Python snippet:

```python
# hello_world.py — run with: uv run python hello_world.py
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="uv",
        args=["run", "env-data-mcp"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "nasa_power_merra2_query",
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
```

Expected output shape:

```json
{
  "data": [
    {"date": "2023-05-01", "T2M": 14.2, "T2M_units": "C", "PRECTOTCORR": 0.0, ...},
    {"date": "2023-05-02", "T2M": 15.8, "T2M_units": "C", "PRECTOTCORR": 1.3, ...},
    {"date": "2023-05-03", "T2M": 13.1, "T2M_units": "C", "PRECTOTCORR": 0.0, ...}
  ],
  "_meta": {
    "source": "nasa_power",
    "rows_returned": 3,
    "latency_s": 1.4,
    "auth_required": false,
    "success": true,
    "license": "Public domain (NASA/US Government). Citation requested.",
    "query_params": {"latitude": 46.253, "longitude": -119.477, ...}
  }
}
```

### Register in VS Code (`.mcp.json`)

Add to your VS Code workspace `.mcp.json` to make all tools available to GitHub Copilot:

```json
{
  "mcpServers": {
    "env-data": {
      "command": "uv",
      "args": ["--directory", "/path/to/env-data-mcp", "run", "env-data-mcp"],
      "env": {
        "EARTHDATA_TOKEN": "${EARTHDATA_TOKEN}",
        "OPENAQ_API_KEY": "${OPENAQ_API_KEY}",
        "ESSDIVE_TOKEN": "${ESSDIVE_TOKEN}"
      }
    }
  }
}
```

Replace `/path/to/env-data-mcp` with the absolute path to your local clone. The `${VAR}` syntax reads from your shell environment (or from a `.env` file if your MCP host supports it).

### Register on JupyterHub / Lakehouse

If the package wheel has been installed into the JupyterHub environment:

```json
{
  "mcpServers": {
    "env-data": {
      "command": "uvx",
      "args": ["--from", "env-data-mcp", "env-data-mcp"],
      "env": {
        "EARTHDATA_TOKEN": "${EARTHDATA_TOKEN}",
        "OPENAQ_API_KEY": "${OPENAQ_API_KEY}",
        "ESSDIVE_TOKEN": "${ESSDIVE_TOKEN}"
      }
    }
  }
}
```

See [Credential setup](#environment-variables) for how to obtain each token.

### Available tools

| Tool | Source | Auth | Description |
|---|---|---|---|
| `nasa_power_merra2_query` | NASA POWER MERRA-2 | none | Atmospheric data (T, precip, RH, radiation) at a point |
| `nasa_power_merra2_bbox_query` | NASA POWER MERRA-2 | none | Atmospheric data over a bounding box |
| `nasa_power_syn1deg_query` | NASA POWER CERES SYN1deg | none | Radiation fluxes at a point |
| `nasa_power_syn1deg_bbox_query` | NASA POWER CERES SYN1deg | none | Radiation fluxes over a bounding box |
| `ssurgo_query` | USDA SSURGO | none | Soil map unit and properties for a US point |
| `ssurgo_bbox_query` | USDA SSURGO | none | Soil map units within a bounding box |
| `soilgrids_query` | ISRIC SoilGrids v2 | none | Global soil properties at a point |
| `soilgrids_bbox_query` | ISRIC SoilGrids v2 | none | Global soil properties over a bounding box |
| `gbif_occurrences` | GBIF | none | Species occurrence records within a radius |
| `gbif_bbox_occurrences` | GBIF | none | Species occurrence records within a bounding box |
| `sentinel5p_query` | Sentinel-5P TROPOMI | none | Atmospheric column at a point (CO / NO₂ / CH₄) |
| `sentinel5p_bbox_query` | Sentinel-5P TROPOMI | none | Atmospheric column mean over a bounding box |
| `oco2_query` | OCO-2 GEOS L3 | NASA EarthData token | Daily XCO₂ column at a point |
| `oco2_bbox_query` | OCO-2 GEOS L3 | NASA EarthData token | Daily XCO₂ column over a bounding box |
| `emit_query` | NASA EMIT L2B | NASA EarthData token | Mineral identification at a point |
| `emit_bbox_query` | NASA EMIT L2B | NASA EarthData token | Mineral identification over a bounding box |
| `essdive_query` | ESS-DIVE | ESS-DIVE token (free) | DOE environmental field datasets near a point |
| `essdive_bbox_query` | ESS-DIVE | ESS-DIVE token (free) | DOE environmental field datasets within a bounding box |
| `openaq_query` | OpenAQ v3 | API key (free) | Surface air quality measurements near a point |
| `openaq_bbox_query` | OpenAQ v3 | API key (free) | Surface air quality measurements within a bounding box |

### Environment variables

| Variable | Required by | Description |
|---|---|---|
| `EARTHDATA_TOKEN` | OCO-2, EMIT | NASA EarthData bearer token — register free at [urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov) |
| `ESSDIVE_TOKEN` | ESS-DIVE | ESS-DIVE API token — register free at [ess-dive.lbl.gov](https://ess-dive.lbl.gov) |
| `OPENAQ_API_KEY` | OpenAQ | Free key from [openaq.org](https://openaq.org) — requests without a key are rejected by the API |

---

## Development

### Requirements

* Python ≥ 3.11
* [uv](https://docs.astral.sh/uv/) (install with `pip install uv` or `curl -Lsf https://astral.sh/uv/install.sh | sh`)

### Install with dev dependencies

```bash
uv sync --extra dev
```

### Run the unit tests (no network required)

```bash
uv run pytest tests/unit/ -m "not integration" -v
```

Expected output: 250+ unit tests pass; all HTTP / S3 calls are mocked.

### Run tests with coverage report

```bash
uv run pytest tests/unit/ -m "not integration" --cov=env_data_mcp --cov-report=html
# then open htmlcov/index.html
```

### Run integration tests (requires network)

```bash
uv run pytest tests/ -m integration -v
```

OpenAQ integration tests also require `OPENAQ_API_KEY` to be set.

### Run example notebooks

Two demonstration notebooks are included:

| Notebook | Description |
|---|---|
| `notebooks/grow_point_sample_demo.ipynb` | All 6 sources for 5 real GROW field samples |
| `notebooks/pnnl_bbox_demo.ipynb` | NASA POWER + Sentinel-5P over the PNNL Richland bbox |

```bash
# load notebook dependencies
uv sync --extra dev --extra notebook

# Run interactively
jupyter lab notebooks/

# Or run headlessly via nbmake (network required; S5P cells take 30–120 s each)
uv run pytest notebooks/ --no-cov
```

---

## Data licences

Each data source adapter carries a `LICENSE_INFO` constant with SPDX identifier, full
licence name, and URL.  Human-readable licence text and citation requirements for all
sources are collected in [LICENSES.md](LICENSES.md).

| Source | Licence |
|---|---|
| NASA POWER | Public domain (NASA) |
| SSURGO | Public domain (USDA) |
| SoilGrids v2 | CC BY 4.0 |
| GBIF | CC0 / CC BY / CC BY-NC per record |
| Sentinel-5P | ESA Copernicus Open Access |
| OpenAQ | CC BY 4.0 |
| OCO-2 | Public domain (NASA) |
| EMIT | Public domain (NASA) |
| ESS-DIVE | Varies per dataset |

---

## Contributing

To add a new data source:

1. Create `src/env_data_mcp/sources/<name>.py` with a `LICENSE_INFO` dict constant and
   one or more `@mcp.tool` functions.
2. Write unit tests in `tests/unit/test_<name>.py` that mock all HTTP / S3 calls.
3. Write an integration test in `tests/integration/test_<name>.py` marked
   `@pytest.mark.integration`.
4. Add licence text to `LICENSES.md`.
5. Add a notebook cell to `notebooks/api_smoke_test.ipynb` demonstrating a real call.
