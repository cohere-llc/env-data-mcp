"""Query logic for the EIA API v2 (https://www.eia.gov/opendata/documentation.php)."""

from __future__ import annotations

import math
from typing import Any

import httpx

from ._constants import EIA_BASE_URL, PAGE, ROUTE

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=60.0, headers={"Accept": "application/json"})
    return _client


def fetch_generators(*, api_key: str, state: str | None, max_pages: int = 20) -> list[dict]:
    """Every generator row for the latest month (paged by ``PAGE``); the key rides in the
    ``X-Api-Key`` header.  ``state`` (two letters) narrows the pull."""
    rows: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        params: list[tuple[str, Any]] = [
            ("frequency", "monthly"),
            ("data[0]", "nameplate-capacity-mw"),
            ("data[1]", "latitude"),
            ("data[2]", "longitude"),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "desc"),
            ("length", PAGE),
            ("offset", offset),
        ]
        if state:
            params.append(("facets[stateid][]", state.upper()))
        resp = _get_client().get(
            f"{EIA_BASE_URL}/{ROUTE}", params=params, headers={"X-Api-Key": api_key}
        )
        if resp.status_code == 403:
            raise PermissionError("EIA rejected the API key (HTTP 403)")
        resp.raise_for_status()
        body = resp.json().get("response") or {}
        page = body.get("data") or []
        rows.extend(page)
        total = int(body.get("total") or 0)
        offset += len(page)
        if not page or offset >= total:
            break
    return rows


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def plants_near(rows: list[dict], lat: float, lon: float, radius_km: float) -> list[dict[str, Any]]:
    """Generator rows (latest period per generator) → plants within the radius, nearest first."""
    latest_period: dict[Any, str] = {}
    for r in rows:  # rows are sorted period desc: the first period seen per generator is the latest
        key = (r.get("plantid"), r.get("generatorid"))
        latest_period.setdefault(key, str(r.get("period") or ""))
    plants: dict[Any, dict[str, Any]] = {}
    for r in rows:
        key = (r.get("plantid"), r.get("generatorid"))
        if str(r.get("period") or "") != latest_period[key]:
            continue
        plat, plon = _f(r.get("latitude")), _f(r.get("longitude"))
        if plat is None or plon is None:
            continue
        d = haversine_km(lat, lon, plat, plon)
        if d > radius_km:
            continue
        pid = r.get("plantid")
        p = plants.setdefault(
            pid,
            {
                "plant_id": pid,
                "name": r.get("plantName"),
                "state": r.get("stateid"),
                "lat": plat,
                "lon": plon,
                "distance_km": round(d, 1),
                "nameplate_capacity_mw": 0.0,
                "n_generators": 0,
                "energy_sources": {},
                "technologies": {},
                "period": latest_period[key],
                "status": r.get("status"),
            },
        )
        cap = _f(r.get("nameplate-capacity-mw")) or 0.0
        p["nameplate_capacity_mw"] = round(p["nameplate_capacity_mw"] + cap, 2)
        p["n_generators"] += 1
        src = str(r.get("energy_source_code") or "?")
        p["energy_sources"][src] = round(p["energy_sources"].get(src, 0.0) + cap, 2)
        tech = str(r.get("technology") or "?")
        p["technologies"][tech] = round(p["technologies"].get(tech, 0.0) + cap, 2)
    return sorted(plants.values(), key=lambda p: p["distance_km"])
