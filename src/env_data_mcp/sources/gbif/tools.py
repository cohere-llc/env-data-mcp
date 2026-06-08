"""MCP tool functions for the GBIF adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.helpers import build_meta, parse_date, point_to_bbox
from env_data_mcp.models import (
    AvailableVariablesResponse,
    BboxInput,
    DateRange,
    GroupedGeometryResponse,
    PointInput,
)
from env_data_mcp.server import mcp

from ._query import _estimate_query_runtime_s, _get_variable_info, _query_bbox, _query_point
from .constants import _DEFAULT_OCCURRENCE_VARIABLES, LICENSE_INFO, _QueryType

_KM_TO_DEG = 0.01  # approximate conversion of km to degrees for runtime estimates


def _validate_available_variables_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize available variables tool responses."""
    return AvailableVariablesResponse.model_validate(response).model_dump(by_alias=True)


def _validate_grouped_geometry_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize grouped geometry responses."""
    return GroupedGeometryResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def gbif_occurrence_available_variables() -> dict[str, Any]:
    """Return a list of available GBIF Occurrence variables with descriptions."""
    try:
        variable_info = _get_variable_info(_QueryType.OCCURRENCE)
        return _validate_available_variables_response(
            {
                "data": variable_info,
                "_meta": build_meta(
                    source="gbif",
                    query_params={},
                    rows_returned=len(variable_info),
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                ),
            }
        )
    except Exception as e:
        return _validate_available_variables_response(
            {
                "data": {},
                "_meta": build_meta(
                    source="gbif",
                    query_params={},
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(e),
                ),
            }
        )


@mcp.tool()
def gbif_occurrence_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    radius_km: float = 5.0,
    taxon_key: int | None = None,
    variables: list[str] = _DEFAULT_OCCURRENCE_VARIABLES,
    limit: int | None = None,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query GBIF occurrences data for a point location.

    Returns data about all species occurrences for the given location and date range.
    Global coverage, 1800s-present.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        start_date: Inclusive start date, ISO 8601 date string, e.g., "2019-08-15".
        end_date: Inclusive end date, ISO 8601 date string, e.g., "2019-08-16".
        radius_km: Search radius in kilometers.
        taxon_key: Optional GBIF taxon key to restrict results to a single taxon.
        variables: GBIF occurrence variable names (defaults to standard set). Use
            gbif_occurrence_available_variables() tool to get a list of valid variable names.
        limit: Optional maximum number of occurrence records to return. Omit to return all records.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "radius_km": radius_km,
        "taxon_key": taxon_key,
        "limit": limit,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    var_info: dict[str, dict[str, str]] = {}
    try:
        point = PointInput(latitude=latitude, longitude=longitude)
        date_range = DateRange(start_date=start_date, end_date=end_date)

        full_var_info = _get_variable_info(_QueryType.OCCURRENCE)
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}
        unavailable_vars = [var for var in variables if var not in full_var_info]

        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        bbox = point_to_bbox(
            latitude=point.latitude, longitude=point.longitude, radius_km=radius_km
        )
        area_deg2 = (bbox["max_lat"] - bbox["min_lat"]) * (bbox["max_lon"] - bbox["min_lon"])
        if warn := _estimate_query_runtime_s(n_days, area_deg2, max_runtime_s):
            return _validate_grouped_geometry_response(warn)
        data, unique_licenses = _query_point(
            lat=point.latitude,
            lon=point.longitude,
            start_date=date_range.start_date,
            end_date=date_range.end_date,
            query_type=_QueryType.OCCURRENCE,
            radius_km=radius_km,
            taxon_key=taxon_key,
            variables=variables,
            limit=limit,
        )
        latency = time.perf_counter() - t0
        license_info = {**LICENSE_INFO}
        if unique_licenses:
            license_info["license"] = ", ".join(unique_licenses)
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="gbif",
                    query_params=query_params,
                    rows_returned=len(data),
                    latency_s=latency,
                    license_info=license_info,
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable_vars,
                ),
            }
        )
    except Exception as e:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="gbif",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(e),
                    variables=variables,
                    variable_info=var_info,
                ),
            }
        )


@mcp.tool()
def gbif_occurrence_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    taxon_key: int | None = None,
    variables: list[str] = _DEFAULT_OCCURRENCE_VARIABLES,
    limit: int | None = None,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query GBIF occurrences data for a bounding box region.

    Returns data about all species occurrences for the given region and date range.
    Global coverage, 1800s-present.

    Args:
        min_lat: Decimal degrees, WGS84 (-90 to 90).
        max_lat: Decimal degrees, WGS84 (-90 to 90).
        min_lon: Decimal degrees, WGS84 (-180 to 180).
        max_lon: Decimal degrees, WGS84 (-180 to 180).
        start_date: Inclusive start date, ISO 8601 date string, e.g., "2019-08-15".
        end_date: Inclusive end date, ISO 8601 date string, e.g., "2019-08-16".
        taxon_key: Optional GBIF taxon key to restrict results to a single taxon.
        variables: GBIF occurrence variable names (defaults to standard set). Use
            gbif_occurrence_available_variables() tool to get a list of valid variable names.
        limit: Optional maximum number of occurrence records to return. Omit to return all records.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "taxon_key": taxon_key,
        "variables": variables,
        "limit": limit,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    var_info: dict[str, dict[str, str]] = {}
    try:
        bbox = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)
        date_range = DateRange(start_date=start_date, end_date=end_date)

        full_var_info = _get_variable_info(_QueryType.OCCURRENCE)
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}
        unavailable_vars = [var for var in variables if var not in full_var_info]

        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        area_deg2 = (max_lat - min_lat) * (max_lon - min_lon)
        if warn := _estimate_query_runtime_s(n_days, area_deg2, max_runtime_s):
            return _validate_grouped_geometry_response(warn)
        data, unique_licenses = _query_bbox(
            min_lat=bbox.min_lat,
            max_lat=bbox.max_lat,
            min_lon=bbox.min_lon,
            max_lon=bbox.max_lon,
            start_date=date_range.start_date,
            end_date=date_range.end_date,
            query_type=_QueryType.OCCURRENCE,
            taxon_key=taxon_key,
            variables=variables,
            limit=limit,
        )
        latency = time.perf_counter() - t0
        license_info = {**LICENSE_INFO}
        if unique_licenses:
            license_info["license"] = ", ".join(unique_licenses)
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="gbif",
                    query_params=query_params,
                    rows_returned=len(data),
                    latency_s=latency,
                    license_info=license_info,
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable_vars,
                ),
            }
        )
    except Exception as e:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="gbif",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(e),
                    variables=variables,
                    variable_info=var_info,
                ),
            }
        )
