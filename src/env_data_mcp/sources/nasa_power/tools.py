"""MCP tool functions for the NASA POWER adapter."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from env_data_mcp.helpers import bbox_area_deg2, build_meta, date_range_days
from env_data_mcp.models import (
    AvailableVariablesResponse,
    BboxInput,
    DateRange,
    GroupedGeometryResponse,
    PointInput,
)
from env_data_mcp.server import mcp

from ._client import _get_variable_info, _open_store
from ._query import _estimate_query_runtime_s, _query_bbox, _query_point
from .constants import (
    DEFAULT_MERRA2_VARIABLES,
    DEFAULT_SYN1DEG_VARIABLES,
    MERRA2_INFO,
    SOURCE_INFO,
    SYN1DEG_INFO,
    DatasetType,
    TemporalResolution,
)


def _validate_available_variables_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize available_variables tool responses."""
    return AvailableVariablesResponse.model_validate(response).model_dump(by_alias=True)


def _validate_grouped_geometry_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize grouped geometry query responses."""
    return GroupedGeometryResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def nasa_power_merra2_available_variables() -> dict[str, Any]:
    """Return a list of available NASA POWER MERRA-2 variables with descriptions and units."""
    store = _open_store(DatasetType.MERRA2, TemporalResolution.DAILY)
    variable_info = _get_variable_info(store)
    return _validate_available_variables_response(
        {
            "data": variable_info,
            "_meta": build_meta(
                source="nasa_power",
                query_params={},
                rows_returned=len(variable_info),
                latency_s=0.0,
                license_info=SOURCE_INFO | MERRA2_INFO,
            ),
        }
    )


@mcp.tool()
def nasa_power_syn1deg_available_variables() -> dict[str, Any]:
    """Return a list of available NASA POWER SYN1deg variables with descriptions and units."""
    store = _open_store(DatasetType.SYN1DEG, TemporalResolution.DAILY)
    variable_info = _get_variable_info(store)
    return _validate_available_variables_response(
        {
            "data": variable_info,
            "_meta": build_meta(
                source="nasa_power",
                query_params={},
                rows_returned=len(variable_info),
                latency_s=0.0,
                license_info=SOURCE_INFO | SYN1DEG_INFO,
            ),
        }
    )


@mcp.tool()
def nasa_power_merra2_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    temporal_resolution: TemporalResolution,
    variables: list[str] = DEFAULT_MERRA2_VARIABLES,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA POWER MERRA-2 climate data for a point location.

    Returns weather variables grouped by nearest grid cell with a GeoJSON Point
    geometry, from the NASA POWER dataset via anonymous S3/Zarr.
    Global coverage, 1980–present.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        start_date: ISO 8601 date string, e.g. "2019-08-15".
        end_date: ISO 8601 date string, inclusive.
        temporal_resolution: "hourly", "daily", "monthly", "annual", or "climatology".
        variables: NASA POWER variable names. Use nasa_power_merra2_available_variables()
            tool to get a list of valid variable names. Defaults to a standard set of commonly
            used variables.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "temporal_resolution": temporal_resolution.value,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    var_info: dict[str, dict[str, str]] = {}
    try:
        point = PointInput(latitude=latitude, longitude=longitude)
        date_range = DateRange(start_date=start_date, end_date=end_date)

        full_var_info = _get_variable_info(_open_store(DatasetType.MERRA2, temporal_resolution))
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}


        n_days = date_range_days(start_date, end_date)
        if warn := _estimate_query_runtime_s(
            n_days, temporal_resolution, len(variables), area_deg2=0.0, max_runtime_s=max_runtime_s
        ):
            return _validate_grouped_geometry_response(warn)
        data, unavailable = _query_point(
            point.latitude,
            point.longitude,
            date_range.start_date,
            date_range.end_date,
            DatasetType.MERRA2,
            temporal_resolution,
            variables,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="nasa_power",
                    query_params=query_params,
                    rows_returned=len(data[0]["records"]) if data else 0,
                    latency_s=latency,
                    license_info=SOURCE_INFO | MERRA2_INFO,
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable if unavailable else None,
                ),
            }
        )
    except (ValidationError, ValueError, Exception) as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="nasa_power",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=SOURCE_INFO | MERRA2_INFO,
                    success=False,
                    error=str(exc),
                    variables=variables,
                    variable_info=var_info,
                ),
            }
        )


@mcp.tool()
def nasa_power_syn1deg_query(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    temporal_resolution: TemporalResolution,
    variables: list[str] = DEFAULT_SYN1DEG_VARIABLES,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA POWER SYN1deg surface radiation data for a point location.

    Returns daily surface radiation variables (shortwave and longwave, all-sky and clear-sky) from
    the NASA POWER dataset via anonymous S3/Zarr. Global coverage, 2001–present.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        start_date: ISO 8601 date string, e.g. "2019-08-15".
        end_date: ISO 8601 date string, inclusive.
        temporal_resolution: Temporal resolution of the data (e.g., daily, monthly).
        variables: NASA POWER SYN1deg variable names. Use nasa_power_syn1deg_available_variables()
            tool to get a list of valid variable names. Defaults to a standard set of commonly used
            surface radiation variables.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "temporal_resolution": temporal_resolution.value,
        "variables": variables,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    var_info: dict[str, dict[str, str]] = {}
    try:
        point = PointInput(latitude=latitude, longitude=longitude)
        date_range = DateRange(start_date=start_date, end_date=end_date)

        full_var_info = _get_variable_info(_open_store(DatasetType.SYN1DEG, temporal_resolution))
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}


        n_days = date_range_days(start_date, end_date)
        if warn := _estimate_query_runtime_s(
            n_days, temporal_resolution, len(variables), area_deg2=0.0, max_runtime_s=max_runtime_s
        ):
            return _validate_grouped_geometry_response(warn)
        data, unavailable = _query_point(
            point.latitude,
            point.longitude,
            date_range.start_date,
            date_range.end_date,
            DatasetType.SYN1DEG,
            temporal_resolution,
            variables,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="nasa_power",
                    query_params=query_params,
                    rows_returned=len(data[0]["records"]) if data else 0,
                    latency_s=latency,
                    license_info=SOURCE_INFO | SYN1DEG_INFO,
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable if unavailable else None,
                ),
            }
        )
    except (ValidationError, ValueError, Exception) as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="nasa_power",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=SOURCE_INFO | SYN1DEG_INFO,
                    success=False,
                    error=str(exc),
                    variables=variables,
                    variable_info=var_info,
                ),
            }
        )


@mcp.tool()
def nasa_power_merra2_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    temporal_resolution: TemporalResolution,
    variables: list[str] = DEFAULT_MERRA2_VARIABLES,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA POWER MERRA-2 climate data for a bounding-box area.

    Returns values for points within the bounding box, as well as the nearest points outside
    the box in each direction (if they exist) to allow for interpolation at the edges.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        start_date: ISO 8601 start date.
        end_date: ISO 8601 end date (inclusive).
        temporal_resolution: Temporal resolution of the data (e.g., daily, monthly).
        variables: NASA POWER MERRA-2 variable names (defaults to standard set). Use
            nasa_power_merra2_available_variables() tool to get a list of valid variable names.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    bbox = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)

    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "temporal_resolution": temporal_resolution.value,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    var_info: dict[str, dict[str, str]] = {}
    try:
        date_range = DateRange(start_date=start_date, end_date=end_date)

        full_var_info = _get_variable_info(_open_store(DatasetType.MERRA2, temporal_resolution))
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}


        n_days = date_range_days(start_date, end_date)
        if warn := _estimate_query_runtime_s(
            n_days,
            temporal_resolution,
            len(variables),
            area_deg2=bbox_area_deg2(bbox.model_dump()),
            max_runtime_s=max_runtime_s,
        ):
            return _validate_grouped_geometry_response(warn)
        data, unavailable = _query_bbox(
            bbox.min_lat,
            bbox.max_lat,
            bbox.min_lon,
            bbox.max_lon,
            date_range.start_date,
            date_range.end_date,
            DatasetType.MERRA2,
            temporal_resolution,
            variables,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="nasa_power",
                    query_params=query_params,
                    rows_returned=sum(len(r["records"]) for r in data),
                    latency_s=latency,
                    license_info=SOURCE_INFO | MERRA2_INFO,
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable if unavailable else None,
                ),
            }
        )
    except (ValidationError, ValueError, Exception) as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="nasa_power",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=SOURCE_INFO | MERRA2_INFO,
                    success=False,
                    error=str(exc),
                    variables=variables,
                    variable_info=var_info,
                ),
            }
        )


@mcp.tool()
def nasa_power_syn1deg_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    temporal_resolution: TemporalResolution,
    variables: list[str] = DEFAULT_SYN1DEG_VARIABLES,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query NASA POWER SYN1deg surface radiation data for a bounding-box area.

    Returns values for points within the bounding box, as well as the nearest points outside
    the box in each direction (if they exist) to allow for interpolation at the edges.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        start_date: ISO 8601 start date.
        end_date: ISO 8601 end date (inclusive).
        temporal_resolution: Temporal resolution of the data (e.g., daily, monthly).
        variables: NASA POWER SYN1deg variable names (defaults to standard set). Use
            nasa_power_syn1deg_available_variables() tool to get a list of valid variable names.
        max_runtime_s: Optional maximum runtime in seconds; if the query is estimated to
            exceed this, a warning is returned instead of data. If not provided, assumed to be 30 s.
    """
    bbox = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)

    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "variables": variables,
        "temporal_resolution": temporal_resolution.value,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    var_info: dict[str, dict[str, str]] = {}
    try:
        date_range = DateRange(start_date=start_date, end_date=end_date)

        full_var_info = _get_variable_info(_open_store(DatasetType.SYN1DEG, temporal_resolution))
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}


        n_days = date_range_days(start_date, end_date)
        if warn := _estimate_query_runtime_s(
            n_days,
            temporal_resolution,
            len(variables),
            area_deg2=bbox_area_deg2(bbox.model_dump()),
            max_runtime_s=max_runtime_s,
        ):
            return _validate_grouped_geometry_response(warn)
        data, unavailable = _query_bbox(
            bbox.min_lat,
            bbox.max_lat,
            bbox.min_lon,
            bbox.max_lon,
            date_range.start_date,
            date_range.end_date,
            DatasetType.SYN1DEG,
            temporal_resolution,
            variables,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="nasa_power",
                    query_params=query_params,
                    rows_returned=sum(len(r["records"]) for r in data),
                    latency_s=latency,
                    license_info=SOURCE_INFO | SYN1DEG_INFO,
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable if unavailable else None,
                ),
            }
        )
    except (ValidationError, ValueError, Exception) as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="nasa_power",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=SOURCE_INFO | SYN1DEG_INFO,
                    success=False,
                    error=str(exc),
                    variables=variables,
                    variable_info=var_info,
                ),
            }
        )
