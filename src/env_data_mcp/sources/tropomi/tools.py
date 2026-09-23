"""MCP tool functions for the Sentinel 5-TROPOMI adapter."""

from __future__ import annotations

import time
from typing import Any

from env_data_mcp.helpers import bbox_area_deg2, build_meta, check_runtime, parse_date
from env_data_mcp.models import (
    AvailableVariablesResponse,
    BboxInput,
    DateRange,
    GroupedGeometryResponse,
    PointInput,
)
from env_data_mcp.server import mcp

from ._constants import DEFAULT_VARIABLES, LICENSE_INFO
from ._query import query_bbox, query_point
from ._var_cache import get_variable_info


def _validate_available_variables_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize available variables tool response."""
    return AvailableVariablesResponse.model_validate(response).model_dump(by_alias=True)


def _validate_grouped_geometry_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize grouped geometry query responses."""
    return GroupedGeometryResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def tropomi_available_variables() -> dict[str, Any]:
    """Return a list of available TROPOMI variables with descriptions."""
    t0 = time.perf_counter()
    try:
        variable_info = get_variable_info()
        latency = time.perf_counter() - t0
        return _validate_available_variables_response(
            {
                "data": variable_info,
                "_meta": build_meta(
                    source="tropomi",
                    query_params={},
                    geometries_returned=0,
                    total_records_returned=len(variable_info),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                ),
            }
        )
    except Exception as e:
        latency = time.perf_counter() - t0
        return _validate_available_variables_response(
            {
                "data": {},
                "_meta": build_meta(
                    source="tropomi",
                    query_params={},
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(e),
                ),
            }
        )


@mcp.tool()
def tropomi_point_query(
    *,
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    variables: frozenset[str] | list[str] = DEFAULT_VARIABLES,
    max_runtime_s: float = 60,
) -> dict[str, Any]:
    """Query Sentinel5-TROPOMI data for a point location.

    Returns atmospheric composition data grouped by nearest grid cell with a GeoJSON Point
    geometry, from the TROPOMI dataset via AWS.
    Global coverage, July 2018-present.

    ### Args
    * __latitude__: Decimal degrees, WGS84 (-90 to 90).
    * __longitude__: Decimal degrees, WGS84 (-180 to 180).
    * __start_date__: Inclusive start date, ISO 8601 date string, e.g., "2019-08-15",
    * __end_date__: Inclusive end date, ISO 8601 date string, e.g., "2019-08-15".
    * __variables__: TROPOMI variable names. Use the ``tropomi_available_variables()`` tool to get
          a list of valid variable names. Defaults to a set of commonly used variables.
    * __max_runtime_s__: Optional maximum runtime in seconds; if the query is estimated to
          exceed this, a warning is returned instead of data. If not provided, assumed to
          be 60s.
    """
    variables = list(variables)
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    try:
        point = PointInput(latitude=latitude, longitude=longitude)
        date_range = DateRange(start_date=start_date, end_date=end_date)

        full_var_info = get_variable_info()
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}

        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        if warn := check_runtime(
            source="tropomi",
            n_days=n_days,
            area_deg2=0.0,
            max_runtime_s=max_runtime_s,
            scale_factor=len(variables),
        ):
            return _validate_grouped_geometry_response(warn)
        data, unavailable = query_point(
            point.latitude,
            point.longitude,
            date_range.start_date,
            date_range.end_date,
            variables,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="tropomi",
                    query_params=query_params,
                    geometries_returned=len(data),
                    total_records_returned=sum(len(r["records"]) for r in data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable,
                ),
            }
        )
    except Exception as e:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="tropomi",
                    query_params=query_params,
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(e),
                    variables=variables,
                    variable_info={},
                ),
            }
        )


@mcp.tool()
def tropomi_bbox_query(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    variables: frozenset[str] | list[str] = DEFAULT_VARIABLES,
    max_runtime_s: float = 60.0,
) -> dict[str, Any]:
    """Query Sentinel5-TROPOMI data within a bounding box.

    Returns atmospheric composition data grouped by grid cell with a GeoJSON Point
    geometry, from the TROPOMI dataset via AWS.
    Global coverage, July 2018-present.

    ### Args
    * __min_lat__: South boundary, decimal degrees, WGS84 (-90 to 90).
    * __max_lat__: North boundary, decimal degrees, WGS84 (-90 to 90).
    * __min_lon__: West boundary, decimal degrees, WGS84 (-180 to 180).
    * __max_lon__: East boundary, decimal degrees, WGS84 (-180 to 180).
    * __start_date__: Inclusive start date, ISO 8601 date string, e.g., "2019-08-15",
    * __end_date__: Inclusive end date, ISO 8601 date string, e.g., "2019-08-15".
    * __variables__: TROPOMI variable names. Use the ``tropomi_available_variables()`` tool to get
          a list of valid variable names. Defaults to a set of commonly used variables.
    * __max_runtime_s__: Optional maximum runtime in seconds; if the query is estimated to
          exceed this, a warning is returned instead of data. If not provided, assumed to
          be 60s.
    """
    variables = list(variables)
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    try:
        bbox = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)
        date_range = DateRange(start_date=start_date, end_date=end_date)

        full_var_info = get_variable_info()
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}

        _sd = parse_date(start_date)
        _ed = parse_date(end_date)
        n_days = (_ed - _sd).days + 1
        if warn := check_runtime(
            source="tropomi",
            n_days=n_days,
            area_deg2=bbox_area_deg2(bbox.model_dump()),
            max_runtime_s=max_runtime_s,
            scale_factor=len(variables),
        ):
            return _validate_grouped_geometry_response(warn)
        data, unavailable = query_bbox(
            bbox.min_lat,
            bbox.max_lat,
            bbox.min_lon,
            bbox.max_lon,
            date_range.start_date,
            date_range.end_date,
            variables,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="tropomi",
                    query_params=query_params,
                    geometries_returned=len(data),
                    total_records_returned=sum(len(r["records"]) for r in data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable,
                ),
            }
        )
    except Exception as e:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="tropomi",
                    query_params=query_params,
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(e),
                    variables=variables,
                    variable_info={},
                ),
            }
        )
