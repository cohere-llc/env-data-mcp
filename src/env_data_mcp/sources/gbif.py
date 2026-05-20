"""GBIF occurrence data adapter — GBIF Occurrence Search REST API.

Data source: ``https://api.gbif.org/v1/occurrence/search``
Coverage: Global, 1800s–present
Auth required: No (public API)
License: Mixed — CC0 1.0, CC BY 4.0, CC BY-NC 4.0 per record
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from env_data_mcp.helpers import build_meta, check_runtime, parse_date
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# License and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "Mixed: CC0 1.0, CC BY 4.0, CC BY-NC 4.0 (per occurrence record)",
    "license_url": "https://www.gbif.org/terms",
    "citation": (
        "GBIF.org. Accessed via GBIF Occurrence Search API: "
        "https://api.gbif.org/v1/occurrence/search. "
        "Cite individual records using the GBIF data publisher DOI."
    ),
}

VARIABLE_INFO: dict[str, dict[str, str]] = {
    "species": {
        "description": "Accepted scientific species name (binomial nomenclature)",
        "units": "dimensionless",
        "valid_range": "N/A",
    },
    "decimalLatitude": {
        "description": "WGS84 decimal latitude of the observed occurrence",
        "units": "degrees",
        "valid_range": "-90 to 90",
    },
    "decimalLongitude": {
        "description": "WGS84 decimal longitude of the observed occurrence",
        "units": "degrees",
        "valid_range": "-180 to 180",
    },
    "eventDate": {
        "description": "Date (and optionally time) of the observation in ISO 8601 format",
        "units": "ISO 8601",
        "valid_range": "1800-01-01 to present",
    },
    "taxonKey": {
        "description": "GBIF backbone taxon identifier for the accepted species",
        "units": "dimensionless",
        "valid_range": "1 to ~10^9",
    },
}

_GBIF_API_BASE = "https://api.gbif.org/v1/occurrence/search"

# GBIF's occurrence search API caps each page at 300 records.
_API_PAGE_SIZE = 300


# ---------------------------------------------------------------------------
# Core query logic (testable without MCP)
# ---------------------------------------------------------------------------


def _fetch_gbif(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    taxon_key: int | None,
    limit: int | None,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Query the GBIF Occurrence Search REST API.

    Returns ``(records, total_count, unique_licenses)``.

    *total_count* is the API-reported total number of matching occurrences
    (may exceed *limit* when results are capped).  At most *limit* records are
    returned (all records when *limit* is ``None``), fetched across multiple
    pages of up to ``_API_PAGE_SIZE`` each.
    """
    base_params: dict[str, Any] = {
        "decimalLatitude": f"{min_lat},{max_lat}",
        "decimalLongitude": f"{min_lon},{max_lon}",
        "eventDate": f"{start_date},{end_date}",
    }
    if taxon_key is not None:
        base_params["taxonKey"] = taxon_key

    raw_records: list[dict[str, Any]] = []
    total_count = 0

    while limit is None or len(raw_records) < limit:
        if limit is not None:
            page_size = min(limit - len(raw_records), _API_PAGE_SIZE)
        else:
            page_size = _API_PAGE_SIZE
        r = httpx.get(
            _GBIF_API_BASE,
            params={**base_params, "limit": page_size, "offset": len(raw_records)},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        total_count = body.get("count", 0)
        page = body.get("results", [])
        raw_records.extend(page)
        if body.get("endOfRecords", True) or not page:
            break

    records: list[dict[str, Any]] = []
    unique_licenses: set[str] = set()
    for rec in raw_records[:limit] if limit is not None else raw_records:
        lic = rec.get("license") or ""
        if lic:
            unique_licenses.add(lic)
        records.append(
            {
                "species": rec.get("species") or rec.get("scientificName"),
                "decimalLatitude": rec.get("decimalLatitude"),
                "decimalLongitude": rec.get("decimalLongitude"),
                "eventDate": rec.get("eventDate"),
                "taxonKey": rec.get("taxonKey"),
                "license": lic,
                "gbifID": rec.get("gbifID") or str(rec.get("key", "")),
            }
        )

    return records, total_count, sorted(unique_licenses)


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
def gbif_occurrences(
    latitude: float,
    longitude: float,
    radius_km: float,
    start_date: str,
    end_date: str,
    taxon_key: int | None = None,
    limit: int | None = None,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Return GBIF species occurrence records within *radius_km* of a point.

    Queries the GBIF Occurrence Search REST API (``api.gbif.org``).

    Args:
        latitude: WGS84 decimal latitude of the query centre.
        longitude: WGS84 decimal longitude of the query centre.
        radius_km: Search radius in kilometres (converted to a bbox internally).
        start_date: Inclusive start date, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end date, ISO 8601 ``YYYY-MM-DD``.
        taxon_key: Optional GBIF taxon key to restrict results to a single taxon.
        limit: Maximum number of occurrence records to return.  Omit (or
            pass ``None``) to rely on the ``max_runtime_s`` gate to bound
            query cost rather than a hard record cap.
        max_runtime_s: Acceptable runtime in seconds; see timing docs.

    Returns:
        ``{"data": list[dict], "_meta": dict}`` — each data record contains
        ``species``, ``decimalLatitude``, ``decimalLongitude``, ``eventDate``,
        ``taxonKey``, ``license``, and ``gbifID``.
    """
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": radius_km,
        "start_date": start_date,
        "end_date": end_date,
        "taxon_key": taxon_key,
        "limit": limit,
        "max_runtime_s": max_runtime_s,
    }
    deg = radius_km / 111.0
    bbox = {
        "min_lat": latitude - deg,
        "max_lat": latitude + deg,
        "min_lon": longitude - deg,
        "max_lon": longitude + deg,
    }
    query_params["resolved_min_lat"] = bbox["min_lat"]
    query_params["resolved_max_lat"] = bbox["max_lat"]
    query_params["resolved_min_lon"] = bbox["min_lon"]
    query_params["resolved_max_lon"] = bbox["max_lon"]
    try:
        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        area_deg2 = (2 * deg) ** 2
        if warn := check_runtime("gbif", n_days, area_deg2, max_runtime_s):
            return warn
        records, total_count, unique_licenses = _fetch_gbif(
            min_lat=bbox["min_lat"],
            max_lat=bbox["max_lat"],
            min_lon=bbox["min_lon"],
            max_lon=bbox["max_lon"],
            start_date=start_date,
            end_date=end_date,
            taxon_key=taxon_key,
            limit=limit,
        )
        latency = time.perf_counter() - t0
        capped = limit is not None and total_count > limit
        license_str = " | ".join(unique_licenses) if unique_licenses else LICENSE_INFO["license"]
        meta = build_meta(
            source="gbif",
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info={**LICENSE_INFO, "license": license_str},
            variable_info=VARIABLE_INFO,
            success=True,
        )
        meta["capped"] = capped
        meta["total_count"] = total_count
        meta["upstream_page_size"] = _API_PAGE_SIZE
        return {"data": records, "_meta": meta}
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="gbif",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }


@mcp.tool()
def gbif_bbox_occurrences(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    taxon_key: int | None = None,
    limit: int | None = None,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Return GBIF occurrence records within a bounding box.

    Identical to ``gbif_occurrences`` but accepts an explicit bounding box
    instead of a centre point + radius.

    Args:
        min_lat: Southern boundary (WGS84 decimal degrees).
        max_lat: Northern boundary.
        min_lon: Western boundary.
        max_lon: Eastern boundary.
        start_date: Inclusive start date, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end date, ISO 8601 ``YYYY-MM-DD``.
        taxon_key: Optional GBIF taxon key to restrict results.
        limit: Maximum records to return.  Pass ``None`` (default) to return all.
        max_runtime_s: Acceptable runtime in seconds; see timing docs.
    """
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "taxon_key": taxon_key,
        "limit": limit,
        "max_runtime_s": max_runtime_s,
    }
    bbox = {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
    query_params.update(bbox)
    try:
        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        area_deg2 = (bbox["max_lat"] - bbox["min_lat"]) * (bbox["max_lon"] - bbox["min_lon"])
        if warn := check_runtime("gbif", n_days, area_deg2, max_runtime_s):
            return warn
        records, total_count, unique_licenses = _fetch_gbif(
            min_lat=bbox["min_lat"],
            max_lat=bbox["max_lat"],
            min_lon=bbox["min_lon"],
            max_lon=bbox["max_lon"],
            start_date=start_date,
            end_date=end_date,
            taxon_key=taxon_key,
            limit=limit,
        )
        latency = time.perf_counter() - t0
        capped = limit is not None and total_count > limit
        license_str = " | ".join(unique_licenses) if unique_licenses else LICENSE_INFO["license"]
        meta = build_meta(
            source="gbif",
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info={**LICENSE_INFO, "license": license_str},
            variable_info=VARIABLE_INFO,
            success=True,
        )
        meta["capped"] = capped
        meta["total_count"] = total_count
        meta["upstream_page_size"] = _API_PAGE_SIZE
        return {"data": records, "_meta": meta}
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="gbif",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }
