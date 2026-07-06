"""Core query logic for GBIF: point/bbox data extraction."""

from __future__ import annotations

from typing import Any

import httpx

from env_data_mcp.helpers import check_runtime, get_by_path, point_to_bbox

from .constants import _API_PAGE_SIZE, _QUERY_ENDPOINTS, _QUERY_RESULT_SCHEMAS, _QueryType

# ---------------------------------------------------------------------------
# Session-level caches
# ---------------------------------------------------------------------------

# available variables by query type -> { query_type: { variable: {" description": str } }
_VARIABLE_INFO_CACHE: dict[_QueryType, dict[str, dict[str, str]]] = {}

# ---------------------------------------------------------------------------
# Core query logic
# ---------------------------------------------------------------------------


def _get_variable_info(query_type: _QueryType) -> dict[str, dict[str, str]]:
    """Discover available variables for a specific GBIF query type.

    :param query_type: GBIF query type
    :return: dict keyed on variable with `description`
    """
    if query_type in _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE[query_type]
    with httpx.Client(timeout=30) as client:
        resp = client.get(_QUERY_RESULT_SCHEMAS[query_type]["url"])
        resp.raise_for_status()
        info = get_by_path(resp.json(), _QUERY_RESULT_SCHEMAS[query_type]["path"], {})
    _VARIABLE_INFO_CACHE[query_type] = {
        key: {"description": val.get("description", key) or key, "units": ""}
        for key, val in info.items()
    }
    return _VARIABLE_INFO_CACHE[query_type]


def _query_point(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    query_type: _QueryType,
    radius_km: float,
    taxon_key: int | None,
    variables: list[str],
    limit: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract time-series records for a single point from a GBIF query.

    Returns ``(groups, unique_licenses)`` where ``groups``
    is either an empty list (query returned no results) or a list of occurrences
    organized by GeoJSON ``Point`` geometries (one occurrence per geometry).
    """
    bbox = point_to_bbox(latitude=lat, longitude=lon, radius_km=radius_km)
    return _query_bbox(
        min_lat=bbox["min_lat"],
        max_lat=bbox["max_lat"],
        min_lon=bbox["min_lon"],
        max_lon=bbox["max_lon"],
        start_date=start_date,
        end_date=end_date,
        query_type=query_type,
        taxon_key=taxon_key,
        variables=variables,
        limit=limit,
    )


def _query_bbox(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    query_type: _QueryType,
    taxon_key: int | None,
    variables: list[str],
    limit: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract time-series records for a bounding box from a GBIF query.

    Returns ``(groups, unique_licenses)`` where ``groups``
    is either an empty list (query returned no results) or a list of occurrences
    organized by GeoJSON ``Point`` geometries (one occurrence per geometry).

    """
    base_params: dict[str, Any] = {
        "decimalLatitude": f"{min_lat},{max_lat}",
        "decimalLongitude": f"{min_lon},{max_lon}",
        "eventDate": f"{start_date},{end_date}",
    }
    if taxon_key is not None:
        base_params["taxonKey"] = taxon_key

    raw_records: list[dict[str, Any]] = []

    while limit is None or len(raw_records) < limit:
        if limit is not None:
            page_size = min(limit - len(raw_records), _API_PAGE_SIZE)
        else:
            page_size = _API_PAGE_SIZE
        r = httpx.get(
            _QUERY_ENDPOINTS[query_type],
            params={**base_params, "limit": page_size, "offset": len(raw_records)},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        page = body["results"]
        raw_records.extend(page)
        if body["endOfRecords"]:
            break

    records: list[dict[str, Any]] = []
    unique_licenses: set[str] = set()
    for rec in raw_records:
        lic = rec.get("license", "")
        if lic:
            unique_licenses.add(lic)
        data = {var: rec[var] for var in variables if var in rec}
        records.append(
            {
                "geometry": {
                    "type": "Point",
                    "coordinates": [rec["decimalLongitude"], rec["decimalLatitude"]],
                },
                "latitude": rec["decimalLatitude"],
                "longitude": rec["decimalLongitude"],
                "records": [data],
            }
        )

    return records, sorted(unique_licenses)


# ---------------------------------------------------------------------------
# Runtime estimation
# ---------------------------------------------------------------------------


def _estimate_query_runtime_s(
    n_days: int,
    area_deg2: float,
    max_runtime_s: float,
) -> dict[str, Any] | None:
    """Rough heuristic to estimate query runtime in seconds based on query size."""
    return check_runtime(
        source="gbif", n_days=n_days, area_deg2=area_deg2, max_runtime_s=max_runtime_s
    )
