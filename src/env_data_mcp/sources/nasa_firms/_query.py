"""Query logic for NASA FIRMS (https://firms.modaps.eosdis.nasa.gov/api/area/)."""

from __future__ import annotations

import csv
import io
from typing import Any

import httpx

from ._constants import FIRMS_BASE_URL, LICENSE_INFO, SOURCE

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=60.0, headers={"Accept": "text/csv"})
    return _client


def fetch_csv(
    *, map_key: str, product: str, bbox: dict[str, float], days: int, date: str | None
) -> str:
    """The area CSV.  The key lives in the path (FIRMS design); the URL is built here and never
    returned or logged — a failure reports the status code only."""
    area = f"{bbox['min_lon']},{bbox['min_lat']},{bbox['max_lon']},{bbox['max_lat']}"
    url = f"{FIRMS_BASE_URL}/{map_key}/{product}/{area}/{days}" + (f"/{date}" if date else "")
    resp = _get_client().get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"FIRMS answered HTTP {resp.status_code}")
    text = resp.text
    if text.startswith("Invalid MAP_KEY"):
        raise PermissionError("FIRMS rejected the MAP_KEY")
    return text


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_records(csv_text: str, product: str) -> list[dict[str, Any]]:
    """FIRMS CSV rows → EventRecord dicts.  ``magnitude`` = fire radiative power (MW) when present;
    ``severity`` = the confidence class (VIIRS: l/n/h; MODIS: 0–100 → low/nominal/high)."""
    out: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for i, row in enumerate(reader):
        lat, lon = _f(row.get("latitude")), _f(row.get("longitude"))
        if lat is None or lon is None:
            continue
        acq_date = (row.get("acq_date") or "").strip()
        acq_time = (row.get("acq_time") or "").strip().zfill(4)
        t = f"{acq_date}T{acq_time[:2]}:{acq_time[2:]}:00Z" if acq_date else ""
        conf = (row.get("confidence") or "").strip()
        conf_n = _f(conf)
        if conf_n is not None:
            severity = "low" if conf_n < 30 else ("nominal" if conf_n < 80 else "high")
        else:
            severity = {"l": "low", "n": "nominal", "h": "high"}.get(conf.lower(), conf or None)
        out.append(
            {
                "id": f"{product}:{acq_date}:{acq_time}:{lat:.4f}:{lon:.4f}:{i}",
                "source": SOURCE,
                "kind": "fire",
                "title": f"{row.get('instrument') or product} fire detection",
                "lat": lat,
                "lon": lon,
                "geometry": None,
                "t_start": t,
                "t_end": None,
                "magnitude": _f(row.get("frp")),
                "magnitude_unit": "MW" if row.get("frp") not in (None, "") else None,
                "severity": severity,
                "url": "https://firms.modaps.eosdis.nasa.gov/map/",
                "licence": LICENSE_INFO["license"],
                "properties": {
                    "product": product,
                    "satellite": row.get("satellite"),
                    "instrument": row.get("instrument"),
                    "confidence": conf or None,
                    "bright_ti4": _f(row.get("bright_ti4")),
                    "bright_ti5": _f(row.get("bright_ti5")),
                    "brightness": _f(row.get("brightness")),
                    "scan": _f(row.get("scan")),
                    "track": _f(row.get("track")),
                    "daynight": row.get("daynight"),
                    "version": row.get("version"),
                },
            }
        )
    return out
