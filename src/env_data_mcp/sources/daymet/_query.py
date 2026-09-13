"""Query logic for the Daymet single-pixel API (https://daymet.ornl.gov/single-pixel/)."""

from __future__ import annotations

from typing import Any

import httpx

from ._constants import DAYMET_BASE_URL, VARIABLES

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0, headers={"Accept": "application/json"})
    return _client


def fetch_pixel(*, lat: float, lon: float, date: str, variables: list[str]) -> dict[str, Any]:
    params = {
        "lat": lat,
        "lon": lon,
        "vars": ",".join(variables),
        "start": date,
        "end": date,
        "format": "json",
    }
    resp = _get_client().get(DAYMET_BASE_URL, params=params)
    resp.raise_for_status()
    return resp.json()


def to_record(payload: dict[str, Any], date: str, variables: list[str]) -> dict[str, Any]:
    """The single-pixel JSON → one flat record: ``{date, tmax_degC, tmin_degC, prcp_mm_day, …}``
    plus the pixel's elevation and tile."""
    data = payload.get("data") or {}
    rec: dict[str, Any] = {"date": date}
    for v in variables:
        col, unit = VARIABLES[v]
        vals = data.get(col) or []
        rec[f"{v}_{unit.replace('/', '_').replace('^', '')}"] = (
            float(vals[0]) if vals and vals[0] is not None else None
        )
    rec["elevation_m"] = _elev(payload.get("Elevation"))
    rec["tile"] = payload.get("Tile")
    rec["pixel_lat_lon"] = payload.get("loc")
    return rec


def _elev(v: Any) -> float | None:
    try:
        return float(str(v).split()[0])
    except (ValueError, IndexError, AttributeError):
        return None
