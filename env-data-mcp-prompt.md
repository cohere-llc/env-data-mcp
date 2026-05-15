# Environmental Data MCP Server — Development Plan

**Status**: Ready for implementation  
**Package name**: `env-data-mcp`  
**Language**: Python ≥ 3.11 (zarr 3.x requires 3.11; MCP SDK requires 3.10+)  
**Consumer**: BERIL-research-observatory (and any other repo that registers it in `.mcp.json`)  
**Companion plan**: `env-data-prompt.md` — BERIL integration work (logging, Lakehouse, demo notebooks)  
**Reference templates**: `~/git-repos/external-data-gallery` (NASA POWER Zarr, SSURGO, GBIF, Earth Engine)

> **How to read this plan**: Each phase section lists implementation steps, the helper functions to extract, the tests to write alongside, and (boxed) any account registrations you need to complete before that step. The cross-cutting sections on [Data Licenses](#data-licenses), [Variable Metadata Standards](#variable-metadata-standards), [Graceful Upstream Failure Handling](#graceful-upstream-failure-handling), [Query Optimization](#query-optimization), [Automated Testing Strategy](#automated-testing-strategy), [Reproducibility Practices](#reproducibility-practices), and [Local and Lakehouse Testing](#local-and-lakehouse-testing) provide the standards every implementation step must follow.

---

## Purpose and Context

`env-data-mcp` is a standalone MCP server that provides environmental data (weather, soil, atmospheric, satellite) for arbitrary locations and time windows. It is intentionally domain-agnostic — it knows nothing about BERIL, KBase, or any specific dataset. Every tool accepts only location (lat/lon or bounding box) and datetime parameters and returns a structured result. BERIL-specific concerns (Spark SQL, Lakehouse logging, GROW data loading) live entirely in the BERIL repo.

The primary driver is enriching field sample metadata with environmental context at the time and place of sampling — but the interface is general enough to support any location+datetime query.

**Relationship to GeoTap**: GeoTap MCP (`npx geotap-mcp-server`) already covers US government sources: USGS NWIS streamflow, EPA ATTAINS water quality, NOAA rainfall, NWI wetlands, FEMA flood zones. `env-data-mcp` does **not** duplicate these. It covers the complementary set: global weather (NASA POWER), global and US soil (SoilGrids, SSURGO), atmospheric columns (Sentinel-5P, OCO-2/3), hyperspectral (EMIT), biodiversity (GBIF), air quality (OpenAQ), and multi-source imagery (GEE). Downstream consumers register both servers in `.mcp.json` and the agent chooses the right tool.

**Relationship to `external-data-gallery`**: The adapter logic in `external-data-gallery` is the template for every source module here. `env-data-mcp` does not import from `external-data-gallery` — it adapts the code into independently-tested, MCP-compatible modules under `src/env_data_mcp/sources/`. Both repos share test fixture data (`grow_locations.txt`, `pnnl_field_locations.txt`).

---

## Interface Design

The key design constraint: **every tool is fully described by location + datetime**. No tool requires knowledge of BERDL, Spark, or any downstream system.

### Response format

Every tool returns a dict with two top-level keys:

```json
{
  "data": [ ...records... ],
  "_meta": {
    "source": "nasa_power",
    "variables": ["T2M", "PRECTOTCORR"],
    "rows_returned": 31,
    "latency_s": 4.2,
    "auth_required": false,
    "auth_present": true,
    "success": true,
    "error": null,
    "license": "Public domain (NASA/US Government). Citation requested: NASA POWER Project.",
    "license_url": "https://power.larc.nasa.gov/docs/services/terms-conditions/",
    "query_params": {
      "latitude": 46.2531, "longitude": -119.4768,
      "start_date": "2023-05-01", "end_date": "2023-06-01"
    }
  }
}
```

`_meta` is the hook for downstream usage logging. The server reports what it did; consumers (e.g. the BERIL skill) decide whether and where to record it. This keeps the server domain-agnostic while making reliable logging possible without requiring the agent to construct log records from scratch.

`_meta.license` and `_meta.license_url` communicate each source's data use terms so callers can include them in outputs or logs — see [Data Licenses](#data-licenses) for the full per-source table.

`_meta.query_params` echoes back the exact inputs used, enabling exact reproduction of any query from a log record alone.

For auth-required tools where credentials are missing, `data` is `[]` and `_meta.success` is `false` with `_meta.error` containing the setup message. This allows callers to detect and log auth friction without raising an exception.

### Point-sample tools (GROW-style: one row per sample)

```python
nasa_power_query(
    latitude: float,
    longitude: float,
    start_date: str,          # ISO 8601, e.g. "2019-08-15"
    end_date: str,
    variables: list[str] = ["T2M", "T10M", "PRECTOTCORR",
                             "ALLSKY_SFC_SW_DWN", "RH2M", "WS2M"],
    temporal_resolution: str = "daily"   # "daily" | "hourly"
) -> {"data": list[dict], "_meta": dict}

ssurgo_query(
    latitude: float,
    longitude: float
) -> {"data": dict, "_meta": dict}      # map unit + component + horizon; US only

soilgrids_query(
    latitude: float,
    longitude: float
) -> {"data": dict, "_meta": dict}      # sand/silt/clay, SOC, pH, bulk density; global

gbif_occurrences(
    latitude: float,
    longitude: float,
    radius_km: float,
    start_date: str,
    end_date: str,
    taxon_key: int | None = None
) -> {"data": list[dict], "_meta": dict}

sentinel5p_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    product: str              # "CO" | "CH4" | "NO2"
) -> {"data": list[dict], "_meta": dict}

openaq_query(
    latitude: float,
    longitude: float,
    radius_km: float,
    start_date: str,
    end_date: str,
    parameters: list[str] = ["pm25", "pm10", "o3", "no2", "co"]
) -> {"data": list[dict], "_meta": dict}

oco2_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str
) -> {"data": list[dict], "_meta": dict}  # auth_required: true

emit_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str
) -> {"data": list[dict], "_meta": dict}  # auth_required: true

essdive_query(
    latitude: float,
    longitude: float,
    radius_km: float,
    field_name: str
) -> {"data": list[dict], "_meta": dict}  # auth_required: true

gee_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    dataset: str,
    bands: list[str]
) -> {"data": list[dict], "_meta": dict}  # auth_required: true
```

### Bounding-box tools (PNNL-style: time series over an area)

All point tools above accept an optional `bbox` alternative to `latitude`/`longitude`:

```python
bbox: dict = {
    "min_lat": float, "max_lat": float,
    "min_lon": float, "max_lon": float
}
```

When `bbox` is provided, point tools use the centroid for raster sources (NASA POWER, SoilGrids) and the polygon for spatial-query sources (SSURGO, GBIF, OpenAQ). GEE and Sentinel-5P operate natively on the bbox extent.

---

## Data Sources

| Source | Tool | Auth | Coverage |
|---|---|---|---|
| NASA POWER | `nasa_power_query` | None | Global, 1981–present, 0.5°, daily + hourly |
| SSURGO | `ssurgo_query` | None | US only, map-unit scale |
| SoilGrids v2 | `soilgrids_query` | None | Global, 250 m |
| GBIF | `gbif_occurrences` | None | Global, 1800s–present |
| Sentinel-5P TROPOMI | `sentinel5p_query` | None (no-sign S3) | Global, Jul 2018–present |
| OpenAQ | `openaq_query` | None | Global, 2016–present |
| OCO-2/OCO-3 L3 | `oco2_query` | NASA EarthData (free) | Global, 2014–present |
| EMIT hyperspectral | `emit_query` | NASA EarthData (same) | Global land, Aug 2022–present |
| ESS-DIVE Deep Dive | `essdive_query`, `essdive_bbox_query` | ESS-DIVE token (free) | DOE field datasets | ✅ Phase 3, Step 3.3 |
| Google Earth Engine | `gee_query` | Google account + GEE project | Any GEE dataset | *(deferred — exploring free-tier alternatives)* |

**Not included** (covered by GeoTap): USGS NWIS, EPA ATTAINS, NOAA rainfall, NWI, FEMA.

---

## Data Licenses

Every source module must expose a `LICENSE_INFO` dict constant and populate `_meta.license` and `_meta.license_url` on every response. This makes license propagation automatic — callers never need to look it up manually.

```python
# Pattern in each source module, e.g. sources/nasa_power.py
LICENSE_INFO = {
    "license": "Public domain (NASA/US Government). Citation requested.",
    "license_url": "https://power.larc.nasa.gov/docs/services/terms-conditions/",
    "citation": (
        "These data were obtained from the NASA Langley Research Center (LaRC) POWER Project "
        "funded through the NASA Earth Science/Applied Science Program."
    ),
}
```

### Per-source license details

| Source | License | Key constraint | Citation required? |
|---|---|---|---|
| **NASA POWER** | Public domain (US Govt) | None — but NASA requests acknowledgment | Yes — see citation text in NASA_POWER.LICENSE_INFO |
| **SSURGO** | Public domain (USDA) | None | No — but attribution to USDA NRCS is good practice |
| **SoilGrids v2** | CC BY 4.0 | Attribution required in any publication or product | Yes — cite ISRIC (https://www.isric.org/explore/soilgrids) |
| **GBIF occurrences** | Mixed — CC0, CC BY, CC BY-NC per record | `license` column present in each Parquet record; most-restrictive license in `_meta.license` | Cite GBIF occurrence download DOI when using CC BY/CC BY-NC records |
| **Sentinel-5P TROPOMI** | ESA Copernicus Open Access | Free use + distribution; attribution required | Yes — "Contains modified Copernicus Sentinel data [year]" |
| **OpenAQ** | CC BY 4.0 | Attribution required | Yes — cite OpenAQ (https://openaq.org) |
| **OCO-2/OCO-3** | Public domain (NASA/US Govt) | None | Yes — cite Jet Propulsion Laboratory and the OCO-2/3 Science Team |
| **EMIT** | Public domain (NASA/US Govt) | None | Yes — cite NASA JPL EMIT mission |
| **ESS-DIVE** | Varies per dataset package | Extract `license` from dataset metadata at query time; propagate in `_meta` | Per-dataset — available in ESS-DIVE metadata |
| **GEE datasets** | Varies per dataset | Extract from Earth Engine catalog `ee.Image.getInfo()` `properties.license` | Per-dataset |

### Implementation requirements for mixed-license sources

**GBIF**: The Parquet schema includes a `license` column per occurrence. After filtering to the spatial/temporal query, compute `unique_licenses = df["license"].unique().tolist()` and set:

```python
"license": " | ".join(unique_licenses),
"license_url": "https://www.gbif.org/terms",
```

**ESS-DIVE**: Call `GET /api/v1/datasets/{id}` to retrieve `dataset.license` before returning data. Propagate the verbatim string.

**GEE**: After resolving the dataset, call `ee.data.getAsset(dataset_id)` and extract `properties.license` if present, else fall back to `"See https://developers.google.com/earth-engine/datasets"`.

### `LICENSES.md`

Include a top-level `LICENSES.md` file in the package (in addition to `LICENSE` which covers the `env-data-mcp` package code itself). `LICENSES.md` lists each upstream data source, its license, and its citation text. This file is human-readable documentation to accompany any derived dataset or publication. Template:

```markdown
# Data Source Licenses

This package retrieves data from third-party sources. Each source has its own
license and attribution requirements, which are also propagated in `_meta.license`
on every tool response.

## NASA POWER
License: Public domain (US Government work)
Attribution requested: "These data were obtained from the NASA Langley Research
Center (LaRC) POWER Project funded through the NASA Earth Science/Applied
Science Program."
Terms: https://power.larc.nasa.gov/docs/services/terms-conditions/

## SSURGO ...
```

---

## Variable Metadata Standards

Every source module must expose a `VARIABLE_INFO` constant (a dict of variable-name → metadata dict) and include a filtered copy in every tool response under `_meta.variable_info`. This ensures that any LLM or downstream consumer can interpret values without needing external documentation.

### Required format

```python
# Pattern in each source module
VARIABLE_INFO: dict[str, dict[str, str]] = {
    "T2M": {
        "description": "Air temperature at 2 meters above ground",
        "units": "°C",
        "valid_range": "−90 to 60",
    },
    "PRECTOTCORR": {
        "description": "Bias-corrected total precipitation",
        "units": "mm/day",
        "valid_range": "0 to ~300",
    },
    # ...
}
```

### Including in `_meta`

`build_meta()` accepts a `variable_info` keyword argument. Pass the slice of `VARIABLE_INFO` corresponding to the requested variables:

```python
build_meta(
    source="nasa_power",
    ...,
    variables=variables,
    variable_info={k: VARIABLE_INFO[k] for k in variables if k in VARIABLE_INFO},
)
```

The resulting `_meta` will contain:
```json
"variable_info": {
  "T2M": {"description": "Air temperature at 2 m above ground", "units": "°C", "valid_range": "−90 to 60"},
  "PRECTOTCORR": {"description": "Bias-corrected total precipitation", "units": "mm/day", "valid_range": "0 to ~300"}
}
```

### Testing variable metadata

Every source unit test must assert:
1. `_meta.variable_info` is present and non-empty
2. Each requested variable appears as a key in `variable_info`
3. `variable_info[var]["units"]` matches the `{var}_units` values in the data records
4. Numeric values in data records fall within the documented `valid_range`

---

## Graceful Upstream Failure Handling

Every source tool must return a structured error response (never raise an unhandled exception) when the upstream data source is unavailable, returns an error, or changes its schema unexpectedly. This lets multi-source workflows continue running even when individual sources are down.

### Required pattern

```python
@mcp.tool()
def source_query(latitude, longitude, ...) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        data, latency = _fetch(latitude, longitude)
        ...
        return {"data": data, "_meta": build_meta(..., success=True)}
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],   # or {} for single-record sources
            "_meta": build_meta(
                ...,
                latency_s=latency,   # always capture latency even on error
                success=False,
                error=str(exc),
            ),
        }
```

Key rules:
- **Always capture `latency`** even when an exception is raised (use `time.perf_counter() - t0` in the `except` block, not a hardcoded `0.0`)
- **Never re-raise** — the caller must be able to inspect `_meta.success` and `_meta.error` without catching exceptions
- **Distinguish service-down from empty results**: HTTP 4xx/5xx or network errors → `success=False, error=<exception text>`; empty spatial coverage → `success=True, data=[], error="No data for this location"`
- **Integration tests for externally-hosted APIs** must include an availability guard that skips all tests in the module when the upstream service is unreachable (rather than failing with confusing assertion errors):

```python
@pytest.fixture(scope="module", autouse=True)
def _require_api_available() -> None:
    try:
        r = httpx.get(API_HEALTH_URL, timeout=5)
        if r.status_code >= 500:
            pytest.skip(f"API returned HTTP {r.status_code} — service may be paused")
    except Exception as exc:
        pytest.skip(f"API not reachable: {exc}")
```

---

## Query Optimization

Every source implementation must include an explicit optimization step. Environmental data sources are large (global grids, multi-decade time series, high-resolution imagery) and naive queries can fetch orders of magnitude more data than needed. The optimization step is **not optional** and must be completed before the source module is considered done.

### Optimization checklist for each source

1. **Slice before loading** — for array/raster sources (Zarr, NetCDF, WCS), always narrow the time and space dimensions *before* downloading chunks. Never load the full array and filter in memory.
2. **Minimize S3 round-trips** — fetch only the zarr chunks that contain the requested spatial cells and time steps. One well-constructed slice request can replace thousands of individual chunk fetches.
3. **Cache expensive metadata** — coordinate arrays (lat/lon/time) that don't change between calls should be loaded once and cached at module level.
4. **Enforce size caps on unbounded queries** — any query that could return an unbounded number of rows (GBIF, OpenAQ) must enforce a `limit` parameter and report `_meta.capped = True` when the cap is reached.
5. **Document the optimization** — add a comment in the source code explaining *what* was optimized and *why* (e.g., `# Slice time dimension first — arr[:, lat_idx, lon_idx] loads 40+ years; t_start:t_end limits to requested window`).

### Per-source optimization notes (Phase 1)

**NASA POWER (Zarr/S3)**:
- Open the store once per process and cache the `zarr.Group` at module level — S3 metadata roundtrips on every call are expensive
- Decode the time coordinate once and cache it alongside the group (or at minimum avoid redundant `group["time"][:]` loads when the group is already open)
- Use `arr[t_start:t_end, lat_idx, lon_idx]` not `arr[:, lat_idx, lon_idx]` — the full MERRA-2 daily record is 40+ years; narrow the time window to only the requested date range before pulling chunks
- The `CacheStore` wrapper means repeated queries over the same chunks are served from RAM instead of S3 — warm-cache queries should be near-instant

**SSURGO (SDA REST)**:
- The SQL query already joins component + horizon in a single POST, avoiding multiple round-trips
- The query uses `SDA_Get_Mukey_from_intersection_with_WktWgs84()` which is server-side; no client-side spatial filtering needed
- Only `majcompflag = 'Yes'` rows are returned — avoid fetching all components for a map unit

**SoilGrids (REST or WCS)**:
- Batch all properties in a single request rather than one request per property (the REST API accepts `property` as a repeatable parameter)
- If switching to WCS: use tight bounding boxes (single pixel or small buffer), not continent-wide extents

---

## Package Structure

```
env-data-mcp/
├── pyproject.toml              # Package config; entry point: env-data-mcp
├── README.md                   # Installation, credential setup, .mcp.json snippet
├── LICENSES.md                 # Per-source license and citation text (see Data Licenses)
├── .env.example                # Template: EARTHDATA_TOKEN, OPENAQ_API_KEY (ESS-DIVE and GEE deferred)
├── src/
│   └── env_data_mcp/
│       ├── __init__.py
│       ├── server.py           # MCP server entry point; @mcp.tool() registrations
│       ├── models.py           # Pydantic input schemas (BboxInput, PointInput, etc.)
│       ├── helpers.py          # Shared utilities (see Reproducibility Practices)
│       └── sources/
│           ├── __init__.py
│           ├── nasa_power.py   # Zarr S3 adapter; LICENSE_INFO constant
│           ├── ssurgo.py       # REST/WFS adapter; LICENSE_INFO constant
│           ├── soilgrids.py    # WCS adapter; LICENSE_INFO constant
│           ├── gbif.py         # anonymous S3 Parquet adapter; LICENSE_INFO constant
│           ├── sentinel5p.py   # no-sign S3 adapter; LICENSE_INFO constant
│           ├── openaq.py       # REST adapter; LICENSE_INFO constant
│           ├── oco2.py         # OPeNDAP + bearer token adapter; LICENSE_INFO constant
│           ├── emit.py         # OPeNDAP + bearer token adapter; LICENSE_INFO constant
│           ├── essdive.py      # REST adapter; LICENSE_INFO constant
│           └── gee.py          # Earth Engine Python API adapter; LICENSE_INFO constant
├── notebooks/
│   ├── grow_point_sample_demo.ipynb    # GROW use case: 5 samples × all no-auth sources
│   ├── pnnl_bbox_demo.ipynb            # PNNL use case: bbox × date range × NASA POWER
│   └── api_smoke_test.ipynb            # One call per source; used for manual API health checks
└── tests/
    ├── conftest.py             # GROW and PNNL fixtures; shared mock factories
    ├── unit/                   # No network; mock all HTTP/S3 calls (fast, run on every PR)
    │   ├── test_helpers.py
    │   ├── test_nasa_power.py
    │   ├── test_ssurgo.py
    │   ├── test_soilgrids.py
    │   ├── test_gbif.py
    │   ├── test_sentinel5p.py
    │   ├── test_openaq.py
    │   └── test_models.py
    └── integration/            # Real API calls; marked @pytest.mark.integration
        ├── test_nasa_power_live.py
        ├── test_ssurgo_live.py
        ├── test_soilgrids_live.py
        ├── test_gbif_live.py
        ├── test_sentinel5p_live.py
        ├── test_openaq_live.py
        ├── test_oco2_live.py       # requires EARTHDATA creds
        ├── test_emit_live.py       # requires EARTHDATA creds
        ├── test_essdive_live.py    # requires ESSDIVE_TOKEN  [DEFERRED]
        └── test_gee_live.py        # requires GOOGLE_APPLICATION_CREDENTIALS  [DEFERRED]
```

### `pyproject.toml` key dependencies

```toml
[project]
name = "env-data-mcp"
requires-python = ">=3.10"
dependencies = [
    "mcp>=1.0",
    "xarray>=2024.0",
    "zarr>=3.0",
    "s3fs>=2024.0",
    "httpx>=0.27",
    "pydantic>=2",
    "pandas>=2.0",
    "earthengine-api>=0.1.400",     # for GEE
    "numpy>=1.26",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-httpx>=0.30",           # mock httpx calls in unit tests
    "moto[s3]>=5.0",                # mock S3 in unit tests
    "nbmake>=1.5",                  # test notebooks
    "pytest-cov",
]

[project.scripts]
env-data-mcp = "env_data_mcp.server:main"

[tool.pytest.ini_options]
testpaths = ["tests", "notebooks"]
addopts = ["--cov=env_data_mcp", "--cov-report=term-missing", "--nbmake",
           "--nbmake-timeout=300", "--ignore=notebooks/api_smoke_test.ipynb"]
markers = [
    "integration: real API calls; requires network (deselect with -m 'not integration')",
    "smoke: one live call per source to verify connectivity",
]
```

GitHub Actions CI:
- **`test.yml`** (every PR): `pytest tests/unit/ -m "not integration"` — no credentials needed, fast (\< 60 s)
- **`integration.yml`** (nightly, `cron: "0 6 * * *"`): `pytest tests/integration/` — credentials injected from GitHub Secrets. Failures page the maintainer and indicate upstream API changes.
- **`notebooks.yml`** (weekly, `cron: "0 8 * * 1"`): `pytest notebooks/ --nbmake` on no-auth notebooks only; auth-required notebooks excluded via `--ignore`.

---

## Credential Handling

Auth-required tools check for credentials at call time:

1. Read from environment variables (set in `.mcp.json` `env` block or loaded from `.env`)
2. If missing: return `{"data": [], "_meta": {"success": false, "auth_required": true, "auth_present": false, "error": "<setup message>"}}` — do not raise an unhandled exception. This allows the caller to log the auth friction and continue with other sources.
3. Never hard-code credentials; always read auth from env vars (never from files on disk)

```python
# Pattern for auth-required tools
@mcp.tool()
def oco2_query(latitude, longitude, start_date, end_date):
    token = os.environ.get("EARTHDATA_TOKEN")
    if not token:
        return {
            "data": [],
            "_meta": {
                "source": "oco2", "auth_required": True, "auth_present": False,
                "success": False, "rows_returned": 0, "latency_s": 0,
                "error": "EARTHDATA_TOKEN required. "
                         "Register free at https://urs.earthdata.nasa.gov/ then generate "
                         "a token under Profile → Generate Token."
            }
        }
    headers = {"Authorization": f"Bearer {token}"}
    # Pass headers= to every httpx / requests call that hits urs.earthdata.nasa.gov
    # or any EDL-integrated OPeNDAP endpoint (e.g. opendap.earthdata.nasa.gov).
    ...
    return {"data": records, "_meta": {"source": "oco2", "auth_required": True,
                                        "auth_present": True, "success": True, ...}}
```

**Expired token handling**

EarthData bearer tokens expire every few months. An expired token returns HTTP 401 — the same status as an absent token. Always check for 401 *after* confirming the token is present, so the error message tells the user to *regenerate* rather than *register*:

```python
token = os.environ.get("EARTHDATA_TOKEN")
if not token:
    return auth_missing_response(source, ...)  # token never set up

resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
if resp.status_code == 401:
    return {
        "data": [],
        "_meta": {
            "source": source, "auth_required": True, "auth_present": True,
            "success": False, "rows_returned": 0, "latency_s": elapsed,
            "error": (
                "EarthData token rejected (HTTP 401) — token may be expired. "
                "Tokens expire every few months. Regenerate at "
                "https://urs.earthdata.nasa.gov/ → Profile → Generate Token "
                "and update EARTHDATA_TOKEN in .env."
            ),
        },
    }
resp.raise_for_status()
```

Key distinction: `auth_present=True` (the env var is set) but `success=False` (the token was rejected). This lets callers and logs distinguish "user hasn't registered" from "user needs to renew their token".

NASA EarthData supports bearer tokens for all EDL-compliant applications (including OPeNDAP).
A bearer token is preferred over username/password: it is a single env var, requires no
`~/.netrc`, and can be revoked without changing your password.
Generate a token at: https://urs.earthdata.nasa.gov/ → Profile → Generate Token.

| Source | Env var | Registration URL |
|---|---|---|
| OCO-2, EMIT | `EARTHDATA_TOKEN` | https://urs.earthdata.nasa.gov/ |
| OpenAQ | `OPENAQ_API_KEY` | https://explore.openaq.org/ |
| ESS-DIVE | `ESSDIVE_TOKEN` | https://data.ess-dive.lbl.gov/ |
| GEE *(deferred)* | `GOOGLE_APPLICATION_CREDENTIALS` | https://console.cloud.google.com/ + GEE project approval |

---

## Reproducibility Practices

The goal is for every result to be exactly reproducible from a log record alone.

### `helpers.py` — shared utilities

All cross-source utilities live in `src/env_data_mcp/helpers.py`. Every source module imports from here; no source module reimplements these.

```python
# src/env_data_mcp/helpers.py  (abbreviated interface)

def parse_date(date_str: str) -> datetime.date:
    """Parse ISO 8601 date string to date. Raises ValueError with a clear message."""

def bbox_centroid(bbox: dict) -> tuple[float, float]:
    """Return (lat, lon) centroid of a bbox dict (min_lat/max_lat/min_lon/max_lon)."""

def bbox_to_wkt_polygon(bbox: dict) -> str:
    """Return WKT POLYGON string for SSURGO/GBIF spatial queries."""

def build_meta(
    source: str,
    query_params: dict,
    rows_returned: int,
    latency_s: float,
    license_info: dict,
    *,
    auth_required: bool = False,
    auth_present: bool = True,
    success: bool = True,
    error: str | None = None,
    variables: list[str] | None = None,
) -> dict:
    """Construct the standard _meta dict. All source modules call this."""

def auth_missing_response(source: str, license_info: dict, error_msg: str, query_params: dict) -> dict:
    """Return the standard no-auth failure response without raising."""

def clamp_bbox(bbox: dict, *, max_degrees: float = 10.0) -> dict:
    """Warn and clamp oversized bboxes that would cause excessive data fetches."""
```

### Why `_meta.query_params` enables reproducibility

Every tool response echoes back the exact resolved inputs (after date parsing, bbox centroid computation, default substitution, etc.). A consumer can reconstruct *any* result by re-running the tool with exactly those parameters. This is especially important for the Lakehouse log: if a scientist wants to reproduce the NASA POWER values used in an analysis, they can replay the logged `query_params` directly.

### Dependency pinning

Use `uv lock` to maintain `uv.lock`. Never leave major version bounds open for data-access libraries (`zarr`, `s3fs`, `httpx`); upstream S3 path structures or API schemas can shift between minor versions. When an integration test fails due to a schema change, update the pinned version and document what changed in `CHANGELOG.md`.

### Version tracking in `_meta`

Where a data source exposes a version, publication date, or DOI, include it:

```python
# e.g. SoilGrids returns version in WCS metadata
"_meta": { ..., "source_version": "SoilGrids v2.0 (2022-05)" }
# e.g. GBIF Parquet partition date
"_meta": { ..., "source_version": "gbif-open-data partition 2025-01-01" }
```

---

## Development Phases

> **Convention for each step**: When implementing a source module, always (a) extract shared logic into `helpers.py` first, (b) write unit tests with mocked HTTP/S3 before writing real API code, and (c) add the integration test immediately after verifying the real call works. The test is part of the implementation step, not a separate later task.

### Phase 0 — Scaffold and helper foundation

**Step 0.1 — Initialize the Python package**
- `uv init --lib` with `requires-python = ">=3.10"`; add `mcp`, `httpx`, `pydantic>=2`, `xarray`, `zarr`, `s3fs`, `pandas`, `numpy` to `[project.dependencies]`
- Add `[project.optional-dependencies] dev = [pytest, pytest-httpx, moto[s3], nbmake, pytest-cov]`
- Configure `[tool.pytest.ini_options]` with `testpaths`, markers, and `--nbmake`; add the `unit/` and `integration/` layout
- Create `src/env_data_mcp/server.py` with `mcp = FastMCP("env-data-mcp")` and a `main()` entry point
- Create `src/env_data_mcp/helpers.py` with `parse_date`, `bbox_centroid`, `bbox_to_wkt_polygon`, `build_meta`, `auth_missing_response`, and `clamp_bbox`
- Create `src/env_data_mcp/models.py` with `PointInput`, `BboxInput`, and `DateRange` Pydantic models
- **Tests to write**: `tests/unit/test_helpers.py` — full coverage of all helper functions including edge cases (invalid date, bbox inversion, missing fields)

**Step 0.2 — Create `LICENSES.md`**
- Populate with per-source license text and citation strings (can be stubs until source modules are implemented; fill in final citation text alongside each module)

**Step 0.3 — Create fixture data and `conftest.py`**
- Load first 5 rows of `grow_locations.txt` into `GROW_SAMPLES` constant (parse the `|`-delimited format, handle `NULL` Time values)
- Define `PNNL_BBOX`, `PNNL_START`, `PNNL_END` constants
- Add `pytest.fixture` for a single GROW sample (`yakimariver_2019`) used in per-module unit tests
- **Verify**: `pytest tests/unit/test_helpers.py` passes with no network calls

---

### Phase 1 — No-auth core: NASA POWER + SSURGO + SoilGrids

> No account registrations required for this phase.

**Step 1.1 — `nasa_power_query`**

*Reference*: `external-data-gallery/src/external_data_gallery/sources/nasa_zarr.py` + `weather-station-nasa-power.ipynb`

- Implement `sources/nasa_power.py`:
  - `load_store()` — open `s3://nasa-power/merra2/spatial/power_merra2_daily_spatial_utc.zarr` with `FsspecStore` + 256 MB `CacheStore` (exactly as in `nasa_zarr.py`)
  - `query_point(lat, lon, start_date, end_date, variables, temporal_resolution)` — extract array slices using nearest-index lookup for lat/lon, boolean mask for time; return list of `{"date": ..., variable: value, "units": ...}` dicts
  - `query_bbox(bbox, ...)` — use `bbox_centroid()` helper then delegate to `query_point()`
  - `LICENSE_INFO` constant (see Data Licenses)
- Register `@mcp.tool() def nasa_power_query(...)` in `server.py`; call `build_meta()` for `_meta`
- **Unit tests** (`tests/unit/test_nasa_power.py`): mock `FsspecStore.from_url` with `moto`; verify column names, date range bounds, `_meta` fields including `license` and `query_params`
- **Integration test** (`tests/integration/test_nasa_power_live.py`): one call with `yakimariver_2019` fixture; assert `len(data) == 1`, all 6 default variables present, `_meta.success == True`; assert `_meta.rows_returned > 0`. **This test will catch S3 path or schema changes.**
- **Notebook**: `notebooks/grow_point_sample_demo.ipynb` — first cell: NASA POWER for 5 GROW samples

**Step 1.2 — `ssurgo_query`**

*Reference*: `external-data-gallery/notebooks/weather-station-comparison/ssurgo/weather-station-ssurgo.ipynb`

- Implement `sources/ssurgo.py`:
  - `get_mapunit_for_point(lat, lon)` — `POST https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest` with `SoilDataMapper` query; use `httpx` async client
  - `get_component_and_horizon(mukey)` — tabular query for component + horizon data
  - Out-of-coverage handling: return `{"data": {}, "_meta": {..., "error": "No SSURGO data for this location (non-US or unmapped area)"}}` without raising
  - `LICENSE_INFO` constant
- **Unit tests**: mock `httpx.AsyncClient.post` with `pytest-httpx`; test both US and non-US coordinates; verify graceful out-of-coverage response
- **Integration test**: yakimariver (US) → expect non-empty data; Yukon_2004 (Alaska, should have coverage); add a non-US point (e.g., lat=51.5, lon=0.1) → expect graceful no-data response

**Step 1.3 — `soilgrids_query`**

*Reference*: `external-data-gallery` SoilGrids WCS adapter (check `notebooks/` for existing WCS pattern)

- Implement `sources/soilgrids.py`:
  - WCS `GetCoverage` request to `https://maps.isric.org/mapserv?map=/map/{property}.map` for each of: `sand`, `silt`, `clay`, `soc`, `phh2o`, `bdod`; use 0–5 cm depth by default
  - Parse GeoTIFF response with `rioxarray`; extract pixel value at (lat, lon)
  - `LICENSE_INFO` with CC BY 4.0 and ISRIC citation
- **Unit tests**: mock the WCS HTTP response with a tiny in-memory GeoTIFF
- **Integration test**: yakimariver point; assert all 6 properties present and in plausible ranges (e.g., sand 0–100%, pH 3–9)

**Step 1.4 — Optimize Phase 1 queries**

Apply the optimization checklist from [Query Optimization](#query-optimization) to all three sources:
- **NASA POWER**: verify `arr[t_start:t_end, lat_idx, lon_idx]` slicing is in place; profile a single-day query and confirm it completes in < 5 s on a cold cache (first open) and < 0.5 s on a warm cache
- **SSURGO**: confirm single-POST SQL join is in place; no further optimization needed for point queries
- **SoilGrids**: confirm all properties are fetched in one request (not one per property); verify `timeout` is set and not unbounded

**Step 1.5 — End-to-end Phase 1 test**
- Run `pytest tests/unit/` (zero network calls, \< 30 s)
- Run `pytest tests/integration/ -m integration -k "nasa_power or ssurgo or soilgrids"` against real APIs
- Start the MCP server locally and run a manual call (see [Local Testing Walkthrough](#local-and-lakehouse-testing))
- Add Phase 1 sources to `notebooks/grow_point_sample_demo.ipynb`; run all 5 GROW samples through all three sources; verify no uncaught exceptions

---

### Phase 2 — Remaining no-auth sources: GBIF + Sentinel-5P + OpenAQ

> No account registrations required for this phase.

**Step 2.1 — `gbif_occurrences`**

*Reference*: `external-data-gallery/src/external_data_gallery/sources/gbif_parquet.py`

- Implement `sources/gbif.py`:
  - Discover the most recent partition date by listing `s3://gbif-open-data-{region}/occurrence/` (region defaults to `us-east-1`; the `af-south-1` bucket in `external-data-gallery` is a regional mirror — use the canonical `gbif-open-data-us-east-1` for lowest latency)
  - Read Parquet with `dask`; filter by bounding box + date range + optional `taxonKey`; `.compute()` on filtered subset only
  - **License handling**: collect unique values from `license` column; populate `_meta.license` as `" | ".join(unique_licenses)` (see Data Licenses)
  - `bbox` mode: use polygon filter on `decimalLatitude`/`decimalLongitude`
  - Enforce a row cap (default `limit=1000`) to prevent unbounded Dask reads; include `_meta.capped = True` if cap was hit
  - `LICENSE_INFO` constant with GBIF citation DOI
- **Unit tests**: provide a tiny mock Parquet in `tests/fixtures/gbif_sample.parquet`; test license aggregation logic; test row cap
- **Integration test**: 50 km radius around yakimariver; assert `_meta.success`, assert `license` field in `_meta` is populated

**Step 2.2 — `sentinel5p_query`**

*Reference*: `gee-data-prompt.md` S3 no-sign pattern in BERIL repo (`~/git-repos/BERIL-research-observatory/gee-prompt.md`)

- Implement `sources/sentinel5p.py`:
  - Bucket: `s3://meeo-s5p` with `--no-sign-request` (use `s3fs.S3FileSystem(anon=True)`)
  - Folder structure: `OFFL/L2__CO___/{year}/{month}/{day}/` (similar for NO2 and CH4)
  - Download the relevant `.nc` granule(s) covering the query bbox; extract a spatial mean over the bbox
  - `LICENSE_INFO` with ESA Copernicus attribution string
- **Unit tests**: mock `s3fs.S3FileSystem`; test product path construction for each product type
- **Integration test**: PNNL bbox, May 2023, CO product; assert result has `column_amount_CO_dry_air` field

**Step 2.3 — `openaq_query`**

- Implement `sources/openaq.py`:
  - `GET https://api.openaq.org/v3/locations?coordinates={lat},{lon}&radius={radius_m}&parameters={params}`; then per-location `GET /v3/measurements?...&date_from=...&date_to=...`
  - Paginate results; enforce `limit=500` total rows
  - Handle sparse coverage gracefully: if no stations within radius, return `data=[]` with a descriptive `_meta.error` (not an exception)
  - `LICENSE_INFO` with CC BY 4.0 and OpenAQ URL
- **Unit tests**: mock `httpx` responses; test pagination logic; test sparse-coverage fallback
- **Integration test**: yakimariver 50 km radius, Aug 2019; assert `_meta.success` (data may be sparse — success = no exception, even if `rows_returned == 0`)

**Step 2.4 — End-to-end Phase 2 test**
- `pytest tests/unit/` — all six no-auth sources pass
- `pytest tests/integration/ -m integration -k "gbif or sentinel5p or openaq"`
- Extend `notebooks/grow_point_sample_demo.ipynb` to include all six no-auth sources for 5 GROW samples
- Run `notebooks/pnnl_bbox_demo.ipynb` for NASA POWER + Sentinel-5P over the PNNL bbox
- Register server in BERIL `.mcp.json` and run end-to-end GROW demo with BERIL skill (see [Lakehouse Integration Testing](#local-and-lakehouse-testing))

---

### Phase 3 — Auth-required sources

> **Account registration steps are called out below. Read ahead and complete registrations before starting each step — some require approval time.**

**⚠️ Account registration: NASA EarthData (do before Step 3.1)**

Required for `oco2_query` (Step 3.1) and `emit_query` (Step 3.2).

1. Register at https://urs.earthdata.nasa.gov/ (free, instant)
2. Under "Applications" → "Authorized Apps", approve "NASA GESDISC DATA ARCHIVE" and "EARTHDATA OPENDAP"
3. Generate a bearer token: Profile → Generate Token (up to 2 active tokens at a time)
4. Add `EARTHDATA_TOKEN=<token>` to `.env`
5. Verify: `curl -H "Authorization: Bearer <token>" https://opendap.earthdata.nasa.gov/` returns a directory listing, not a 401

**Step 3.1 — `oco2_query`**

- Implement `sources/oco2.py`:
  - Target: OCO-2 Level 3 monthly XCO2 via OPeNDAP at `https://opendap.earthdata.nasa.gov/providers/GES_DISC/collections/OCO2_L3CO2_7r.10.3/granules/`
  - Use `httpx` with `headers={"Authorization": f"Bearer {token}"}` for all OPeNDAP requests; read token from `EARTHDATA_TOKEN` env var
  - `LICENSE_INFO` constant
- **Unit tests**: mock the OPeNDAP URL response (a small synthetic NetCDF fixture)
- **Integration test**: yakimariver, Aug 2019; assert `xco2` column present, values in 390–430 ppm range

**⚠️ Account registration: same NASA EarthData credentials work for EMIT**

No additional registration needed. EMIT uses the same `EARTHDATA_TOKEN`.

**Step 3.2 — `emit_query`**

- Implement `sources/emit.py`:
  - Target: EMIT L2B Mineral spectral unmixing via NASA CMR search + OPeNDAP download
  - CMR search: `GET https://cmr.earthdata.nasa.gov/search/granules?short_name=EMITL2BMIN&bounding_box={west},{south},{east},{north}&temporal={start},{end}`
  - For each matching granule, fetch the OPeNDAP `.nc4` and extract the bounding pixel
  - Return records with `mineral_name`, `abundance`, `granule_id`
  - `LICENSE_INFO` constant

**Step 3.3 — `essdive_query` + `essdive_bbox_query`** ✅ Complete

- Implement `sources/essdive.py`:
  - API base: `https://api.ess-dive.lbl.gov/packages` (Bearer token auth)
  - Point search: `GET /packages?lat={lat}&lon={lon}&radius={radius_m}&isPublic=true`
  - Bbox search: `GET /packages?bbox={min_lat},{min_lon},{max_lat},{max_lon}&isPublic=true`
  - Optional: `beginDate`, `endDate`, `text` free-text filter, `pageSize` (max 100), cursor pagination
  - Each result includes `license` in the `dataset` object — aggregate unique licenses into `_meta.license`
  - Extract per-dataset: `doi`, `title`, `license`, `date_published`, `temporal_start/end`, `keywords`, `variables_measured`, `description`, `url`
  - `LICENSE_INFO` stub: `{"license": "Varies per dataset; see _meta.license", "license_url": "https://data.ess-dive.lbl.gov"}`

> **⚠️ DEFERRED:** GEE free-tier options are still being evaluated. Resume Step 3.4 when a solution is confirmed.

**⚠️ Account registration: Google / GEE (do before Step 3.4 — may take 1–3 days for approval)**

Required for `gee_query`.

1. Sign in at https://earthengine.google.com/signup/ with a Google account
2. Request access to Google Earth Engine (non-commercial use; approval is usually \< 24 h)
3. Create a service account in Google Cloud Console → IAM → Service Accounts
4. Download the JSON key; save to a stable path (e.g., `~/.config/gee/credentials.json`)
5. Add to `.env`: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json`
6. Also set `GEE_PROJECT=<your cloud project id>`
7. Verify: `python -c "import ee; ee.Initialize(); print(ee.Image('COPERNICUS/S2').getInfo())"`

**Step 3.4 — `gee_query`** *(DEFERRED)*

*Reference*: `external-data-gallery/notebooks/earth-engine/alpha-earth.ipynb`

- Implement `sources/gee.py`:
  - `ee.Initialize(project=os.environ["GEE_PROJECT"])` at call time (lazy; not at import)
  - For point queries: `ee.Image(dataset).select(bands).sample(ee.Geometry.Point([lon, lat]), ...)`.getInfo()``
  - For bbox queries: `ee.ImageCollection(dataset).filterBounds(ee.Geometry.Rectangle(...)).filterDate(...).mean().reduceRegion(...)`
  - Handle `dataset` as an Earth Engine asset ID string (e.g., `"COPERNICUS/S2_SR_HARMONIZED"`)
  - `LICENSE_INFO` stub: `{"license": "Varies by dataset; check Earth Engine Data Catalog", "license_url": "https://developers.google.com/earth-engine/datasets"}`
  - Attempt to extract dataset-specific license from `ee.data.getAsset(dataset)` `properties`
- **Unit tests**: mock `ee.Initialize` and the GEE client; verify auth-missing response when env vars absent
- **Integration test**: yakimariver, Sentinel-2 SR, Aug 2019, bands `["B4", "B3", "B2"]`

**Step 3.5 — End-to-end Phase 3 test**
- `pytest tests/integration/ -m integration` — all 9 active sources pass (GEE deferred)
- Update `notebooks/grow_point_sample_demo.ipynb` to include auth-required sources for at least 2 GROW samples
- Review `LICENSES.md` — fill in any remaining citation stubs now that all modules are implemented

---

### Phase 4 — Automated testing infrastructure and CI

**Step 4.1 — GitHub Actions: unit test workflow**

Create `.github/workflows/test.yml`:
- Trigger: every push and PR
- Matrix: Python 3.10, 3.12
- Steps: `uv sync --extra dev`, `pytest tests/unit/ -m "not integration"`, upload coverage report
- No secrets needed; should pass in \< 60 s

**Step 4.2 — GitHub Actions: nightly integration workflow**

Create `.github/workflows/integration.yml`:
- Trigger: `cron: "0 6 * * *"` + manual `workflow_dispatch`
- Store all credentials as GitHub Secrets: `EARTHDATA_TOKEN`, `OPENAQ_API_KEY`, `ESSDIVE_TOKEN` (GEE is deferred; add its secret when resumed)
- Steps: decode GEE key to file, `pytest tests/integration/ -m integration --tb=short`
- On failure: create a GitHub Issue with the failure summary (use `actions/github-script`)
- **Purpose**: flags upstream API changes within 24 hours so you know before users do

**Step 4.3 — GitHub Actions: weekly notebook workflow**

Create `.github/workflows/notebooks.yml`:
- Trigger: `cron: "0 8 * * 1"` (Monday morning)
- Run: `pytest notebooks/ --nbmake --ignore=notebooks/api_smoke_test.ipynb` (no auth notebooks only)
- Ensures example notebooks don't silently break as dependencies update

**Step 4.4 — Schema stability assertions in integration tests**

Each integration test must include assertions beyond "it returned something":

```python
# Example: test_nasa_power_live.py
def test_nasa_power_schema_stable(yakimariver_fixture):
    result = nasa_power_query(**yakimariver_fixture)
    assert result["_meta"]["success"]
    data = result["data"]
    assert len(data) == 1
    row = data[0]
    # These assertions fail if NASA changes variable names or units
    assert "T2M" in row, "T2M variable missing — upstream schema may have changed"
    assert "units" in row, "units field missing"
    assert -50 < row["T2M"] < 60, f"T2M out of plausible range: {row['T2M']}"
    assert result["_meta"]["license"] != "", "license field empty"
    assert "latitude" in result["_meta"]["query_params"]
```

---

### Phase 5 — Packaging, documentation, and BERIL integration

**Step 5.1 — `README.md`**

Sections:
1. What this is (one paragraph)
2. **Hello-world example** — a minimal, copy-paste-runnable example that verifies the server works before any BERIL setup. Place this near the top of the README so it's the first thing a new user tries:
   ```bash
   # Install
   git clone https://github.com/<org>/env-data-mcp.git
   cd env-data-mcp
   uv sync

   # Start the server (stdio transport; runs until killed)
   uv run env-data-mcp
   ```
   Then show a self-contained Python snippet using the `mcp` client that calls `nasa_power_query` and prints the result — no BERIL, no credentials, no Spark:
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
                   "nasa_power_query",
                   arguments={
                       "latitude": 46.253,
                       "longitude": -119.477,
                       "start_date": "2023-05-01",
                       "end_date": "2023-05-03",
                   },
               )
               print(result)

   asyncio.run(main())
   ```
   Include the expected output shape so the reader knows what "working" looks like.

3. **Build and test instructions** — a dedicated section titled "Development":
   ```bash
   # Install with dev dependencies
   uv sync --extra dev

   # Run fast unit tests (no network required)
   uv run pytest tests/unit/ -m "not integration" -v

   # Run integration tests against real APIs (requires network)
   uv run pytest tests/integration/ -m integration -v

   # Run example notebooks
   uv run pytest notebooks/ --nbmake

   # Check test coverage
   uv run pytest tests/unit/ --cov=env_data_mcp --cov-report=html
   open htmlcov/index.html
   ```
   Also note which CI checks run automatically (unit tests on every PR, integration tests nightly).

4. Quick start: `uvx --from /path/to/env-data-mcp env-data-mcp`
5. `.mcp.json` snippets for VS Code (local dev) and BERIL JupyterHub
6. Credential setup — one subsection per auth-required source with exact commands
7. Data licenses — brief table linking to `LICENSES.md`
8. Contributing — how to add a new source (checklist: module, `LICENSE_INFO`, unit test, integration test, `LICENSES.md` entry, notebook cell)

**Step 5.2 — `.env.example`**

```bash
# NASA EarthData (OCO-2, EMIT) — generate token at https://urs.earthdata.nasa.gov/
EARTHDATA_TOKEN=

# ESS-DIVE
ESSDIVE_TOKEN=

# Google Earth Engine [DEFERRED]
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/gee-credentials.json
# GEE_PROJECT=
```

**Step 5.3 — BERIL integration prompt document**

Rather than directly editing the BERIL repo, produce a self-contained prompt document at
`beril-env-data-prompt.md` (in this repo, sibling to this file) that can be dropped into a fresh
Copilot session with the BERIL repo loaded. The document should be fully self-contained — the
Copilot session reading it will have no access to this session's history.

The prompt document must cover:

1. **What `env-data-mcp` is** — one paragraph summary, entry-point command, response schema
   (`data` + `_meta`), and a pointer to the published README for full tool reference.

2. **`.mcp.json` registration** — concrete JSON blocks for two environments:
   - *Local dev* (VS Code + `uv`): `"command": "uv"`, `"args": ["--directory", "<path>", "run", "env-data-mcp"]`
   - *Lakehouse / JupyterHub*: `uvx --from <wheel-or-git-url> env-data-mcp` variant, with the env
     block for `EARTHDATA_TOKEN`, `OPENAQ_API_KEY`, `ESSDIVE_TOKEN`

3. **BERIL skill (`SKILL.md`)** — instructions for creating
   `.claude/skills/env-data/SKILL.md` in the BERIL repo, covering:
   - When to invoke `env-data-mcp` tools vs. GeoTap vs. Lakehouse `refdata_env_*` tables (check
     Lakehouse first; fall back to MCP)
   - How to load GROW sample locations (on-cluster: Spark SQL `SELECT * FROM grow.samples`;
     off-cluster: read `grow_locations.txt`)
   - How to write `_meta` to the usage log (`kbase_ops.env_query_log` on-cluster, or
     `~/.beril/env_query_log.jsonl` off-cluster as a JSONL fallback)
   - Example agentic workflow: for each GROW sample, call `nasa_power_query` + `soilgrids_query`,
     merge results, write log row, return enriched DataFrame

4. **Local testing options** — step-by-step for verifying the integration *without* Lakehouse access:
   - Start the server with `uv run env-data-mcp` (stdio) and run the hello-world snippet from the
     `env-data-mcp` README against it
   - Use VS Code MCP inspector (`Cmd+Shift+P → MCP: List Tools`) to browse and call tools manually
   - Run the BERIL skill against `grow_locations.txt` (off-cluster path) and inspect
     `~/.beril/env_query_log.jsonl` to verify log rows are written

5. **Lakehouse testing options** — step-by-step for verifying the full on-cluster path:
   - Deploy server to JupyterHub via `uvx` (exact command + env vars)
   - Run a single GROW sample enrichment query via the skill and confirm a row appears in
     `kbase_ops.env_query_log`
   - Run the demo notebook (reference the notebook path in the BERIL repo once created)

6. **Documentation to add in the BERIL repo**:
   - Update the top-level `README.md` "External data sources" section to list the MCP tools
   - Add `env-data-mcp` to whatever dependency/setup docs exist for onboarding new contributors

**Step 5.4 — PyPI publishing** *(deferred — out of scope for now)*

~~Once the package is stable, publish to PyPI to enable `uvx env-data-mcp` without a local clone~~

---

## Test Fixtures

Use these in `tests/conftest.py` to drive all tests consistently.

### GROW point-samples fixture (first 5 rows)

Parsed from the `|`-delimited `grow_locations.txt` — handle `NULL` Time values by defaulting to date-level daily queries.

```python
GROW_SAMPLES = [
    {"sample_name": "Yukon_2004-3",      "date": "2004-06-15", "latitude": 61.933, "longitude": -162.867},
    {"sample_name": "Yukon_2004-1",      "date": "2004-04-07", "latitude": 61.933, "longitude": -162.867},
    {"sample_name": "yakimariver_2019",  "date": "2019-08-19", "latitude": 46.253, "longitude": -119.477},
    {"sample_name": "whiteclaycreek2",   "date": "2019-08-12", "latitude": 39.859, "longitude": -75.784},
    {"sample_name": "whiteclaycreek1",   "date": "2019-08-12", "latitude": 39.858, "longitude": -75.783},
]
```

Full file: `~/git-repos/external-data-gallery/examples/grow_locations.txt`

### PNNL bbox fixture

```python
PNNL_BBOX = {
    "min_lat": 46.251407, "max_lat": 46.251790,
    "min_lon": -119.728785, "max_lon": -119.728369
}
PNNL_START = "2023-05-01"
PNNL_END   = "2023-06-01"
```

Full file: `~/git-repos/external-data-gallery/examples/pnnl_field_locations.txt`

---

## Automated Testing Strategy

### Test hierarchy

| Layer | Location | Speed | Network | When it runs |
|---|---|---|---|---|
| **Unit** | `tests/unit/` | \< 30 s | Never (all mocked) | Every PR |
| **Integration** | `tests/integration/` | 2–10 min | Yes (real APIs) | Nightly cron + manual |
| **Notebook** | `notebooks/` (via nbmake) | 5–15 min | Yes (no-auth only) | Weekly |
| **Smoke** | `notebooks/api_smoke_test.ipynb` | 1–3 min | Yes (one call/source) | Run manually before releases |

### Unit test design

Every source module's unit test uses `pytest-httpx` (for `httpx`-based REST adapters) or `moto[s3]` (for S3-based sources) to intercept all network calls. Tests must be completely deterministic and pass offline.

```python
# Example pattern for an httpx-based adapter
import pytest
from pytest_httpx import HTTPXMock
from env_data_mcp.sources.openaq import fetch_openaq

def test_openaq_returns_expected_shape(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url__startswith="https://api.openaq.org/v3/locations",
        json={"results": [{"id": 123, "name": "Test Station"}]}
    )
    httpx_mock.add_response(
        url__startswith="https://api.openaq.org/v3/measurements",
        json={"results": [{"value": 12.5, "parameter": "pm25", "date": {"utc": "2019-08-19T00:00:00Z"}}]}
    )
    result = fetch_openaq(latitude=46.253, longitude=-119.477, radius_km=50,
                          start_date="2019-08-19", end_date="2019-08-19")
    assert result["_meta"]["success"]
    assert result["_meta"]["license"] != ""
    assert result["_meta"]["query_params"]["latitude"] == 46.253
```

### Integration test design: API change detection

Integration tests must include **schema stability assertions** that will fail if the upstream API renames a field, changes a URL, or alters units. This is the primary mechanism for detecting upstream changes.

**Value-range assertions** are required for all numeric variables. These catch unit changes (e.g., if a variable switches from °C to K) as well as fill-value leakage:

```python
# Annotate each assertion with what it's detecting
assert "T2M" in row, "NASA POWER: T2M variable renamed or removed"
assert row["T2M_units"] == "C", "NASA POWER: T2M units changed from Celsius"
assert -90.0 <= row["T2M"] <= 60.0, f"NASA POWER: T2M={row['T2M']} outside physical range — fill value or unit change?"
assert "decimalLatitude" in gbif_row, "GBIF Parquet schema: column renamed"
assert result["_meta"]["rows_returned"] > 0, "OpenAQ: no data for known-active station area"
```

**Variable metadata assertions** verify the `_meta.variable_info` dict is populated and consistent with data values:

```python
assert "variable_info" in result["_meta"]
info = result["_meta"]["variable_info"]
assert "T2M" in info
assert info["T2M"]["units"] == row["T2M_units"], "variable_info units disagree with data row units"
```

Unit tests must include these same assertions against mock data, so any code change that breaks value semantics is caught before reaching integration tests.
3. If upstream changed: update the adapter, bump the pinned dependency if needed, update the assertion with the new expected value, and note the change in `CHANGELOG.md`

### Mocking S3 sources

For NASA POWER and GBIF, use `moto` to mock the S3 interactions:

```python
import boto3
from moto import mock_aws

@mock_aws
def test_nasa_power_unit():
    # Create a fake S3 bucket with a small synthetic Zarr store
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="nasa-power")
    # ... upload synthetic zarr metadata and arrays
    result = nasa_power_query(latitude=46.253, longitude=-119.477,
                               start_date="2019-08-19", end_date="2019-08-19")
    assert result["_meta"]["success"]
```

For Sentinel-5P, mock the `s3fs.S3FileSystem` listing and file download similarly.

### Notebook testing

`nbmake` re-executes each notebook cell by cell. All no-auth notebooks are included in the weekly CI run. Auth-required notebooks are excluded from automated CI but can be run manually.

Notebooks must not use hardcoded absolute paths. Use `pathlib.Path(__file__).parent` relative paths or environment variables. This ensures notebooks run in both local and JupyterHub environments.

---

## Account Registrations Timeline

Complete these in order before starting the corresponding implementation step. Include a personal note of your username and the account email in your password manager — you will need them for GitHub Secrets setup in Phase 4.

| When | Service | URL | Time to access | What you get |
|---|---|---|---|---|
| **Before Phase 3, Step 3.1** | NASA EarthData | https://urs.earthdata.nasa.gov/ | Instant | `EARTHDATA_TOKEN`; generate under Profile → Generate Token; needed for OCO-2 and EMIT |
| Before Phase 3, Step 3.3 | ESS-DIVE | https://data.ess-dive.lbl.gov/ | Instant | ✅ Registered — `ESSDIVE_TOKEN` added to `.env` |
| ~~Before Phase 3, Step 3.4~~ | Google Earth Engine | https://earthengine.google.com/signup/ | — | **DEFERRED** — exploring free-tier alternatives |

**Note on GeoTap**: If you want to test the full dual-server setup (GeoTap + env-data-mcp) in BERIL:
- Register at https://geotap.io/ for a GeoTap API key → `GEOTAP_API_KEY` in BERIL `.mcp.json`
- This is optional for `env-data-mcp` development itself

---

## Local and Lakehouse Testing

### Local testing (off-cluster)

**Step-by-step: test the MCP server directly from VS Code or Claude Desktop**

1. **Install the package in development mode**:
   ```bash
   cd ~/git-repos/env-data-mcp
   uv sync --extra dev
   ```

2. **Verify unit tests pass** (no network):
   ```bash
   uv run pytest tests/unit/ -m "not integration" -v
   ```

3. **Verify one integration test** (requires network; start with NASA POWER — no credentials needed):
   ```bash
   uv run pytest tests/integration/test_nasa_power_live.py -v
   ```

4. **Register in VS Code workspace `.mcp.json`** (add to the `env-data-mcp` workspace or BERIL workspace):
   ```json
   {
     "mcpServers": {
       "env-data": {
         "command": "uv",
         "args": ["run", "--directory", "/home/user/git-repos/env-data-mcp", "env-data-mcp"],
         "env": {
           "EARTHDATA_TOKEN": "${env:EARTHDATA_TOKEN}",
           "OPENAQ_API_KEY": "${env:OPENAQ_API_KEY}"
         }
       }
     }
   }
   ```
   Then ask Claude in VS Code: *"Use the env-data server to get NASA POWER temperature for latitude 46.253, longitude -119.477 for August 19, 2019."*

5. **Test via Claude Desktop** (alternative; useful for comparing behavior):
   Add the same entry to `~/.config/claude/claude_desktop_config.json` under `"mcpServers"`.

6. **Run demo notebooks**:
   ```bash
   uv run jupyter lab notebooks/
   ```
   Open `grow_point_sample_demo.ipynb` and run all cells.

7. **Inspect `_meta` for correctness**: Every tool response should have `_meta.success == true`, `_meta.license` non-empty, and `_meta.query_params` populated. If any are wrong, fix before Phase 5.

### Testing BERIL integration locally (off-cluster Lakehouse skill)

1. **Register `env-data-mcp` in BERIL's `.mcp.json`** (update the BERIL repo):
   ```json
   {
     "mcpServers": {
       "env-data": {
         "command": "uvx",
         "args": ["--from", "/home/user/git-repos/env-data-mcp", "env-data-mcp"],
         "env": {
           "EARTHDATA_TOKEN": "${EARTHDATA_TOKEN}",
           "OPENAQ_API_KEY": "${OPENAQ_API_KEY}"
         }
       }
     }
   }
   ```

2. **Load GROW data from file** (off-cluster mode):
   The BERIL SKILL.md will instruct the agent to read from `grow_locations.txt` when Spark is unavailable. Verify the agent reads the file and passes correct lat/lon/date to `nasa_power_query`.

3. **Check local log**: After a successful query, verify `~/.beril/env_query_log.jsonl` was written with the correct `_meta` fields. If the file isn't being written, debug the SKILL.md logging instructions.

4. **Test auth-missing response**: Temporarily unset `OPENAQ_API_KEY` in the MCP server's env block, then ask the agent to call `openaq_query`. Verify the response includes `_meta.auth_present == false` and a clear setup message — and that it does not crash or block the other source queries.

### Testing BERIL integration on-cluster (Lakehouse)

1. **SSH to BERDL JupyterHub** (or use the JupyterHub web UI).

2. **Clone `env-data-mcp` on the cluster** (or install from PyPI once published):
   ```bash
   git clone git@github.com:<org>/env-data-mcp.git ~/env-data-mcp
   ```

3. **Register in BERIL `.mcp.json` on-cluster** (same JSON as above, adjusted path).

4. **Load GROW data from Spark**:
   In a BERIL session, ask the agent: *"Load GROW sample metadata from Spark and enrich the first 5 samples with NASA POWER weather data."*
   Expected agent behavior:
   - `spark.sql("SELECT * FROM msyscolo_grow.growdb_sample_metadata LIMIT 5")`
   - For each row, call `nasa_power_query(latitude=..., longitude=..., start_date=date, end_date=date)`
   - Write `_meta` to `kbase_ops.env_query_log`

5. **Verify log table**:
   ```sql
   SELECT * FROM kbase_ops.env_query_log ORDER BY timestamp DESC LIMIT 10;
   ```
   Assert: `source = "nasa_power"`, `success = true`, `rows_returned > 0`, `latency_s` is reasonable.

6. **Check for pre-ingested tables** (if running after any data has been ingested):
   ```sql
   SHOW TABLES IN refdata_env_nasa_power;
   ```
   If the table exists, the BERIL skill should prefer it over calling the MCP tool. Verify the SKILL.md logic routes correctly.

7. **Run the GROW demo notebook on-cluster**: Open `notebooks/grow_point_sample_demo.ipynb` in JupyterHub; run all cells using the Spark kernel; verify output matches the off-cluster run (same values ± rounding).

---

## Running Locally for BERIL Integration

No PyPI publishing required for local testing. Add to BERIL's `.mcp.json`:

```json
{
  "mcpServers": {
    "env-data": {
      "command": "uvx",
      "args": ["--from", "/home/user/git-repos/env-data-mcp", "env-data-mcp"],
      "env": {
        "EARTHDATA_TOKEN": "${EARTHDATA_TOKEN}",
        "OPENAQ_API_KEY": "${OPENAQ_API_KEY}"
      }
    }
  }
}
```

Once published to PyPI, this simplifies to:

```json
"args": ["env-data-mcp"]
```

---

## Key Reference Files

| File | Purpose |
|---|---|
| `~/git-repos/external-data-gallery/src/external_data_gallery/sources/nasa_zarr.py` | NASA POWER Zarr S3 schema + query logic — template for `sources/nasa_power.py` |
| `~/git-repos/external-data-gallery/notebooks/weather-station-comparison/nasa-power/weather-station-nasa-power.ipynb` | `load_store()`, `extract_array_slice()` implementations |
| `~/git-repos/external-data-gallery/notebooks/weather-station-comparison/ssurgo/weather-station-ssurgo.ipynb` | `get_soil_data_for_polygon()` via SSURGO REST — template for `sources/ssurgo.py` |
| `~/git-repos/external-data-gallery/notebooks/earth-engine/alpha-earth.ipynb` | GEE auth + query pattern — template for `sources/gee.py` |
| `~/git-repos/external-data-gallery/src/external_data_gallery/sources/gbif_parquet.py` | Dask + anonymous S3 Parquet pattern — template for `sources/gbif.py` |
| `~/git-repos/external-data-gallery/examples/grow_locations.txt` | GROW point-samples test data |
| `~/git-repos/external-data-gallery/examples/pnnl_field_locations.txt` | PNNL bbox test data |
| `~/git-repos/external-data-gallery/docs/agent_recommendations_7Jan2026.md` | Lessons from prior agent prototype: query quality > model choice; robust verification critical |
| `~/git-repos/BERIL-research-observatory/env-data-prompt.md` | BERIL integration plan (Lakehouse logging, demo notebooks, on/off-cluster modes) |
| `~/git-repos/BERIL-research-observatory/gee-prompt.md` | S3 no-sign-request pattern for Sentinel-5P; GEE ingestion pipeline pattern |
