"""Query logic for the ARM Live data service (https://adc.arm.gov/armlive/)."""

from __future__ import annotations

from typing import Any

import httpx

from ._constants import ARMLIVE_BASE_URL

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=60.0, headers={"Accept": "application/json"})
    return _client


def fetch_files(*, credential: str, datastream: str, start: str, end: str) -> dict[str, Any]:
    """``livedata/query`` — the files for a datastream between two dates. The credential rides in
    the query string (ARM offers no header form); see feeds.RedactCredentials."""
    params = {"user": credential, "ds": datastream, "start": start, "end": end, "wt": "json"}
    resp = _get_client().get(f"{ARMLIVE_BASE_URL}/query", params=params)
    if resp.status_code in (401, 403):
        raise PermissionError(f"ARM Live rejected the credential (HTTP {resp.status_code})")
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict) and str(body.get("status", "")).lower() not in ("", "success"):
        reason = str(body.get("reason") or body.get("message") or body.get("status"))
        if "auth" in reason.lower() or "user" in reason.lower():
            raise PermissionError(f"ARM Live rejected the credential: {reason[:80]}")
        raise RuntimeError(f"ARM Live: {reason[:120]}")
    return body if isinstance(body, dict) else {"files": []}


def to_records(body: dict[str, Any], datastream: str) -> list[dict[str, Any]]:
    out = []
    for f in body.get("files") or []:
        name = str(f)
        parts = name.split(".")
        date = parts[2] if len(parts) > 3 and parts[2].isdigit() else None
        out.append(
            {
                "file": name,
                "datastream": datastream,
                "date": (
                    f"{date[:4]}-{date[4:6]}-{date[6:8]}" if date and len(date) == 8 else None
                ),
                "download": f"{ARMLIVE_BASE_URL}/saveData?file={name}",
            }
        )
    return out
