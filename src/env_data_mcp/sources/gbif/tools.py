"""MCP tool functions for the GBIF adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.helpers import build_meta, date_range_days, point_to_bbox
from env_data_mcp.models import (
    AvailableVariablesResponse,
    BboxInput,
    DateRange,
    GroupedGeometryResponse,
    PointInput,
)
from env_data_mcp.server import mcp

from ._constants import _DEFAULT_OCCURRENCE_VARIABLES, LICENSE_INFO, QueryType
from ._query import estimate_query_runtime_s, query_bbox, query_point
from ._var_cache import get_variable_info

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
    t0 = time.perf_counter()
    try:
        variable_info = get_variable_info(QueryType.OCCURRENCE)
        return _validate_available_variables_response(
            {
                "data": variable_info,
                "_meta": build_meta(
                    source="gbif",
                    query_params={},
                    geometries_returned=0,
                    total_records_returned=len(variable_info),
                    latency_s=time.perf_counter() - t0,
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
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=time.perf_counter() - t0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(e),
                ),
            }
        )


@mcp.tool()
def gbif_occurrence_point_query(
    *,
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
        variables: GBIF occurrence variable names. Use the ``gbif_occurrence_available_variables()``
            tool to get a list of valid variable names. Defaults to a standard set of commonly used
            variables.
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

        full_var_info = get_variable_info(QueryType.OCCURRENCE)
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}
        unavailable_vars = [var for var in variables if var not in full_var_info]

        if not var_info:
            # All requested variables are unknown; skip the API call and return empty data.
            latency = time.perf_counter() - t0
            return _validate_grouped_geometry_response(
                {
                    "data": [],
                    "_meta": build_meta(
                        source="gbif",
                        query_params=query_params,
                        geometries_returned=0,
                        total_records_returned=0,
                        latency_s=latency,
                        license_info=LICENSE_INFO,
                        variables=variables,
                        variable_info={},
                        unavailable_variables=unavailable_vars,
                    ),
                }
            )

        valid_vars = list(var_info.keys())
        n_days = date_range_days(start_date, end_date)
        bbox = point_to_bbox(
            latitude=point.latitude, longitude=point.longitude, radius_km=radius_km
        )
        area_deg2 = (bbox["max_lat"] - bbox["min_lat"]) * (bbox["max_lon"] - bbox["min_lon"])
        if warn := estimate_query_runtime_s(n_days, area_deg2, max_runtime_s):
            return _validate_grouped_geometry_response(warn)
        data, unique_licenses = query_point(
            lat=point.latitude,
            lon=point.longitude,
            start_date=date_range.start_date,
            end_date=date_range.end_date,
            query_type=QueryType.OCCURRENCE,
            radius_km=radius_km,
            taxon_key=taxon_key,
            variables=valid_vars,
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
                    geometries_returned=len(data),
                    total_records_returned=sum(len(r["records"]) for r in data),
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
                    geometries_returned=0,
                    total_records_returned=0,
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
    *,
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
        min_lat: South boundary, decimal degrees, WGS84 (-90 to 90).
        max_lat: North boundary, decimal degrees, WGS84 (-90 to 90).
        min_lon: West boundary, decimal degrees, WGS84 (-180 to 180).
        max_lon: East boundary, decimal degrees, WGS84 (-180 to 180).
        start_date: Inclusive start date, ISO 8601 date string, e.g., "2019-08-15".
        end_date: Inclusive end date, ISO 8601 date string, e.g., "2019-08-16".
        taxon_key: Optional GBIF taxon key to restrict results to a single taxon.
        variables: GBIF occurrence variable names. Use the ``gbif_occurrence_available_variables()``
            tool to get a list of valid variable names. Defaults to a standard set of commonly used
            variables.
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

        full_var_info = get_variable_info(QueryType.OCCURRENCE)
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}
        unavailable_vars = [var for var in variables if var not in full_var_info]

        if not var_info:
            # All requested variables are unknown; skip the API call and return empty data.
            latency = time.perf_counter() - t0
            return _validate_grouped_geometry_response(
                {
                    "data": [],
                    "_meta": build_meta(
                        source="gbif",
                        query_params=query_params,
                        geometries_returned=0,
                        total_records_returned=0,
                        latency_s=latency,
                        license_info=LICENSE_INFO,
                        variables=variables,
                        variable_info={},
                        unavailable_variables=unavailable_vars,
                    ),
                }
            )

        valid_vars = list(var_info.keys())
        n_days = date_range_days(start_date, end_date)
        area_deg2 = (max_lat - min_lat) * (max_lon - min_lon)
        if warn := estimate_query_runtime_s(n_days, area_deg2, max_runtime_s):
            return _validate_grouped_geometry_response(warn)
        data, unique_licenses = query_bbox(
            min_lat=bbox.min_lat,
            max_lat=bbox.max_lat,
            min_lon=bbox.min_lon,
            max_lon=bbox.max_lon,
            start_date=date_range.start_date,
            end_date=date_range.end_date,
            query_type=QueryType.OCCURRENCE,
            taxon_key=taxon_key,
            variables=valid_vars,
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
                    geometries_returned=len(data),
                    total_records_returned=sum(len(r["records"]) for r in data),
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
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(e),
                    variables=variables,
                    variable_info=var_info,
                ),
            }
        )
