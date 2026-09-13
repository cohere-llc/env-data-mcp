"""Query logic for Macrostrat (https://macrostrat.org/api/v2)."""

from __future__ import annotations

from typing import Any

import httpx

from ._constants import MACROSTRAT_BASE_URL

_client: httpx.Client | None = None

_FIELDS = (
    "map_id",
    "source_id",
    "name",
    "strat_name",
    "lith",
    "descrip",
    "comments",
    "b_age",
    "t_age",
    "b_int_name",
    "t_int_name",
    "best_int_name",
    "color",
)


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0, headers={"Accept": "application/json"})
    return _client


def fetch_units(*, lat: float, lon: float) -> dict[str, Any]:
    resp = _get_client().get(
        f"{MACROSTRAT_BASE_URL}/geologic_units/map", params={"lat": lat, "lng": lon}
    )
    resp.raise_for_status()
    return resp.json()


def to_record(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The API payload → one record (the first / finest unit) with all units listed."""
    body = payload.get("success") or {}
    units = body.get("data") or []
    if not units:
        return None
    first = units[0]
    rec = {k: first.get(k) for k in _FIELDS}
    rec["age_ma"] = [first.get("b_age"), first.get("t_age")]
    rec["units"] = [{k: u.get(k) for k in _FIELDS} for u in units]
    rec["api_license"] = body.get("license")
    return rec
