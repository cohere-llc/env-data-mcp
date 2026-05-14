"""OpenAQ v3 REST API adapter.

Data source: ``https://api.openaq.org/v3/``
Coverage: Global, 2016–present (sensor network)
Auth required: Yes — free API key from https://explore.openaq.org/register
               Set ``OPENAQ_API_KEY`` environment variable.
License: CC BY 4.0

Note on authentication
----------------------
OpenAQ v2 (unauthenticated) was retired in 2024.  v3 requires a free API key
obtained at https://explore.openaq.org/register.  When the key is absent this
module returns a structured ``auth_present=False`` response rather than raising.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

import httpx

from env_data_mcp.helpers import build_meta, clamp_bbox
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# License and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "CC BY 4.0",
    "license_url": "https://openaq.org/about/",
    "citation": (
        "OpenAQ. Air quality data accessed via OpenAQ API v3 "
        "(https://api.openaq.org/v3/). "
        "https://doi.org/10.7910/DVN/GKA0UN"
    ),
}

_OPENAQ_BASE = "https://api.openaq.org/v3"
_DEFAULT_PARAMETERS = ["pm25", "pm10", "o3", "no2", "co"]
_DEFAULT_LIMIT = 500

VARIABLE_INFO: dict[str, dict[str, str]] = {
    "pm25": {
        "description": "Fine particulate matter (diameter ≤ 2.5 µm)",
        "units": "µg/m³",
        "valid_range": "0 to ~500",
    },
    "pm10": {
        "description": "Coarse particulate matter (diameter ≤ 10 µm)",
        "units": "µg/m³",
        "valid_range": "0 to ~600",
    },
    "o3": {
        "description": "Surface ozone concentration",
        "units": "µg/m³",
        "valid_range": "0 to ~400",
    },
    "no2": {
        "description": "Nitrogen dioxide surface concentration",
        "units": "µg/m³",
        "valid_range": "0 to ~400",
    },
    "co": {
        "description": "Carbon monoxide surface concentration",
        "units": "µg/m³",
        "valid_range": "0 to ~30000",
    },
}


# ---------------------------------------------------------------------------
# Core query logic (testable without MCP)
# ---------------------------------------------------------------------------


def _build_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Accept": "application/json"}


def _fetch_locations(
    client: httpx.Client,
    api_key: str,
    lat: float,
    lon: float,
    radius_km: float,
) -> list[dict[str, Any]]:
    """Return up to 100 nearby sensor locations within radius_km of lat/lon.

    Uses bbox format to avoid the 25,000 m radius cap in the OpenAQ v3 API.
    """
    lat_d = radius_km / 111.0
    safe_lat = min(89.9, max(-89.9, lat))
    lon_d = radius_km / (111.0 * math.cos(math.radians(safe_lat)))
    bbox = f"{lon - lon_d:.6f},{lat - lat_d:.6f},{lon + lon_d:.6f},{lat + lat_d:.6f}"
    resp = client.get(
        f"{_OPENAQ_BASE}/locations",
        params={"bbox": bbox, "limit": 100},
        headers=_build_headers(api_key),
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def _fetch_measurements(
    client: httpx.Client,
    api_key: str,
    location_id: int,
    sensors: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    parameters: list[str],
    remaining_cap: int,
) -> list[dict[str, Any]]:
    """Fetch measurements for one location across all matching sensors."""
    records: list[dict[str, Any]] = []
    for sensor in sensors:
        if remaining_cap <= 0:
            break
        param = sensor.get("parameter", {})
        param_name = (param.get("name") or "").lower()
        if param_name not in parameters:
            continue
        sensor_id = sensor.get("id")
        page = 1
        while remaining_cap > 0:
            resp = client.get(
                f"{_OPENAQ_BASE}/sensors/{sensor_id}/measurements",
                params={
                    "date_from": f"{start_date}T00:00:00Z",
                    "date_to": f"{end_date}T23:59:59Z",
                    "limit": min(100, remaining_cap),
                    "page": page,
                },
                headers=_build_headers(api_key),
            )
            resp.raise_for_status()
            body = resp.json()
            batch = body.get("results", [])
            if not batch:
                break
            for m in batch:
                records.append(
                    {
                        "location_id": location_id,
                        "sensor_id": sensor_id,
                        "parameter": param_name,
                        "value": m.get("value"),
                        "units": param.get("units", ""),
                        "datetime": m.get("period", {})
                        .get("datetimeFrom", {})
                        .get("local", m.get("date", {}).get("utc", "")),
                        "latitude": (m.get("coordinates") or {}).get("latitude"),
                        "longitude": (m.get("coordinates") or {}).get("longitude"),
                    }
                )
            remaining_cap -= len(batch)
            if len(batch) < 100:
                break
            page += 1
    return records


def _fetch_openaq(
    lat: float,
    lon: float,
    radius_km: float,
    start_date: str,
    end_date: str,
    parameters: list[str],
    limit: int,
    api_key: str,
) -> list[dict[str, Any]]:
    """Fetch OpenAQ measurements near (lat, lon) within radius_km.

    Optimization strategy
    ---------------------
    * **Two-stage fetch**: a single ``/locations`` call retrieves up to 100
      nearby stations; measurements are only fetched for those stations.
      This avoids a full-table scan against the OpenAQ v3 backend.
    * **Per-page cap**: each measurements page is capped at
      ``min(100, remaining_cap)`` — no page larger than needed is requested.
    * **Early exit**: ``remaining`` is decremented after each location and the
      loop exits as soon as the caller-supplied ``limit`` is satisfied,
      preventing unnecessary downstream HTTP calls.

    Returns a flat list of measurement records capped at *limit* rows.
    """
    records: list[dict[str, Any]] = []

    with httpx.Client(timeout=30.0) as client:
        locations = _fetch_locations(client, api_key, lat, lon, radius_km)
        remaining = limit
        for loc in locations:
            if remaining <= 0:
                break
            location_id: int = int(loc.get("id") or 0)
            sensors = loc.get("sensors", [])
            batch = _fetch_measurements(
                client,
                api_key,
                location_id,
                sensors,
                start_date,
                end_date,
                parameters,
                remaining,
            )
            records.extend(batch)
            remaining -= len(batch)

    return records


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
def openaq_query(
    latitude: float,
    longitude: float,
    radius_km: float,
    start_date: str,
    end_date: str,
    parameters: list[str] | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return OpenAQ air quality measurements near a point for a date range.

    Requires the ``OPENAQ_API_KEY`` environment variable (free registration at
    https://explore.openaq.org/register).

    Args:
        latitude: WGS84 decimal latitude of the query centre.
        longitude: WGS84 decimal longitude of the query centre.
        radius_km: Search radius in kilometres.
        start_date: Inclusive start date, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end date, ISO 8601 ``YYYY-MM-DD``.
        parameters: List of pollutant codes to query (default:
            ``["pm25","pm10","o3","no2","co"]``).
        limit: Maximum number of measurement records to return (default 500).

    Returns:
        ``{"data": list[dict], "_meta": dict}`` — each data record contains
        ``location_id``, ``sensor_id``, ``parameter``, ``value``, ``units``,
        ``datetime``, ``latitude``, and ``longitude``.
    """
    if parameters is None:
        parameters = _DEFAULT_PARAMETERS
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": radius_km,
        "start_date": start_date,
        "end_date": end_date,
        "parameters": parameters,
        "limit": limit,
    }

    api_key = os.environ.get("OPENAQ_API_KEY", "")
    if not api_key:
        return {
            "data": [],
            "_meta": build_meta(
                source="openaq",
                query_params=query_params,
                rows_returned=0,
                latency_s=0.0,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=False,
                success=False,
                error=(
                    "OPENAQ_API_KEY environment variable is not set. "
                    "Register for a free API key at https://explore.openaq.org/register "
                    "and set it in your environment or .env file."
                ),
            ),
        }

    try:
        records = _fetch_openaq(
            lat=latitude,
            lon=longitude,
            radius_km=radius_km,
            start_date=start_date,
            end_date=end_date,
            parameters=parameters,
            limit=limit,
            api_key=api_key,
        )
        latency = time.perf_counter() - t0
        capped = len(records) >= limit
        req_params_set = set(parameters)
        info = {k: v for k, v in VARIABLE_INFO.items() if k in req_params_set}
        meta = build_meta(
            source="openaq",
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info=LICENSE_INFO,
            auth_required=True,
            auth_present=True,
            variables=parameters,
            variable_info=info,
            success=True,
            error=(
                f"No OpenAQ stations found within {radius_km} km of "
                f"({latitude}, {longitude}) for the requested date range."
                if not records
                else None
            ),
        )
        meta["capped"] = capped
        return {"data": records, "_meta": meta}
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="openaq",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=True,
                success=False,
                error=str(exc),
            ),
        }


