# env-data-mcp

[![CI](https://github.com/cohere-llc/env-data-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/cohere-llc/env-data-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/cohere-llc/env-data-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/cohere-llc/env-data-mcp)

MCP server that exposes environmental data — weather, soil, atmospheric composition,
and satellite observations — as tools callable by any MCP-compatible AI assistant or
workflow.  Tools accept a location (point or bounding box) and a date range and return
structured JSON with the data and a `_meta` block that includes the data licence,
latency, and enough provenance information to reproduce the query.

**Status:** Phase 2 complete — 5 no-auth sources operational (NASA POWER, SSURGO,
SoilGrids, GBIF, Sentinel-5P) + 1 auth-required source (OpenAQ, free key).

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
| `ssurgo_query` | USDA SSURGO | none | Soil map unit and properties for a US point |
| `soilgrids_query` | ISRIC SoilGrids v2 | none | Global soil properties at a point |
| `gbif_occurrences` | GBIF | none | Species occurrence records within a radius |
| `gbif_bbox_occurrences` | GBIF | none | Species occurrence records within a bounding box |
| `sentinel5p_query` | Sentinel-5P TROPOMI | none | Atmospheric column at a point (CO / NO₂ / CH₄) |
| `sentinel5p_bbox_query` | Sentinel-5P TROPOMI | none | Atmospheric column mean over a bounding box |
| `openaq_query` | OpenAQ v3 | API key (free) | Surface air quality measurements |

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENAQ_API_KEY` | Recommended | Free key from [openaq.org](https://openaq.org) — requests without a key are rejected by the API |

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

Expected output: 170+ unit tests pass; all HTTP / S3 calls are mocked.

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
| OCO-2 / OCO-3 | Public domain (NASA) |
| EMIT | Public domain (NASA) |
| ESS-DIVE | Varies per dataset |
| Google Earth Engine | Varies per dataset |

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
