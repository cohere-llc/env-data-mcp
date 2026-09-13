"""Query logic for NWS alerts (https://www.weather.gov/documentation/services-web-api)."""

from __future__ import annotations

from typing import Any

import httpx

from ._constants import LICENSE_INFO, NWS_BASE_URL, SOURCE, USER_AGENT

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=30.0, headers={"Accept": "application/geo+json", "User-Agent": USER_AGENT}
        )
    return _client


def fetch_alerts(*, lat: float | None, lon: float | None, area: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"status": "actual", "message_type": "alert,update"}
    if lat is not None and lon is not None:
        params["point"] = f"{lat:.4f},{lon:.4f}"
    elif area:
        params["area"] = area
    resp = _get_client().get(f"{NWS_BASE_URL}/alerts/active", params=params)
    resp.raise_for_status()
    return resp.json()


def to_records(
    collection: dict[str, Any], fallback_lat: float | None, fallback_lon: float | None
) -> list[dict[str, Any]]:
    """GeoJSON alert features → EventRecord dicts.  Zone-based alerts have ``geometry: null``; the
    query point (or the zone list) stands in for a location."""
    out: list[dict[str, Any]] = []
    for f in collection.get("features") or []:
        p = f.get("properties") or {}
        geom = f.get("geometry")
        lat, lon = _centroid(geom)
        if lat is None:
            lat, lon = fallback_lat, fallback_lon
        if lat is None or lon is None:
            continue
        out.append(
            {
                "id": str(p.get("id") or f.get("id") or ""),
                "source": SOURCE,
                "kind": "alert",
                "title": str(p.get("headline") or p.get("event") or ""),
                "lat": float(lat),
                "lon": float(lon),
                "geometry": geom
                if geom and geom.get("type") in ("Polygon", "MultiPolygon")
                else None,
                "t_start": str(p.get("onset") or p.get("effective") or p.get("sent") or ""),
                "t_end": p.get("ends") or p.get("expires"),
                "magnitude": None,
                "magnitude_unit": None,
                "severity": p.get("severity"),
                "url": str(p.get("@id") or ""),
                "licence": LICENSE_INFO["license"],
                "properties": {
                    "event": p.get("event"),
                    "urgency": p.get("urgency"),
                    "certainty": p.get("certainty"),
                    "category": p.get("category"),
                    "area_desc": p.get("areaDesc"),
                    "zones": p.get("affectedZones") or [],
                    "sender": p.get("senderName"),
                    "instruction": p.get("instruction"),
                    "location_is_query_point": lat == fallback_lat and lon == fallback_lon,
                },
            }
        )
    return out


def _centroid(geom: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not geom:
        return None, None
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Point" and c:
        return float(c[1]), float(c[0])
    rings: list[Any] = []
    if t == "Polygon":
        rings = c[0] if c else []
    elif t == "MultiPolygon":
        rings = [pt for poly in (c or []) for pt in (poly[0] if poly else [])]
    if rings:
        lats = [pt[1] for pt in rings]
        lons = [pt[0] for pt in rings]
        return sum(lats) / len(lats), sum(lons) / len(lons)
    return None, None
