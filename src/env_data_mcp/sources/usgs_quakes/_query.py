"""Query logic for the USGS FDSN event service (https://earthquake.usgs.gov/fdsnws/event/1/)."""

from __future__ import annotations

import datetime
from typing import Any

import httpx

from env_data_mcp.feeds import iso_or_none

from ._constants import FDSN_BASE_URL, LICENSE_INFO, SOURCE

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0, headers={"Accept": "application/json"})
    return _client


def fetch_quakes(
    *,
    bbox: dict[str, float] | None,
    days: int,
    min_magnitude: float,
    limit: int,
    now: datetime.datetime | None = None,
) -> list[dict[str, Any]]:
    """GeoJSON features for the window ``[now − days, now]``."""
    end = now or datetime.datetime.now(datetime.UTC)
    start = end - datetime.timedelta(days=days)
    params: dict[str, Any] = {
        "format": "geojson",
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": end.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": min_magnitude,
        "limit": limit,
        "orderby": "time",
    }
    if bbox is not None:
        params.update(
            {
                "minlatitude": bbox["min_lat"],
                "maxlatitude": bbox["max_lat"],
                "minlongitude": bbox["min_lon"],
                "maxlongitude": bbox["max_lon"],
            }
        )
    resp = _get_client().get(f"{FDSN_BASE_URL}/query", params=params)
    resp.raise_for_status()
    return resp.json().get("features", [])


def to_records(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in features:
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        mag = p.get("mag")
        out.append(
            {
                "id": str(f.get("id")),
                "source": SOURCE,
                "kind": "quake",
                "title": str(p.get("title") or p.get("place") or ""),
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "geometry": None,
                "t_start": iso_or_none(p.get("time")) or "",
                "t_end": None,
                "magnitude": float(mag) if mag is not None else None,
                "magnitude_unit": p.get("magType"),
                "severity": p.get("alert"),  # PAGER alert level: green/yellow/orange/red, or null
                "url": str(p.get("url") or ""),
                "licence": LICENSE_INFO["license"],
                "properties": {
                    "depth_km": float(coords[2])
                    if len(coords) > 2 and coords[2] is not None
                    else None,
                    "place": p.get("place"),
                    "tsunami": p.get("tsunami"),
                    "felt": p.get("felt"),
                    "status": p.get("status"),
                    "updated": iso_or_none(p.get("updated")),
                },
            }
        )
    return out
