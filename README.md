# env-data-mcp

[![CI](https://github.com/cohere-llc/env-data-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/cohere-llc/env-data-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/cohere-llc/env-data-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/cohere-llc/env-data-mcp)

MCP server that exposes environmental data — weather, soil, atmospheric composition,
and satellite observations — as tools callable by any MCP-compatible AI assistant or
workflow.  Tools accept a location (point or bounding box) and a date range and return
structured JSON with the data and a `_meta` block that includes the data licence,
latency, and enough provenance information to reproduce the query.

**Status:** Phase 0 scaffold — server starts and responds to the MCP handshake; data
tools are added in later phases.

---

## Quick start

```bash
git clone https://github.com/<org>/env-data-mcp.git
cd env-data-mcp
uv sync

# Start the server (stdio transport; runs until killed with Ctrl-C)
uv run env-data-mcp
```

The server prints no output on start; an MCP client connects via stdio.  With the Phase 0
scaffold the tool list is empty — tools are added in Phases 1–4.

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

Expected output: **62 passed** covering `helpers.py` and `models.py` at 100 %.

### Run tests with coverage report

```bash
uv run pytest tests/unit/ -m "not integration" --cov=env_data_mcp --cov-report=html
# then open htmlcov/index.html
```

### Run integration tests (requires network and credentials)

Integration tests are not yet written (Phase 1+).  When available:

```bash
uv run pytest tests/integration/ -m integration -v
```

### Run example notebooks

```bash
uv run pytest notebooks/ --nbmake
```

No notebooks exist yet; this command will collect zero items and exit successfully.

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
