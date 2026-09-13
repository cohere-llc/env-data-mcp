"""Approximate bounding boxes of the 50 US states + DC (degrees; generous by design) — used to
turn a point and a radius into the ``facets[stateid][]`` values the EIA API filters on, so a
plants-near-a-point query pulls one or two states' generators (thousands of rows) instead of the
national table (100,000+ rows over 20 pages)."""

from __future__ import annotations

import math

# state: (min_lat, max_lat, min_lon, max_lon)
STATE_BBOX: dict[str, tuple[float, float, float, float]] = {
    "AL": (30.1, 35.1, -88.6, -84.8),
    "AK": (51.0, 71.5, -179.9, -129.9),
    "AZ": (31.3, 37.1, -114.9, -109.0),
    "AR": (33.0, 36.6, -94.7, -89.6),
    "CA": (32.4, 42.1, -124.5, -114.1),
    "CO": (36.9, 41.1, -109.1, -102.0),
    "CT": (40.9, 42.1, -73.8, -71.7),
    "DE": (38.4, 39.9, -75.8, -74.9),
    "DC": (38.7, 39.1, -77.2, -76.9),
    "FL": (24.3, 31.1, -87.7, -79.9),
    "GA": (30.3, 35.1, -85.7, -80.7),
    "HI": (18.8, 22.4, -160.3, -154.7),
    "ID": (41.9, 49.1, -117.3, -110.9),
    "IL": (36.9, 42.6, -91.6, -87.4),
    "IN": (37.7, 41.8, -88.2, -84.7),
    "IA": (40.3, 43.6, -96.7, -90.1),
    "KS": (36.9, 40.1, -102.1, -94.5),
    "KY": (36.4, 39.2, -89.6, -81.9),
    "LA": (28.8, 33.1, -94.1, -88.7),
    "ME": (42.9, 47.5, -71.2, -66.8),
    "MD": (37.8, 39.8, -79.5, -74.9),
    "MA": (41.1, 42.9, -73.6, -69.8),
    "MI": (41.6, 48.4, -90.5, -82.3),
    "MN": (43.4, 49.5, -97.3, -89.4),
    "MS": (30.1, 35.1, -91.7, -88.0),
    "MO": (35.9, 40.7, -95.8, -89.0),
    "MT": (44.3, 49.1, -116.1, -104.0),
    "NE": (39.9, 43.1, -104.1, -95.2),
    "NV": (34.9, 42.1, -120.1, -113.9),
    "NH": (42.6, 45.4, -72.7, -70.6),
    "NJ": (38.8, 41.4, -75.6, -73.8),
    "NM": (31.2, 37.1, -109.1, -102.9),
    "NY": (40.4, 45.1, -79.9, -71.7),
    "NC": (33.7, 36.7, -84.4, -75.3),
    "ND": (45.8, 49.1, -104.1, -96.5),
    "OH": (38.3, 42.1, -84.9, -80.4),
    "OK": (33.5, 37.1, -103.1, -94.3),
    "OR": (41.9, 46.4, -124.7, -116.4),
    "PA": (39.6, 42.3, -80.6, -74.6),
    "RI": (41.1, 42.1, -71.9, -71.1),
    "SC": (32.0, 35.3, -83.4, -78.4),
    "SD": (42.4, 46.0, -104.1, -96.4),
    "TN": (34.9, 36.7, -90.4, -81.6),
    "TX": (25.8, 36.6, -106.7, -93.4),
    "UT": (36.9, 42.1, -114.1, -108.9),
    "VT": (42.7, 45.1, -73.5, -71.4),
    "VA": (36.5, 39.5, -83.7, -75.2),
    "WA": (45.5, 49.1, -124.9, -116.8),
    "WV": (37.1, 40.7, -82.7, -77.6),
    "WI": (42.4, 47.1, -92.9, -86.7),
    "WY": (40.9, 45.1, -111.1, -104.0),
}


def states_near(lat: float, lon: float, radius_km: float) -> list[str]:
    """The states whose (generous) bounding box intersects the circle — one to three; empty
    outside the US."""
    dlat = radius_km / 111.0
    dlon = radius_km / max(1e-6, 111.0 * math.cos(math.radians(lat)))
    out = []
    for st, (la0, la1, lo0, lo1) in STATE_BBOX.items():
        if lat + dlat >= la0 and lat - dlat <= la1 and lon + dlon >= lo0 and lon - dlon <= lo1:
            out.append(st)
    return sorted(out)
