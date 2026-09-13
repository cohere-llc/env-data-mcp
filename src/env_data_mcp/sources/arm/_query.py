"""Nearest-site logic for the ARM adapter (no network: a cited static table)."""

from __future__ import annotations

import math
from typing import Any

from ._constants import SITES


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def nearest(lat: float, lon: float, n: int = 3) -> list[dict[str, Any]]:
    """Every fixed site with its distance, nearest first (``n`` of them)."""
    rows = []
    for s in SITES:
        d = haversine_km(lat, lon, float(s["lat"]), float(s["lon"]))
        rows.append({**s, "distance_km": round(d, 1)})
    rows.sort(key=lambda r: r["distance_km"])
    return rows[:n]
