"""Query logic for the USGS Water Data OGC API (https://api.waterdata.usgs.gov/docs/ogcapi/)."""

from __future__ import annotations

from typing import Any

import httpx

from ._constants import LICENSE_INFO, PARAMETERS, SOURCE, WATER_BASE_URL

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0, headers={"Accept": "application/geo+json"})
    return _client


def fetch_latest(
    *,
    bbox: dict[str, float] | None,
    site: str | None,
    parameter_code: str,
    limit: int,
    api_key: str,
) -> dict[str, Any]:
    """One GET on ``latest-continuous/items``.  The key, when present, goes in ``X-Api-Key``."""
    params: dict[str, Any] = {"parameter_code": parameter_code, "limit": limit, "f": "json"}
    if bbox is not None:
        params["bbox"] = f"{bbox['min_lon']},{bbox['min_lat']},{bbox['max_lon']},{bbox['max_lat']}"
    if site:
        params["monitoring_location_id"] = site if site.startswith("USGS-") else f"USGS-{site}"
    headers = {"X-Api-Key": api_key} if api_key else {}
    resp = _get_client().get(
        f"{WATER_BASE_URL}/collections/latest-continuous/items", params=params, headers=headers
    )
    if resp.status_code == 403:
        raise PermissionError("USGS Water Data rejected the API key (HTTP 403)")
    if resp.status_code == 429:
        raise RuntimeError("USGS Water Data rate limit reached (HTTP 429)")
    resp.raise_for_status()
    return resp.json()


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_records(collection: dict[str, Any], parameter_code: str) -> list[dict[str, Any]]:
    """Latest-value features → EventRecord dicts (``kind = "water"``; ``magnitude`` = the value,
    ``magnitude_unit`` = its unit; ``t_start`` = the observation time)."""
    out: list[dict[str, Any]] = []
    label = PARAMETERS.get(parameter_code, f"parameter {parameter_code}")
    for f in collection.get("features") or []:
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        site = str(p.get("monitoring_location_id") or "")
        out.append(
            {
                "id": f"{site}:{p.get('parameter_code')}:{p.get('time')}",
                "source": SOURCE,
                "kind": "water",
                "title": (
                    f"{site} — {label}: {p.get('value')} {p.get('unit_of_measure') or ''}".strip()
                ),
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "geometry": None,
                "t_start": str(p.get("time") or ""),
                "t_end": None,
                "magnitude": _f(p.get("value")),
                "magnitude_unit": p.get("unit_of_measure"),
                "severity": None,
                "url": (
                    f"https://waterdata.usgs.gov/monitoring-location/{site.replace('USGS-', '')}/"
                ),
                "licence": LICENSE_INFO["license"],
                "properties": {
                    "monitoring_location_id": site,
                    "parameter_code": p.get("parameter_code"),
                    "parameter": label,
                    "statistic_id": p.get("statistic_id"),
                    "approval_status": p.get("approval_status"),
                    "qualifier": p.get("qualifier"),
                    "last_modified": p.get("last_modified"),
                    "time_series_id": p.get("time_series_id"),
                },
            }
        )
    return out
