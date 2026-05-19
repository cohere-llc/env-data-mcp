"""ISRIC SoilGrids v2.0 REST API adapter.

Data source: ``https://rest.isric.org/soilgrids/v2.0/``
Coverage: Global land areas, 250 m resolution
Auth required: No
License: CC BY 4.0 (ISRIC — World Soil Information)
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from env_data_mcp.helpers import bbox_centroid, build_meta, check_runtime
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# Licence and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "CC BY 4.0",
    "license_url": "https://www.isric.org/explore/soilgrids/faq-soilgrids",
    "citation": (
        "Poggio, L. et al. (2021). SoilGrids 2.0: producing soil information "
        "for the globe with quantified spatial uncertainty. SOIL, 7, 217–240. "
        "https://doi.org/10.5194/soil-7-217-2021"
    ),
}

_SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"

# Properties to fetch in Phase 1; depth fixed at 0–5 cm.
_PROPERTIES = ["bdod", "clay", "phh2o", "sand", "silt", "soc"]
_DEPTH = "0-5cm"

_NO_COVERAGE_MSG = (
    "No SoilGrids data for this location. The point may be in the ocean or outside land coverage."
)

# Plain-language descriptions and expected units for every property this
# adapter returns.  Included in _meta.variable_info on every response.
PROPERTY_INFO: dict[str, dict[str, str]] = {
    "bdod": {
        "description": "Bulk density of the fine earth fraction",
        "units": "kg/dm³",
        "valid_range": "0.5 to 2.0",
    },
    "clay": {
        "description": "Proportion of clay particles (< 0.002 mm) in the fine earth fraction",
        "units": "%",
        "valid_range": "0 to 100",
    },
    "phh2o": {
        "description": "Soil pH measured in a 1:1 soil-water suspension",
        "units": "pH units",
        "valid_range": "2 to 11",
    },
    "sand": {
        "description": "Proportion of sand particles (0.05–2 mm) in the fine earth fraction",
        "units": "%",
        "valid_range": "0 to 100",
    },
    "silt": {
        "description": "Proportion of silt particles (0.002–0.05 mm) in the fine earth fraction",
        "units": "%",
        "valid_range": "0 to 100",
    },
    "soc": {
        "description": "Soil organic carbon content in the fine earth fraction",
        "units": "g/kg",
        "valid_range": "0 to ~500",
    },
}


# ---------------------------------------------------------------------------
# Core query logic (sync, testable without MCP)
# ---------------------------------------------------------------------------


def _fetch_soilgrids(lat: float, lon: float) -> tuple[dict[str, Any], float]:
    """Fetch SoilGrids v2.0 property values at (lat, lon).

    Returns ``(result_dict, latency_s)``.  The result dict maps each property
    name to its physical value (after d_factor division) and unit string.
    Values are ``None`` for locations with no SoilGrids coverage.
    """
    params: dict[str, Any] = {
        "lon": float(lon),
        "lat": float(lat),
        "property": _PROPERTIES,
        "depth": _DEPTH,
        "value": "mean",
    }
    t0 = time.perf_counter()
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(_SOILGRIDS_URL, params=params)
    latency = time.perf_counter() - t0  # always captured; raise_for_status after timing
    resp.raise_for_status()

    data = resp.json()
    result: dict[str, Any] = {}
    layers = data.get("properties", {}).get("layers", [])
    for layer in layers:
        name: str = layer["name"]
        d_factor: int = layer.get("unit_measure", {}).get("d_factor", 1)
        target_unit: str = layer.get("unit_measure", {}).get("target_units", "")
        for depth_info in layer.get("depths", []):
            if depth_info.get("label") == _DEPTH:
                raw_val = depth_info.get("values", {}).get("mean")
                result[name] = round(raw_val / d_factor, 4) if raw_val is not None else None
                result[f"{name}_unit"] = target_unit
                break
    return result, latency


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def soilgrids_query(
    latitude: float,
    longitude: float,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query ISRIC SoilGrids v2.0 soil properties for a point location.

    Returns soil physical and chemical properties at 0–5 cm depth from the
    global SoilGrids 250 m dataset.  Properties: bulk density (bdod), clay,
    pH in water (phh2o), sand, silt, soil organic carbon (soc).
    Global land coverage; no API key required.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
    """
    if warn := check_runtime("soilgrids", 0, 0.0, max_runtime_s):
        return warn
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "max_runtime_s": max_runtime_s,
        "depth": _DEPTH,
        "properties": _PROPERTIES,
    }

    t0 = time.perf_counter()
    try:
        result, latency = _fetch_soilgrids(latitude, longitude)
        has_data = any(v is not None for k, v in result.items() if not k.endswith("_unit"))
        rows_returned = sum(
            1 for k, v in result.items() if not k.endswith("_unit") and v is not None
        )
        return {
            "data": result,
            "_meta": build_meta(
                source="soilgrids",
                query_params=query_params,
                rows_returned=rows_returned,
                latency_s=latency,
                license_info=LICENSE_INFO,
                variables=_PROPERTIES,
                variable_info=PROPERTY_INFO,
                error=_NO_COVERAGE_MSG if not has_data else None,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": {},
            "_meta": build_meta(
                source="soilgrids",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
                variables=_PROPERTIES,
                variable_info=PROPERTY_INFO,
            ),
        }


@mcp.tool()
def soilgrids_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query ISRIC SoilGrids v2.0 soil properties for a bounding-box area.

    Uses the centroid of the bounding box.
    Bounding boxes exceeding 10° in either dimension are clamped.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
    """
    bbox = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }
    clat, clon = bbox_centroid(bbox)
    area_deg2 = (bbox["max_lat"] - bbox["min_lat"]) * (bbox["max_lon"] - bbox["min_lon"])
    if warn := check_runtime("soilgrids", 0, area_deg2, max_runtime_s):
        return warn

    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "max_runtime_s": max_runtime_s,
        "centroid_lat": clat,
        "centroid_lon": clon,
        "depth": _DEPTH,
        "properties": _PROPERTIES,
    }

    t0 = time.perf_counter()
    try:
        result, latency = _fetch_soilgrids(clat, clon)
        has_data = any(v is not None for k, v in result.items() if not k.endswith("_unit"))
        rows_returned = sum(
            1 for k, v in result.items() if not k.endswith("_unit") and v is not None
        )
        return {
            "data": result,
            "_meta": build_meta(
                source="soilgrids",
                query_params=query_params,
                rows_returned=rows_returned,
                latency_s=latency,
                license_info=LICENSE_INFO,
                variables=_PROPERTIES,
                variable_info=PROPERTY_INFO,
                error=_NO_COVERAGE_MSG if not has_data else None,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": {},
            "_meta": build_meta(
                source="soilgrids",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
                variables=_PROPERTIES,
                variable_info=PROPERTY_INFO,
            ),
        }
