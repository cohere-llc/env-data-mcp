"""ESS-DIVE dataset search adapter.

Data source: ESS-DIVE Dataset API v2.4
             https://api.ess-dive.lbl.gov/packages
Coverage:    DOE-funded environmental field datasets globally
Auth:        ESS-DIVE Bearer token — set ``ESSDIVE_TOKEN`` env var
             Free registration: https://data.ess-dive.lbl.gov/
             Generate token: Account Settings → API Tokens
License:     Varies per dataset — propagated from each dataset's metadata
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from env_data_mcp.helpers import (
    auth_missing_response,
    build_meta,
    check_runtime,
    parse_date,
)
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# License and variable metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "Varies per dataset; see _meta.license and each record's license field",
    "license_url": "https://data.ess-dive.lbl.gov",
    "citation": (
        "Data retrieved from ESS-DIVE (Environmental System Science Data "
        "Infrastructure for a Virtual Ecosystem), a repository funded by the "
        "U.S. Department of Energy's Office of Science. "
        "https://data.ess-dive.lbl.gov"
    ),
}

# ESS-DIVE datasets cover diverse DOE environmental science variables;
# no fixed schema exists — variables are per-dataset.
VARIABLE_INFO: dict[str, dict[str, str]] = {}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ESSDIVE_BASE = "https://api.ess-dive.lbl.gov/packages"
_SOURCE = "essdive"
_MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _extract_record(result: dict[str, Any]) -> dict[str, Any]:
    """Extract a flat, serialisable record from one ESS-DIVE search result."""
    dataset: dict[str, Any] = result.get("dataset") or {}

    # Temporal coverage — may be a dict or a plain string
    tc = dataset.get("temporalCoverage") or {}
    if isinstance(tc, dict):
        temporal_start: str = str(tc.get("startDate") or "")
        temporal_end: str = str(tc.get("endDate") or "")
    else:
        temporal_start = temporal_end = str(tc)

    # Description — may be a list of paragraphs or a plain string
    raw_desc = dataset.get("description") or ""
    joined = " ".join(str(d) for d in raw_desc[:2]) if isinstance(raw_desc, list) else str(raw_desc)
    description = joined[:500]

    # Variables measured — may be list[str] or list[dict]
    vm_raw = dataset.get("variableMeasured") or []
    variables_measured: list[str] = []
    for v in vm_raw:
        if isinstance(v, str):
            variables_measured.append(v)
        elif isinstance(v, dict):
            variables_measured.append(str(v.get("name") or v))

    return {
        "id": result.get("id") or "",
        "doi": dataset.get("@id") or "",
        "title": dataset.get("name") or "",
        "license": dataset.get("license") or "",
        "date_published": str(dataset.get("datePublished") or ""),
        "temporal_start": temporal_start,
        "temporal_end": temporal_end,
        "keywords": dataset.get("keywords") or [],
        "variables_measured": variables_measured,
        "description": description,
        "url": result.get("viewUrl") or "",
    }


def _search_packages(
    search_params: dict[str, Any],
    limit: int | None,
    token: str,
) -> list[dict[str, Any]]:
    """Fetch ESS-DIVE packages up to *limit*, following cursor pagination.

    Pass ``limit=None`` to fetch all matching packages (no cap).  The upstream
    API caps each page at ``_MAX_PAGE_SIZE`` (100) regardless.

    Raises
    ------
    ValueError
        When the server returns HTTP 401 (expired or invalid token).
    httpx.HTTPStatusError
        For any other non-2xx HTTP response.
    """
    headers = _build_headers(token)
    params: dict[str, Any] = {
        **search_params,
        "isPublic": "true",
        "pageSize": _MAX_PAGE_SIZE if limit is None else min(limit, _MAX_PAGE_SIZE),
    }

    records: list[dict[str, Any]] = []
    cursor: str | None = None

    with httpx.Client(timeout=30.0) as client:
        while limit is None or len(records) < limit:
            req_params = dict(params)
            req_params["pageSize"] = (
                _MAX_PAGE_SIZE if limit is None else min(limit - len(records), _MAX_PAGE_SIZE)
            )
            if cursor:
                req_params["cursor"] = cursor

            resp = client.get(_ESSDIVE_BASE, params=req_params, headers=headers)
            if resp.status_code == 401:
                raise ValueError(
                    "ESS-DIVE token rejected (HTTP 401) — token may be expired. "
                    "Regenerate at https://data.ess-dive.lbl.gov/ → "
                    "Account Settings → API Tokens and update ESSDIVE_TOKEN in .env."
                )
            # ESS-DIVE returns 404 with {"detail":"No datasets were found."} when
            # the query matches no records — treat this as an empty result set.
            if resp.status_code == 404:
                break
            resp.raise_for_status()

            body = resp.json()
            batch: list[dict[str, Any]] = body.get("result") or []
            records.extend(_extract_record(r) for r in batch)

            cursor = body.get("nextCursor")
            if not cursor or not batch:
                break

    return records if limit is None else records[:limit]


def _aggregate_licenses(records: list[dict[str, Any]]) -> str:
    """Return a deduplicated, sorted string of all dataset licenses."""
    unique = sorted({r["license"] for r in records if r.get("license")})
    if not unique:
        return LICENSE_INFO["license"]
    return " | ".join(unique)


# ---------------------------------------------------------------------------
# MCP tool: point query
# ---------------------------------------------------------------------------


@mcp.tool()
def essdive_query(
    latitude: float,
    longitude: float,
    radius_km: float = 50.0,
    start_date: str | None = None,
    end_date: str | None = None,
    text: str | None = None,
    limit: int | None = None,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Search ESS-DIVE for environmental datasets near a point location.

    Searches the DOE ESS-DIVE repository for datasets whose spatial coverage
    intersects a circle centred at (latitude, longitude) with the given radius.
    Returns dataset-level metadata (title, DOI, license, temporal coverage,
    keywords, variables measured) — not raw data values.

    Args:
        latitude: Decimal degrees, WGS-84, −90 to 90.
        longitude: Decimal degrees, WGS-84, −180 to 180.
        radius_km: Search radius in kilometres (default 50 km).
        start_date: Earliest date of dataset temporal coverage, ISO 8601
            (YYYY-MM-DD).  Datasets ending before this date are excluded.
        end_date: Latest date of dataset temporal coverage, ISO 8601
            (YYYY-MM-DD).  Datasets starting after this date are excluded.
        text: Optional free-text filter applied across all metadata fields.
        limit: Maximum number of datasets to return.  Omit (or pass ``None``)
            to rely on the ``max_runtime_s`` gate to bound query cost rather
            than a hard record cap.  Upstream page size is 100.
        max_runtime_s: If set, the query is allowed to run up to
            ``max_runtime_s * 1.2`` seconds before a slow-query warning is
            returned instead.  Default threshold is 30 s.

    Returns:
        {"data": [list of dataset records], "_meta": {...}}
    """
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": radius_km,
        "start_date": start_date,
        "end_date": end_date,
        "text": text,
        "limit": limit,
        "max_runtime_s": max_runtime_s,
    }
    try:
        _sd = parse_date(start_date) if start_date else None
        _ed = parse_date(end_date) if end_date else None
        n_days = (_ed - _sd).days + 1 if (_sd and _ed) else 0
        deg = radius_km / 111.0
        area_deg2 = (2 * deg) ** 2
        if warn := check_runtime("essdive", n_days, area_deg2, max_runtime_s):
            return warn
    except ValueError:
        pass  # invalid dates will surface below

    token = os.environ.get("ESSDIVE_TOKEN")
    if not token:
        return auth_missing_response(
            source=_SOURCE,
            license_info=LICENSE_INFO,
            error_msg=(
                "ESSDIVE_TOKEN is required. Register free at "
                "https://data.ess-dive.lbl.gov/ then go to "
                "Account Settings → API Tokens to generate a token."
            ),
            query_params=query_params,
        )

    try:
        search_params: dict[str, Any] = {
            "lat": latitude,
            "lon": longitude,
            "radius": int(radius_km * 1000),  # API expects metres
        }
        if start_date:
            search_params["beginDate"] = start_date
        if end_date:
            search_params["endDate"] = end_date
        if text:
            search_params["text"] = text

        records = _search_packages(search_params, limit=limit, token=token)
        latency = time.perf_counter() - t0
        capped = limit is not None and len(records) >= limit
        agg_license = _aggregate_licenses(records)
        lic = dict(LICENSE_INFO)
        lic["license"] = agg_license
        meta = build_meta(
            source=_SOURCE,
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info=lic,
            auth_required=True,
            auth_present=True,
            success=True,
        )
        meta["capped"] = capped
        meta["upstream_page_size"] = _MAX_PAGE_SIZE
        return {
            "data": records,
            "_meta": meta,
        }
    except ValueError as exc:
        # 401 expired-token path
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source=_SOURCE,
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=True,
                success=False,
                error=str(exc),
            ),
        }
    except httpx.HTTPError as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source=_SOURCE,
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=True,
                success=False,
                error=str(exc),
            ),
        }


