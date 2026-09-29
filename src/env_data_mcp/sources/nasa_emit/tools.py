"""MCP tool functions for the NASA EMIT adapter."""

from __future__ import annotations

import os
import time
from typing import Any

from env_data_mcp.helpers import bbox_area_deg2, build_meta, check_runtime, date_range_days
from env_data_mcp.models import (
    BboxInput,
    DateRange,
    GroupedGeometryResponse,
    PointInput,
)
from env_data_mcp.server import mcp

from ._constants import LICENSE_INFO, VARIABLE_INFO
from ._query import query_bbox, query_point


def _validate_grouped_geometry_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize grouped geometry query responses."""
    return GroupedGeometryResponse.model_validate(response).model_dump(by_alias=True)


def _get_token(
    query_params: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Get the EARTHDATA token from the environment.

    If the environment variable doesn't exist, an error response is returned as the
    second argument.
    """
    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        return "", {
            "data": [],
            "_meta": build_meta(
                source="nasa_emit",
                query_params=query_params,
                geometries_returned=0,
                total_records_returned=0,
                latency_s=0,
                license_info=LICENSE_INFO,
                auth_required=True,
                auth_present=False,
                success=False,
                error=(
                    "EARTHDATA_TOKEN environment variable is not set. "
                    "Instructions for registering for a free token can be found here: "
                    "https://urs.earthdata.nasa.gov/documentation/for_users/user_token"
                ),
                variables=[key for key in VARIABLE_INFO],
                variable_info={key: val for key, val in VARIABLE_INFO.items()},
            ),
        }
    return token, None


@mcp.tool()
def nasa_emit_point_query(
    *,
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA EMIT surface mineral dust data for a point location.

    Returns mineral abundance for the queried area from the NASA EMIT dataset.
    Global coverage, 2022-08-09 to present.

    ### Args
    * __latitude__: Decimal degrees, WGS84 (-90 to 90).
    * __longitude__: Decimal degrees, WGS84 (-180 to 180).
    * __start_date__: Inclusive start date, ISO 8601 date string, e.g., "2023-08-15",
    * __end_date__: Inclusive end date, ISO 8601 date string, e.g., "2023-08-15".
    * __max_runtime_s__: Optional maximum runtime in seconds; if the query is estimated to
          exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    token, error = _get_token(query_params=query_params)
    if error:
        return error
    try:
        point = PointInput(latitude=latitude, longitude=longitude)
        date_range = DateRange(start_date=start_date, end_date=end_date)

        n_days = date_range_days(start_date=start_date, end_date=end_date)
        if warn := check_runtime(
            source="nasa_emit", n_days=n_days, area_deg2=0.0, max_runtime_s=max_runtime_s
        ):
            return _validate_grouped_geometry_response(warn)
        data = query_point(
            latitude=point.latitude,
            longitude=point.longitude,
            start_date=date_range.start_date,
            end_date=date_range.end_date,
            token=token,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="nasa_emit",
                    query_params=query_params,
                    geometries_returned=len(data),
                    total_records_returned=sum(len(r["records"]) for r in data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    variables=[key for key in VARIABLE_INFO],
                    variable_info={key: val for key, val in VARIABLE_INFO.items()},
                    auth_required=True,
                    auth_present=True,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="nasa_emit",
                    query_params=query_params,
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                    variables=[key for key in VARIABLE_INFO],
                    variable_info={key: val for key, val in VARIABLE_INFO.items()},
                    auth_required=True,
                    auth_present=True,
                ),
            }
        )


@mcp.tool()
def nasa_emit_bbox_query(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA EMIT surface mineral dust data for a bounding-box area.

    Returns mineral abundance for the queried area from the NASA EMIT dataset.
    Global coverage, 2022-08-09 to present.

    ### Args
    * __min_lat__: South boundary, decimal degrees, WGS84 (-90 to 90).
    * __max_lat__: North boundary, decimal degrees, WGS84 (-90 to 90).
    * __min_lon__: West boundary, decimal degrees, WGS84 (-180 to 180).
    * __max_lon__: East boundary, decimal degrees, WGS84 (-180 to 180).
    * __start_date__: Inclusive start date, ISO 8601 date string, e.g., "2023-08-15",
    * __end_date__: Inclusive end date, ISO 8601 date string, e.g., "2023-08-15".
    * __max_runtime_s__: Optional maximum runtime in seconds; if the query is estimated to
          exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.

    """
    bbox = BboxInput(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    token, error = _get_token(query_params=query_params)
    if error:
        return error
    try:
        date_range = DateRange(start_date=start_date, end_date=end_date)
        n_days = date_range_days(start_date=start_date, end_date=end_date)
        if warn := check_runtime(
            source="nasa_emit",
            n_days=n_days,
            area_deg2=bbox_area_deg2(bbox.model_dump()),
            max_runtime_s=max_runtime_s,
        ):
            return _validate_grouped_geometry_response(warn)
        data = query_bbox(
            min_lat=bbox.min_lat,
            max_lat=bbox.max_lat,
            min_lon=bbox.min_lon,
            max_lon=bbox.max_lon,
            start_date=date_range.start_date,
            end_date=date_range.end_date,
            token=token,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="nasa_emit",
                    query_params=query_params,
                    geometries_returned=len(data),
                    total_records_returned=sum(len(r["records"]) for r in data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    variables=[key for key in VARIABLE_INFO],
                    variable_info={key: val for key, val in VARIABLE_INFO.items()},
                    auth_required=True,
                    auth_present=True,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="nasa_emit",
                    query_params=query_params,
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                    variables=[key for key in VARIABLE_INFO],
                    variable_info={key: val for key, val in VARIABLE_INFO.items()},
                    auth_required=True,
                    auth_present=True,
                ),
            }
        )
