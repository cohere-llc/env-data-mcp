"""Query logic for the USGS Elevation Point Query Service."""

from __future__ import annotations

from typing import Any

import httpx

from ._constants import EPQS_URL

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=60.0, headers={"Accept": "application/json"})
    return _client


def fetch_elevation(*, lat: float, lon: float) -> dict[str, Any]:
    resp = _get_client().get(EPQS_URL, params={"x": lon, "y": lat, "units": "Meters", "wkid": 4326})
    resp.raise_for_status()
    return resp.json()


def to_record(payload: dict[str, Any]) -> dict[str, Any] | None:
    """EPQS JSON → ``{elevation_m, resolution_m, raster_id}``; ``None`` where the DEM has no data
    (EPQS answers a sentinel or an empty value outside coverage)."""
    raw = payload.get("value")
    if raw is None or raw == "":
        return None
    try:
        elev = float(str(raw))
    except ValueError:
        return None
    if elev <= -1e6:  # EPQS nodata sentinel
        return None
    return {
        "elevation_m": round(elev, 3),
        "resolution_m": payload.get("resolution"),
        "raster_id": payload.get("rasterId"),
        "units": "m",
    }