# ---------------------------------------------------------------------------
# MCP tool: bounding-box query
# ---------------------------------------------------------------------------


@mcp.tool()
def essdive_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str | None = None,
    end_date: str | None = None,
    text: str | None = None,
    limit: int | None = None,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Search ESS-DIVE for environmental datasets within a bounding box.

    Searches the DOE ESS-DIVE repository for datasets whose spatial coverage
    intersects the given bounding box.  Returns dataset-level metadata —
    not raw data values.

    Args:
        min_lat: Southern latitude bound, −90 to 90.
        max_lat: Northern latitude bound, −90 to 90.
        min_lon: Western longitude bound, −180 to 180.
        max_lon: Eastern longitude bound, −180 to 180.
        start_date: Earliest date of dataset temporal coverage (YYYY-MM-DD).
        end_date: Latest date of dataset temporal coverage (YYYY-MM-DD).
        text: Optional free-text filter across all metadata fields.
        limit: Maximum number of datasets to return.  Omit (or pass ``None``)
            to rely on the ``max_runtime_s`` gate to bound query cost rather
            than a hard record cap.  Upstream page size is 100.
        max_runtime_s: Acceptable runtime in seconds; see ``essdive_query``.

    Returns:
        {"data": [list of dataset records], "_meta": {...}}
    """
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "text": text,
        "limit": limit,
        "max_runtime_s": max_runtime_s,
    }

    try:
        _sd = parse_date(start_date) if start_date else None
        _ed = parse_date(end_date) if end_date else None
        n_days = (_ed - _sd).days + 1 if (_sd and _ed) else 0
        area_deg2 = (max_lat - min_lat) * (max_lon - min_lon)
        if warn := check_runtime("essdive", n_days, area_deg2, max_runtime_s):
            return warn
    except ValueError:
        pass  # invalid dates will surface below

    token = os.environ.get("ESSDIVE_TOKEN")
    if not token:
        return auth_missing_response(
            source=_SOURCE,
            license_info=LICENSE_INFO,
            error_msg=(
                "ESSDIVE_TOKEN is required. Register free at "
                "https://data.ess-dive.lbl.gov/ then go to "
                "Account Settings → API Tokens to generate a token."
            ),
            query_params=query_params,
        )

    bbox = {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}

    try:
        # API bbox format: min_lat,min_lon,max_lat,max_lon
        bbox_str = f"{bbox['min_lat']},{bbox['min_lon']},{bbox['max_lat']},{bbox['max_lon']}"
        search_params: dict[str, Any] = {"bbox": bbox_str}
        if start_date:
            search_params["beginDate"] = start_date
        if end_date:
            search_params["endDate"] = end_date
        if text:
            search_params["text"] = text

        records = _search_packages(search_params, limit=limit, token=token)
        latency = time.perf_counter() - t0
        capped = limit is not None and len(records) >= limit
        agg_license = _aggregate_licenses(records)
        lic = dict(LICENSE_INFO)
        lic["license"] = agg_license
        meta = build_meta(
            source=_SOURCE,
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info=lic,
            auth_required=True,
            auth_present=True,
            success=True,
        )
        meta["capped"] = capped
        meta["upstream_page_size"] = _MAX_PAGE_SIZE
        return {
            "data": records,
            "_meta": meta,
        }
    except ValueError as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source=_SOURCE,
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=True,
                success=False,
                error=str(exc),
            ),
        }
    except httpx.HTTPError as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source=_SOURCE,
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=True,
                success=False,
                error=str(exc),
            ),
        }
