# env-data-mcp

[![CI](https://github.com/kbaseincubator/env-data-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/kbaseincubator/env-data-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/kbaseincubator/env-data-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/kbaseincubator/env-data-mcp)

MCP server that exposes environmental data — weather, soil, atmospheric composition,
and satellite observations — as tools callable by any MCP-compatible AI assistant or
workflow.  Tools accept a location (point or bounding box) and a date range and return
structured JSON with the data and a `_meta` block that includes the data license,
citations, query latency, and enough information to reproduce the query.

**Status:** 6 sources have been made fully functional (NASA POWER,
SSURGO, SoilGrids, GBIF, TROPOMI, OpenAQ); 3 sources are still only prototyped (OCO-2, EMIT,
and ESS-DIVE).  The **`feeds` family** (live events: EONET, USGS earthquakes, NASA FIRMS, NWS
alerts, USGS Water Data, Open-Meteo) and six **point accessors** (Daymet, Macrostrat, 3DEP
elevation, ARM, EIA, ERA5 via CDS) return the same `{data, _meta}` shape with a shared event
schema, a per-source TTL and a quota governor — see "Feeds and point accessors" below.

---

## Quick start

Clone the repo and pull in dependencies:
```bash
git clone https://github.com/kbaseincubator/env-data-mcp
cd env-data-mcp
uv sync
```

### Command-Line MCP Usage

Start the server (stdio transport; runs until killed with Ctrl-C)

```bash
uv run env-data-mcp
```

The server prints no output on start; an MCP client connects via stdio.

#### Hello-world example

With the server running, verify it works with this self-contained Python snippet:

```python
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
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            raw_result = await session.call_tool(
                "nasa_power_merra2_point_query",
                arguments={
                    "latitude": 46.253,
                    "longitude": -119.477,
                    "start_date": "2023-05-01",
                    "end_date": "2023-05-03",
                    "variables": ["T2M", "PRECTOTCORR"],
                    "temporal_resolution": "daily",
                },
            )
            result = json.loads(raw_result.content[0].text)
            print(result)

asyncio.run(main())
```

Expected output shape:

```json
{
  'data': [
    {
      'geometry': {'type': 'Point', 'coordinates': [-119.375, 46.5]},
      'records': [
        {'date': '2023-05-01', 'T2M': 17.22998046875, 'T2M_units': 'C', 'PRECTOTCORR': 0.65997314453125, 'PRECTOTCORR_units': 'mm'},
        {'date': '2023-05-02', 'T2M': 14.72998046875, 'T2M_units': 'C', 'PRECTOTCORR': 0.1500244140625, 'PRECTOTCORR_units': 'mm'},
        {'date': '2023-05-03', 'T2M': 19.72998046875, 'T2M_units': 'C', 'PRECTOTCORR': 0.0, 'PRECTOTCORR_units': 'mm'}
      ],
      'latitude': 46.5,
      'longitude': -119.375
    }
  ],
  '_meta': {
    'source': 'nasa_power',
    'success': True,
    'geometries_returned': 1,
    'total_records_returned': 3,
    'latency_s': 0.803849,
    'auth_required': False,
    'auth_present': True,
    'error': None,
    'license': 'There are no restrictions on the use...',
    'license_url': '',
    'citation': 'NASA Prediction of Worldwide Energy Resources (POWER)...',
    'query_params': {
      'latitude': 46.253,
      'longitude': -119.477,
      'start_date': '2023-05-01',
      'end_date': '2023-05-03',
      'variables': ['T2M', 'PRECTOTCORR'],
      'temporal_resolution': 'daily',
      'max_runtime_s': 30.0
    },
    'variables': ['T2M', 'PRECTOTCORR'],
    'variable_info': {
      'T2M': {'description': 'Temperature at 2 Meters', 'units': 'C'},
      'PRECTOTCORR': {'description': 'Precipitation Corrected', 'units': 'mm'}
    },
    'unavailable_variables': [],
    'citation_urls': ['https:\/\/nasa-power.s3.amazonaws.com/CITATION.cff', 'https:\/\/power.larc.nasa.gov/docs/methodology/citations/'],
    'description': "The Modern-Era Retrospective analysis...",
    'description_url': 'https:\/\/registry.opendata.aws/nasa-power/',
    'acknowledgements': ''
  }
}
```

### GUI
To start the GUI (runs until killed with Ctrl-C):
```bash
uv run env-data-mcp --gui
```

Then navigate to the URL specified after `Running on local URL:` (typically `http://127.0.0.1:7860`)

You should see something like this:

![env-data-mcp dashboard](assets/dashboard.png)

Click on a data provider, choose a dataset, and run the queries interactively. You will see formatted JSON output for query responses.

## Register in VS Code (`.mcp.json`)

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

## Register on JupyterHub / Lakehouse

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

# Available tools

| Tool | Source | Auth | Description |
|---|---|---|---|
| `nasa_power_merra2_point_query` | NASA POWER MERRA-2 | none | Atmospheric data (T, precip, RH, radiation) at a point |
| `nasa_power_merra2_bbox_query` | NASA POWER MERRA-2 | none | Atmospheric data over a bounding box |
| `nasa_power_syn1deg_point_query` | NASA POWER CERES SYN1deg | none | Radiation fluxes at a point |
| `nasa_power_syn1deg_bbox_query` | NASA POWER CERES SYN1deg | none | Radiation fluxes over a bounding box |
| `ssurgo_*_query` | USDA SSURGO | none | Soil properties for a US point |
| `ssurgo_*_bbox_query` | USDA SSURGO | none | Soil properties within a bounding box |
| `gbif_occurrence_point_query` | GBIF | none | Species occurrence records within a radius |
| `gbif_occurrence_bbox_query` | GBIF | none | Species occurrence records within a bounding box |
| `soilgrids_point_query` | ISRIC SoilGrids v2 | none | Global soil properties at a point |
| `soilgrids_bbox_query` | ISRIC SoilGrids v2 | none | Global soil properties over a bounding box |
| `tropomi_point_query` | Sentinel-5P TROPOMI | none | Atmospheric composition at a point location |
| `tropomi_bbox_query` | Sentinel-5P TROPOMI | none | Atmospheric composition over a bounding box |
| `openaq_point_query` | OpenAQ v3 | API key (free) | Surface air quality measurements near a point |
| `openaq_bbox_query` | OpenAQ v3 | API key (free) | Surface air quality measurements within a bounding box |


\* For SSURGO tools, replace the (`*`) with one of: `area_summary`, `ecological_site`, `parent_material`, `seasonal_hydrology`, `soil_profile`, `soil_suitability`, `soil_temperature`, or `subsurface_barriers`.

## Feeds and point accessors

Live events share one schema, `models.EventRecord` (`id, source, kind, title, lat, lon, geometry,
t_start, t_end, magnitude, magnitude_unit, severity, url, licence` + source `properties`), and
every feed tool returns `{data: [EventRecord, …], _meta}`.  `_meta` gains `ttl_s` (the source's
cache TTL, honoured in-process), `fetched_at`, `cached`, and for keyed or rate-limited sources
`quota = {limit, window_s, used, remaining, resets_in_s}` — at the limit the tool refuses with a
normal response, never an exception.  A keyed tool without its key answers
`auth_required: true, auth_present: false` and empty `data`.  Keys travel in headers (or, for
FIRMS, in a URL that is never returned or logged); no key is ever echoed.

| Tool | Source | Auth | TTL | Description |
|---|---|---|---|---|
| `eonet_events` | NASA EONET v3 | none | 30 min | Curated natural events (fires, storms, volcanoes, floods, ice …), optional bbox, last N days |
| `usgs_quakes_events` | USGS FDSN / ComCat | none | 5 min | Earthquakes with magnitude, depth, PAGER alert level, optional bbox |
| `nasa_firms_fires` | NASA FIRMS | `NASA_FIRMS_MAP_KEY` (5,000 / 10 min) | 30 min | VIIRS / MODIS fire detections in a bbox, FRP and confidence |
| `nws_alerts_at` | NWS api.weather.gov | none | 10 min | Active alerts at a point or for a state/marine area (US) |
| `usgs_water_latest` | USGS Water Data OGC API | none 50/h · `USGS_WATERDATA_API_KEY` 1,000/h | 15 min | Latest instantaneous values per monitoring location (discharge, gage height …) |
| `open_meteo_current` | Open-Meteo | none; **gated** unless `ENV_DATA_ALLOW_NC=1` | 15 min | Current conditions + daily forecast at a point (non-commercial terms) |
| `daymet_at` | Daymet (ORNL DAAC) | none | 24 h | Daily tmax / tmin / prcp … at a 1 km pixel on one date, North America 1980– |
| `macrostrat_at` | Macrostrat | none | 7 d | The geologic map unit at a point: lithology, age, interval |
| `elevation_3dep` | USGS 3DEP (EPQS) | none | 30 d | Ground elevation at a point (US); the service can take 10–15 s |
| `arm_nearest` | DOE ARM | none (site table) | — | The nearest ARM fixed observatory and its distance |
| `eia_plants_near` | EIA API v2 (EIA-860M) | `EIA_API_KEY` | 24 h | Power plants within a radius, capacity by fuel [field names unverified live until the integration test runs with a key] |
| `era5_monthly_at` | ERA5 via CDS | `CDS_API_KEY` | 30 d | Monthly means at the nearest 0.25° point; **a queued job** — answers `queued:` with a `job_id` to resume |

Not built, and why: **NWI wetlands** — the point/envelope query answers HTTP 400 for every
variant (probed 2026-09); **ARM Live data** — its API takes `user:token` in the query string, which
this server never does (a credential in a URL); the site table stands in until a header-based path
exists.

## Prototyped tools

These tools are functional but may return subsets of requested data, not expose all dataset
parameters, and not follow the standardized response schema.

| Tool | Source | Auth | Description |
|---|---|---|---|
| `oco2_query` | OCO-2 GEOS L3 | NASA EarthData token | Daily XCO₂ column at a point |
| `oco2_bbox_query` | OCO-2 GEOS L3 | NASA EarthData token | Daily XCO₂ column over a bounding box |
| `emit_query` | NASA EMIT L2B | NASA EarthData token | Mineral identification at a point |
| `emit_bbox_query` | NASA EMIT L2B | NASA EarthData token | Mineral identification over a bounding box |
| `essdive_query` | ESS-DIVE | ESS-DIVE token (free) | DOE environmental field datasets near a point |
| `essdive_bbox_query` | ESS-DIVE | ESS-DIVE token (free) | DOE environmental field datasets within a bounding box |

## Environment variables

| Variable | Required by | Description |
|---|---|---|
| `EARTHDATA_TOKEN` | OCO-2, EMIT | NASA EarthData bearer token — register free at [urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov) |
| `ESSDIVE_TOKEN` | ESS-DIVE | ESS-DIVE API token — register free at [ess-dive.lbl.gov](https://ess-dive.lbl.gov) |
| `OPENAQ_API_KEY` | OpenAQ | Free key from [openaq.org](https://openaq.org) — requests without a key are rejected by the API |
| `NASA_FIRMS_MAP_KEY` | NASA FIRMS | Free MAP_KEY from [firms.modaps.eosdis.nasa.gov/api/map_key](https://firms.modaps.eosdis.nasa.gov/api/map_key/) — 5,000 transactions / 10 min |
| `USGS_WATERDATA_API_KEY` | USGS Water Data (optional) | Free key from [api.waterdata.usgs.gov/signup](https://api.waterdata.usgs.gov/signup/) — lifts the keyless 50/h to 1,000/h |
| `EIA_API_KEY` | EIA | Free key from [eia.gov/opendata/register.php](https://www.eia.gov/opendata/register.php) |
| `CDS_API_KEY` | ERA5 (CDS) | A CDS Personal Access Token ([cds.climate.copernicus.eu/how-to-api](https://cds.climate.copernicus.eu/how-to-api)); accept the ERA5 dataset licence once on the CDS site |
| `ENV_DATA_ALLOW_NC` | Open-Meteo | Set to `1` to attest non-commercial use; without it the tool answers `gated` |

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

### Update cached variables

Available variables are cached in the repo in json files. When the test suite is run
(locally or in GitHub Actions), tests verify that the cached variable information is
up-to-date with the live services. If they are out-of-date, the tests fail. The cache
files can be re-synced by running `pytest` with a `--update-caches` flag:

```bash
uv run pytest tests/integration/test_variable_caches_live.py --update-caches
```

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
| TROPOMI | ESA Copernicus Open Access |
| OpenAQ | CC BY 4.0 |
| OCO-2 | Public domain (NASA) |
| EMIT | Public domain (NASA) |
| ESS-DIVE | Varies per dataset |
| NASA EONET | Public domain (NASA) |
| USGS earthquakes | Public domain (USGS) |
| NASA FIRMS | NASA data policy — free and open, attribution requested |
| NWS alerts | Public domain (NOAA) |
| USGS Water Data | Public domain (USGS) |
| Open-Meteo | CC BY 4.0 — free API for non-commercial use only (gated) |
| Daymet | Open (ORNL DAAC) |
| Macrostrat | CC BY 4.0 |
| USGS 3DEP | Public domain (USGS) |
| ARM | Free and open (ARM data use guidelines) |
| EIA | Public domain (US Government) |
| ERA5 (CDS) | CC BY 4.0 |

---

## Contributing

To add a new data source:

1. Create a `src/env_data_mcp/sources/<name>/` folder for the data source.
2. At minimum include a `src/env_data_mcp/sources/<name>/tools.py` file for the MCP tools
3. a. Include `<name>_available_variables`, `<name>_point_query`, and `<name>_bbox_query` functions decorated with `@mcp.tool()`
3. b. Alternatively create `<name>_<dataset>_available_variables`, `<name>_<dataset>_point_query`, and `<name>_<dataset>_bbox_query` tool functions when the data source provides multiple datasets.
4. Write unit tests in `tests/unit/<name>/` that mock all HTTP / S3 calls.
5. Write integration tests in `tests/integration/test_<name>_live.py` marked
   `@pytest.mark.integration` that call the live service and implement the `test_common_live.py` integration tests.
6. Ensure all tool functions follow existing patterns for input arguments and return common response schema validated using `src/env_data_mcp/models.py` and `src/env_data_mcp/helpers.py`.