@mcp.tool()
def openaq_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    parameters: list[str] | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return OpenAQ air quality measurements within a bounding box.

    Uses the bbox centroid + half-diagonal as the centre and radius for the
    OpenAQ ``/locations`` query.

    Args:
        min_lat: Southern boundary (WGS84 decimal degrees).
        max_lat: Northern boundary.
        min_lon: Western boundary.
        max_lon: Eastern boundary.
        start_date: Inclusive start date, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end date, ISO 8601 ``YYYY-MM-DD``.
        parameters: Pollutant codes (default: pm25, pm10, o3, no2, co).
        limit: Maximum measurement records to return (default 500).
    """
    if parameters is None:
        parameters = _DEFAULT_PARAMETERS
    bbox = clamp_bbox(
        {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
    )
    lat, lon = (bbox["min_lat"] + bbox["max_lat"]) / 2.0, (bbox["min_lon"] + bbox["max_lon"]) / 2.0
    # Half-diagonal of the bbox in km.
    lat_half = (bbox["max_lat"] - bbox["min_lat"]) / 2.0 * 111.0
    lon_half = (bbox["max_lon"] - bbox["min_lon"]) / 2.0 * 111.0 * math.cos(math.radians(lat))
    radius_km = math.sqrt(lat_half**2 + lon_half**2)

    return openaq_query(
        latitude=lat,
        longitude=lon,
        radius_km=radius_km,
        start_date=start_date,
        end_date=end_date,
        parameters=parameters,
        limit=limit,
    )
