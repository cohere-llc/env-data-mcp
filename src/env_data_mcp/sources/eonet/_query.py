"""Query logic for the NASA EONET adapter (https://eonet.gsfc.nasa.gov/docs/v3)."""

from __future__ import annotations

from typing import Any

import httpx

from ._constants import EONET_BASE_URL, KIND_BY_CATEGORY, LICENSE_INFO, SOURCE

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0, headers={"Accept": "application/json"})
    return _client


def fetch_events(
    *,
    days: int,
    status: str,
    bbox: dict[str, float] | None,
    category: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """The raw EONET events for the query (one GET)."""
    params: dict[str, Any] = {"status": status, "days": days, "limit": limit}
    if bbox is not None:
        # EONET's bbox order is minLon,maxLat,maxLon,minLat (upper-left, lower-right)
        params["bbox"] = f"{bbox['min_lon']},{bbox['max_lat']},{bbox['max_lon']},{bbox['min_lat']}"
    url = f"{EONET_BASE_URL}/events" if not category else f"{EONET_BASE_URL}/categories/{category}"
    resp = _get_client().get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("events", [])


def to_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """EONET events → EventRecord dicts.

    The representative point is the LATEST geometry; a track (≥ 2 points) becomes a LineString
    geometry; a polygon geometry is kept as is."""
    out: list[dict[str, Any]] = []
    for ev in events:
        geoms = ev.get("geometry") or []
        if not geoms:
            continue
        last = geoms[-1]
        lat, lon = _point_of(last)
        if lat is None or lon is None:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue  # EONET occasionally carries swapped coordinates (seen live: lat 99.07)
        cats = ev.get("categories") or []
        cat_id = cats[0].get("id", "") if cats else ""
        geometry: dict[str, Any] | None = None
        if last.get("type") == "Polygon":
            geometry = {"type": "Polygon", "coordinates": last.get("coordinates")}
        elif len(geoms) >= 2 and all(g.get("type") == "Point" for g in geoms):
            geometry = {"type": "LineString", "coordinates": [g["coordinates"] for g in geoms]}
        mag = last.get("magnitudeValue")
        sources = ev.get("sources") or []
        out.append(
            {
                "id": str(ev.get("id")),
                "source": SOURCE,
                "kind": KIND_BY_CATEGORY.get(cat_id, "other"),
                "title": str(ev.get("title") or ""),
                "lat": lat,
                "lon": lon,
                "geometry": geometry,
                "t_start": str(geoms[0].get("date") or ""),
                "t_end": ev.get("closed"),
                "magnitude": float(mag) if mag is not None else None,
                "magnitude_unit": last.get("magnitudeUnit"),
                "severity": None,
                "url": str(ev.get("link") or ""),
                "licence": LICENSE_INFO["license"],
                "properties": {
                    "category": cat_id,
                    "category_title": cats[0].get("title", "") if cats else "",
                    "n_geometries": len(geoms),
                    "last_update": last.get("date"),
                    "sources": [{"id": s.get("id"), "url": s.get("url")} for s in sources],
                },
            }
        )
    return out


def _point_of(geom: dict[str, Any]) -> tuple[float | None, float | None]:
    coords = geom.get("coordinates")
    if geom.get("type") == "Point" and isinstance(coords, list) and len(coords) >= 2:
        return float(coords[1]), float(coords[0])
    if geom.get("type") == "Polygon" and coords:
        ring = coords[0]
        if ring:
            lons = [p[0] for p in ring]
            lats = [p[1] for p in ring]
            return sum(lats) / len(lats), sum(lons) / len(lons)
    return None, None
