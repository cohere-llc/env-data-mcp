"""MCP tool functions for the ESS-DIVE adapter."""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Any

from env_data_mcp.helpers import (
    bbox_area_deg2,
    build_meta,
    check_runtime,
    date_range_days,
    point_to_bbox,
)
from env_data_mcp.models import (
    BboxInput,
    GroupedGeometryResponse,
    PointInput,
)
from env_data_mcp.server import mcp

from ._constants import LICENSE_INFO
from ._query import query_bbox, query_point


def _validate_grouped_geometry_results(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize grouped geometry response."""
    return GroupedGeometryResponse.model_validate(response).model_dump(by_alias=True)


def _get_api_key() -> str | None:
    """Get ESS-DIVE API key from the environment.

    If the environment variable ``ESSDIVE_TOKEN`` doesn't exist, ``None`` is returned.
    """
    return os.environ.get("ESSDIVE_TOKEN")


@mcp.tool()
def essdive_point_query(
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    start_date: str | None = None,
    end_date: str | None = None,
    keywords: list[str] | None = None,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query ESS-DIVE for datasets intersecting a point location.

    Returns dataset information grouped by GeoJSON geometries corresponding
    to the dataset study region. Dataset information includes license, citation,
    funding, variables-measured, techniques, and a list of dataset files, including
    URLs for each file.

    Note that geometries outside the requested area will be returned when datasets
    include sites within and outside the specified region.

    ESS-DIVE datasets with no spatial coverage listed will be grouped by the requested
    ``Point`` geometry.

    When ``keywords``, ``start_date``, and/or ``end_date`` are omitted, there are no
    corresponding filters applied to the query.

    ### Args
    * __latitude__: Decimal degrees, WGS84 (-90 to 90).
    * __longitude__: Decimal degrees, WGS84 (-180 to 180).
    * __start_date__: Inclusive start date, ISO 8601 date string, e.g., "2019-08-15".
    * __end_date__: Inclusive end date, ISO 8601 date string, e.g., "2019-08-16".
    * __radius_km__: Search radius in kilometers. Defaults to 5 km. Maximum 25.0 km.
    * __keywords__: Optional set of keywords to filter dataset results by. If omitted, all
          intersecting datasets are returned.
    * __max_runtime_s__: Optional maximum runtime in seconds. If the query is estimated to
          exceed this, a warning is returned instead of data. If not provided, it is
          assumed to be 30 s.
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "keywords": keywords,
        "radius_km": radius_km,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    try:
        point = PointInput(latitude=latitude, longitude=longitude)

        n_days = date_range_days(start_date or "1990-01-01", end_date or date.today().isoformat())
        area_deg2 = bbox_area_deg2(point_to_bbox(latitude, longitude, radius_km))
        if warn := check_runtime(
            source="ess-dive",
            n_days=n_days,
            area_deg2=area_deg2,
            max_runtime_s=max_runtime_s,
        ):
            return _validate_grouped_geometry_results(warn)
        data = query_point(
            point.latitude,
            point.longitude,
            radius_km,
            start_date,
            end_date,
            keywords,
            _get_api_key(),
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_results(
            {
                "data": data,
                "_meta": build_meta(
                    source="ess-dive",
                    query_params=query_params,
                    geometries_returned=len(data),
                    total_records_returned=sum(len(group["records"]) for group in data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_results(
            {
                "data": [],
                "_meta": build_meta(
                    source="ess-dive",
                    query_params=query_params,
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )


@mcp.tool()
def essdive_bbox_query(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str | None = None,
    end_date: str | None = None,
    keywords: list[str] | None = None,
    max_runtime_s: float = 30.0,
) -> dict[str, Any]:
    """Query ESS-DIVE for datasets intersecting a point location.

    Returns dataset information grouped by GeoJSON geometries corresponding
    to the dataset study region. Dataset information includes license, citation,
    funding, variables-measured, techniques, and a list of dataset files, including
    URLs for each file.

    Note that geometries outside the requested area will be returned when datasets
    include sites within and outside the specified region.

    ESS-DIVE datasets with no spatial coverage listed will be grouped by the requested
    ``Polygon`` geometry.

    When ``keywords``, ``start_date``, and/or ``end_date`` are omitted, there are no
    corresponding filters applied to the query.

    ### Args
    * __min_lat__: South boundary, decimal degrees, WGS84 (-90 to 90).
    * __max_lat__: North boundary, decimal degrees, WGS84 (-90 to 90).
    * __min_lon__: West boundary, decimal degrees, WGS84 (-180 to 180).
    * __max_lon__: East boundary, decimal degrees, WGS84 (-180 to 180).
    * __start_date__: Inclusive start date, ISO 8601 date string, e.g., "2019-08-15".
    * __end_date__: Inclusive end date, ISO 8601 date string, e.g., "2019-08-16".
    * __keywords__: Optional set of keywords to filter dataset results by. If omitted, all
          intersecting datasets are returned.
    * __max_runtime_s__: Optional maximum runtime in seconds. If the query is estimated to
          exceed this, a warning is returned instead of data. If not provided, it is
          assumed to be 30 s.
    """
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "keywords": keywords,
        "max_runtime_s": max_runtime_s,
    }
    t0 = time.perf_counter()
    try:
        bbox = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)

        n_days = date_range_days(start_date or "1990-01-01", end_date or date.today().isoformat())
        area_deg2 = bbox_area_deg2(bbox.model_dump())
        if warn := check_runtime(
            source="ess-dive",
            n_days=n_days,
            area_deg2=area_deg2,
            max_runtime_s=max_runtime_s,
        ):
            return _validate_grouped_geometry_results(warn)
        data = query_bbox(
            bbox.min_lat,
            bbox.max_lat,
            bbox.min_lon,
            bbox.max_lon,
            start_date,
            end_date,
            keywords,
            _get_api_key(),
        )
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_results(
            {
                "data": data,
                "_meta": build_meta(
                    source="ess-dive",
                    query_params=query_params,
                    geometries_returned=len(data),
                    total_records_returned=sum(len(group["records"]) for group in data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_results(
            {
                "data": [],
                "_meta": build_meta(
                    source="ess-dive",
                    query_params=query_params,
                    geometries_returned=0,
                    total_records_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )
