"""Query logic for Open-Meteo (https://open-meteo.com/en/docs)."""

from __future__ import annotations

from typing import Any

import httpx

from ._constants import CURRENT_VARS, DAILY_VARS, LICENSE_INFO, OPEN_METEO_BASE_URL, SOURCE

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0, headers={"Accept": "application/json"})
    return _client


def fetch_forecast(*, lat: float, lon: float, forecast_days: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join(CURRENT_VARS),
        "daily": ",".join(DAILY_VARS),
        "forecast_days": forecast_days,
        "timezone": "UTC",
    }
    resp = _get_client().get(f"{OPEN_METEO_BASE_URL}/forecast", params=params)
    resp.raise_for_status()
    return resp.json()


def to_record(payload: dict[str, Any], lat: float, lon: float) -> dict[str, Any]:
    """The forecast payload → ONE EventRecord (``kind = "weather"``): the current conditions, with
    the daily forecast and the units in ``properties``."""
    cur = payload.get("current") or {}
    cur_units = payload.get("current_units") or {}
    daily = payload.get("daily") or {}
    daily_units = payload.get("daily_units") or {}
    days = daily.get("time") or []
    forecast = [
        {k: (daily.get(k) or [None] * len(days))[i] for k in ("time", *DAILY_VARS)}
        for i in range(len(days))
    ]
    t = str(cur.get("time") or "")
    temp = cur.get("temperature_2m")
    return {
        "id": f"open_meteo:{lat:.4f}:{lon:.4f}:{t}",
        "source": SOURCE,
        "kind": "weather",
        "title": f"Current conditions: {temp} {cur_units.get('temperature_2m', '°C')}",
        "lat": float(payload.get("latitude", lat)),
        "lon": float(payload.get("longitude", lon)),
        "geometry": None,
        "t_start": t + ("Z" if t and not t.endswith("Z") else ""),
        "t_end": None,
        "magnitude": float(temp) if temp is not None else None,
        "magnitude_unit": cur_units.get("temperature_2m"),
        "severity": None,
        "url": "https://open-meteo.com/",
        "licence": LICENSE_INFO["license"],
        "properties": {
            "current": {k: cur.get(k) for k in CURRENT_VARS},
            "current_units": {k: cur_units.get(k) for k in CURRENT_VARS},
            "elevation_m": payload.get("elevation"),
            "forecast_daily": forecast,
            "daily_units": {k: daily_units.get(k) for k in DAILY_VARS},
            "model_grid_point": [payload.get("latitude"), payload.get("longitude")],
        },
    }
