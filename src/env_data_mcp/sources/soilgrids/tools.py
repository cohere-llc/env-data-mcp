"""MCP tool functions for the SoilGrids adapter."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from typing import Any

from env_data_mcp.helpers import bbox_area_deg2, build_meta, check_runtime, point_to_bbox
from env_data_mcp.models import (
    AvailableVariablesResponse,
    BboxInput,
    GroupedGeometryResponse,
    PointInput,
)
from env_data_mcp.server import mcp

from ._constants import DEFAULT_VARIABLES, LICENSE_INFO
from ._query import query_bbox
from ._var_cache import VariableInfo, get_base_variable_list, get_variable_info


def _validate_available_variable_response(response: dict[str, Any]) -> dict[str, Any]:
    return AvailableVariablesResponse.model_validate(response).model_dump(by_alias=True)


def _validate_grouped_geometry_response(response: dict[str, Any]) -> dict[str, Any]:
    return GroupedGeometryResponse.model_validate(response).model_dump(by_alias=True)


@mcp.tool()
def soilgrids_available_variables() -> dict[str, Any]:
    """Return a list of available SoilGrids variables with descriptions and units."""
    t0 = time.perf_counter()
    base_info = get_base_variable_list()
    var_info_raw: dict[str, VariableInfo] = {}

    max_workers = min(8, max(1, len(base_info)))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(get_variable_info, base) for base in base_info]

        for future in as_completed(futures):
            with suppress(Exception):  # skip any variables that couldn't be retrieved
                var_info_raw |= future.result()

    var_info = {
        key: {"description": val.description, "units": val.units}
        for key, val in var_info_raw.items()
    }
    return _validate_available_variable_response(
        {
            "data": var_info,
            "_meta": build_meta(
                source="soilgrids",
                query_params={},
                geometries_returned=0,
                total_records_returned=len(var_info),
                latency_s=time.perf_counter() - t0,
                license_info=LICENSE_INFO,
            ),
        }
    )


@mcp.tool()
def soilgrids_point_query(
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    variables: frozenset[str] | list[str] = DEFAULT_VARIABLES,
    max_runtime_s: float = 60.0,
) -> dict[str, Any]:
    """Query SoilGrids soil properties for a point location.

    Returns soil properties grouped by the nearest grid cell with a GeoJSON Point
    geometry, from the SoilGrids WebCoverageService.
    Global coverage at 250 m resolution, present time.

    Note: if the radius you specify is smaller than the 250 m resolution of the SoilGrids
    data, no results may be returned.

    ### Args
    * __latitude__: Decimal degrees, WGS84 (-90 to 90).
    * __longitude__: Decimal degrees, WGS84 (-180 to 180).
    * __radius_km__: Search radius in kilometers.
    * __variables__: SoilGrids variable names. Use the ``soilgrids_available_variables()`` tool to
          get a list of valid variable names. Defaults to a set of commonly
          used variables near the surface.
    * __max_runtime_s__: Optional maximum runtime in seconds; if the query is estimated to
          exceed this, a warning is returned instead of data. If not provided, assumed
          to be 60 s.
    """
    variables = list(variables)
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": radius_km,
        "variables": variables,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    var_info: dict[str, dict[str, str]] = {}
    try:
        point = PointInput(latitude=latitude, longitude=longitude)
        bbox = point_to_bbox(
            latitude=point.latitude, longitude=point.longitude, radius_km=radius_km
        )

        full_var_info = soilgrids_available_variables().get("data", {})
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}

        if warn := check_runtime(
            source="soilgrids",
            n_days=0,
            area_deg2=bbox_area_deg2(bbox),
            max_runtime_s=max_runtime_s,
            scale_factor=len(variables),
        ):
            warn["_meta"]["variables"] = variables
            return _validate_grouped_geometry_response(warn)
        data, unavailable_variables = query_bbox(
            min_lat=bbox["min_lat"],
            max_lat=bbox["max_lat"],
            min_lon=bbox["min_lon"],
            max_lon=bbox["max_lon"],
            variables=variables,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="soilgrids",
                    query_params=query_params,
                    geometries_returned=len(data),
                    total_records_returned=sum(len(r["records"]) for r in data),
                    latency_s=latency,
                    license_info={**LICENSE_INFO},
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable_variables,
                ),
            }
        )
    except Exception as e:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="soilgrids",
                    query_params=query_params,
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info={**LICENSE_INFO},
                    success=False,
                    error=str(e),
                    variables=variables,
                    variable_info=var_info,
                ),
            }
        )


@mcp.tool()
def soilgrids_bbox_query(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: frozenset[str] | list[str] = DEFAULT_VARIABLES,
    max_runtime_s: float = 60.0,
) -> dict[str, Any]:
    """Query SoilGrids soil properties for a bounding box region.

    Returns soil properties grouped by GeoJSON Point geometry, from the SoilGrids
    WebCoverageService. Global coverage at 250 m resolution, present time.

    Note: if your bounding box is smaller than the 250 m resoltion of the SoilGrids data,
    no results may be returned.

    ### Args
    * __min_lat__: South boundary, decimal degrees, WGS84 (-90 to 90).
    * __max_lat__: North boundary, decimal degrees, WGS84 (-90 to 90).
    * __min_lon__: West boundary, decimal degrees, WGS84 (-180 to 180).
    * __max_lon__: East boundary, decimal degrees, WGS84 (-180 to 180).
    * __variables__: SoilGrids variable names. Use the ``soilgrids_available_variables()`` tool to
          get a list of valid variable names. Defaults to a set of commonly
          used variables near the surface.
    * __max_runtime_s__: Optional maximum runtime in seconds; if the query is estimated to
          exceed this, a warning is returned instead of data. If not provided, assumed
          to be 60 s.
    """
    variables = list(variables)
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "variables": variables,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    var_info: dict[str, dict[str, str]] = {}
    try:
        bbox = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)

        full_var_info = soilgrids_available_variables().get("data", {})
        var_info = {k: full_var_info[k] for k in variables if k in full_var_info}

        if warn := check_runtime(
            source="soilgrids",
            n_days=0,
            area_deg2=bbox_area_deg2(bbox.model_dump()),
            max_runtime_s=max_runtime_s,
            scale_factor=len(variables),
        ):
            warn["_meta"]["variables"] = variables
            return _validate_grouped_geometry_response(warn)
        data, unavailable_variables = query_bbox(
            min_lat=bbox.min_lat,
            max_lat=bbox.max_lat,
            min_lon=bbox.min_lon,
            max_lon=bbox.max_lon,
            variables=variables,
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="soilgrids",
                    query_params=query_params,
                    geometries_returned=len(data),
                    total_records_returned=sum(len(r["records"]) for r in data),
                    latency_s=latency,
                    license_info={**LICENSE_INFO},
                    variables=variables,
                    variable_info=var_info,
                    unavailable_variables=unavailable_variables,
                ),
            }
        )
    except Exception as e:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="soilgrids",
                    query_params=query_params,
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info={**LICENSE_INFO},
                    success=False,
                    error=str(e),
                    variables=variables,
                    variable_info=var_info,
                ),
            }
        )
