# env-data-mcp

[![CI](https://github.com/cohere-llc/env-data-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/cohere-llc/env-data-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/cohere-llc/env-data-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/cohere-llc/env-data-mcp)

MCP server that exposes environmental data — weather, soil, atmospheric composition,
and satellite observations — as tools callable by any MCP-compatible AI assistant or
workflow.  Tools accept a location (point or bounding box) and a date range and return
structured JSON with the data and a `_meta` block that includes the data licence,
latency, and enough provenance information to reproduce the query.

**Status:** Phase 3 complete — 9 sources operational (NASA POWER, SSURGO, SoilGrids,
GBIF, Sentinel-5P, OCO-2, EMIT, ESS-DIVE, OpenAQ).

---

## Quick start

```bash
git clone https://github.com/<org>/env-data-mcp.git
cd env-data-mcp
uv sync

# Start the server (stdio transport; runs until killed with Ctrl-C)
uv run env-data-mcp
```

The server prints no output on start; an MCP client connects via stdio.

### Available tools

| Tool | Source | Auth | Description |
|---|---|---|---|
| `nasa_power_query` | NASA POWER | none | Daily weather (T, precip, RH, radiation) at a point |
| `nasa_power_bbox_query` | NASA POWER | none | Daily weather statistics over a bounding box |
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
# Run interactively
jupyter lab notebooks/

# Or run headlessly via nbmake (network required; S5P cells take 30–120 s each)
uv run pytest notebooks/ --nbmake --ignore=notebooks/api_smoke_test.ipynb
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
