"""Shared query logic and all MCP tool functions for the SSURGO adapter."""

from __future__ import annotations

import math
import time
from typing import Any

import httpx
from pydantic import ValidationError

from env_data_mcp.helpers import bbox_to_wkt_polygon, build_meta, check_runtime
from env_data_mcp.models import (
    AvailableVariablesResponse,
    BboxInput,
    GroupedGeometryResponse,
    PointInput,
    SuitabilityRulesResponse,
)
from env_data_mcp.server import mcp

from ._client import _fetch_mukey_geometries, _fetch_sda, _get_variable_info, _parse_xml
from .constants import (
    _NO_COVERAGE_MSG,
    _SDA_URL,
    _SOIL_SUITABILITY_RULES_SQL,
    DEFAULT_AREA_SUMMARY_VARIABLES,
    DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    DEFAULT_PARENT_MATERIAL_VARIABLES,
    DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    DEFAULT_SOIL_PROFILE_VARIABLES,
    DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    LICENSE_INFO,
    _QueryType,
)
from .sql import (
    _build_area_summary_sql,
    _build_ecological_site_sql,
    _build_parent_material_sql,
    _build_seasonal_hydrology_sql,
    _build_soil_profile_sql,
    _build_soil_suitability_sql,
    _build_soil_temperature_sql,
    _build_subsurface_barriers_sql,
    _resolve_rule_names,
    _resolve_variables,
)

# Degrees of buffer added around a point when fetching map-unit polygon geometries
# via the SDA WFS endpoint (~5.5 km at mid-latitudes).
_GEOM_BBOX_BUFFER_DEG = 0.05

# ---------------------------------------------------------------------------
# Shared query helpers
# ---------------------------------------------------------------------------


def _group_by_mukey(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group flat SDA result rows by mukey.

    Returns a dict mapping mukey → {"muname": str, "rows": list[dict]}.
    The ``mukey`` and ``muname`` keys are lifted to the group header; all
    other column values remain in the inner row dicts.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for row in records:
        mk = row.get("mukey", "")
        if mk not in grouped:
            grouped[mk] = {"muname": row.get("muname", ""), "rows": []}
        inner = {k: v for k, v in row.items() if k not in ("mukey", "muname")}
        grouped[mk]["rows"].append(inner)
    return grouped


def _validate_available_variables_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize available_variables responses."""
    return AvailableVariablesResponse.model_validate(response).model_dump(by_alias=True)


def _validate_grouped_geometry_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize grouped map-unit responses."""
    return GroupedGeometryResponse.model_validate(response).model_dump(by_alias=True)


def _validate_suitability_rules_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize soil suitability rule-name responses."""
    return SuitabilityRulesResponse.model_validate(response).model_dump(by_alias=True)


def _available_vars_response(query_type: _QueryType) -> dict[str, Any]:
    """Discover available columns via XSD schema introspection.

    Columns are enriched with ``description`` and ``units`` parsed from the SDA
    Tables and Columns Report PDF when available.
    """
    t0 = time.perf_counter()
    try:
        info = _get_variable_info(query_type)
        latency = time.perf_counter() - t0
        flat: dict[str, dict[str, Any]] = {
            col: {
                "description": meta.get("label") or "",
                "units": meta.get("units") or "",
            }
            for col, meta in info.items()
        }
        return _validate_available_variables_response(
            {
                "data": flat,
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={"query_type": query_type},
                    rows_returned=len(info),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_available_variables_response(
            {
                "data": {},
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={"query_type": query_type},
                    rows_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )


def _point_query(
    latitude: float,
    longitude: float,
    variables: list[str],
    sql_builder: Any,
    max_runtime_s: float | None,
    query_type: _QueryType,
) -> dict[str, Any]:
    """Shared implementation for all point-query MCP tools."""
    if warn := check_runtime("ssurgo", 0, 0.0, max_runtime_s):
        return _validate_grouped_geometry_response(warn)
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError(f"latitude and longitude must be finite; got {latitude!r}, {longitude!r}")
    try:
        point = PointInput(latitude=latitude, longitude=longitude)
    except ValidationError as exc:
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={"latitude": latitude, "longitude": longitude},
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )
    try:
        vars_ = _resolve_variables(variables)
    except ValueError as exc:
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={"latitude": latitude, "longitude": longitude},
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )
    user_vars = vars_
    sql_vars = ["mukey", "muname"] + [v for v in vars_ if v not in ("mukey", "muname")]
    wkt = f"POINT({point.longitude} {point.latitude})"
    query_params: dict[str, Any] = {
        "latitude": point.latitude,
        "longitude": point.longitude,
        "variables": user_vars,
        "max_runtime_s": max_runtime_s,
        "query_type": query_type,
    }
    t0 = time.perf_counter()
    try:
        full_info = _get_variable_info(query_type)
        sql = sql_builder(wkt, sql_vars)
        records, latency = _fetch_sda(sql)
        grouped = _group_by_mukey(records)
        _buf = _GEOM_BBOX_BUFFER_DEG
        geo_bbox = (
            point.longitude - _buf,
            point.latitude - _buf,
            point.longitude + _buf,
            point.latitude + _buf,
        )
        geometries = _fetch_mukey_geometries(list(grouped.keys()), geo_bbox)
        data = [
            {
                "mukey": mk,
                "muname": info["muname"],
                "geometry": geometries.get(mk),
                "records": info["rows"],
            }
            for mk, info in grouped.items()
        ]
        # Derive vinfo from actual result columns so always-included context
        # columns (compname, hzname, depth bounds, etc.) appear in the metadata.
        result_cols = next(
            (list(rows["rows"][0].keys()) for rows in grouped.values() if rows["rows"]),
            user_vars,
        )
        vinfo = {
            v: {
                "description": full_info[v].get("label", ""),
                "units": full_info[v].get("units", ""),
            }
            for v in result_cols
            if v in full_info
        }
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="ssurgo",
                    variables=user_vars,
                    query_params=query_params,
                    rows_returned=len(data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    variable_info=vinfo,
                    error=_NO_COVERAGE_MSG if not data else None,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )


def _bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str],
    sql_builder: Any,
    max_runtime_s: float | None,
    query_type: _QueryType,
) -> dict[str, Any]:
    """Shared implementation for all bbox-query MCP tools."""
    try:
        bbox = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)
    except ValidationError as exc:
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={
                        "min_lat": min_lat,
                        "max_lat": max_lat,
                        "min_lon": min_lon,
                        "max_lon": max_lon,
                    },
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )
    area_deg2 = (bbox.max_lat - bbox.min_lat) * (bbox.max_lon - bbox.min_lon)
    if warn := check_runtime("ssurgo", 0, area_deg2, max_runtime_s):
        return _validate_grouped_geometry_response(warn)
    base_params: dict[str, Any] = {
        "min_lat": bbox.min_lat,
        "max_lat": bbox.max_lat,
        "min_lon": bbox.min_lon,
        "max_lon": bbox.max_lon,
    }
    try:
        vars_ = _resolve_variables(variables)
    except ValueError as exc:
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params=base_params,
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )
    user_vars = vars_
    sql_vars = ["mukey", "muname"] + [v for v in vars_ if v not in ("mukey", "muname")]
    wkt = bbox_to_wkt_polygon(bbox.model_dump())
    query_params: dict[str, Any] = {
        **base_params,
        "variables": user_vars,
        "max_runtime_s": max_runtime_s,
        "query_type": query_type,
    }
    t0 = time.perf_counter()
    try:
        full_info = _get_variable_info(query_type)
        sql = sql_builder(wkt, sql_vars)
        records, latency = _fetch_sda(sql)
        grouped = _group_by_mukey(records)
        geo_bbox = (bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat)
        geometries = _fetch_mukey_geometries(list(grouped.keys()), geo_bbox)
        data = [
            {
                "mukey": mk,
                "muname": info["muname"],
                "geometry": geometries.get(mk),
                "records": info["rows"],
            }
            for mk, info in grouped.items()
        ]
        total_records = sum(len(g["records"]) for g in data)
        # Derive vinfo from actual result columns so always-included context
        # columns (compname, hzname, depth bounds, etc.) appear in the metadata.
        result_cols = next(
            (list(rows["rows"][0].keys()) for rows in grouped.values() if rows["rows"]),
            user_vars,
        )
        vinfo = {
            v: {
                "description": full_info[v].get("label", ""),
                "units": full_info[v].get("units", ""),
            }
            for v in result_cols
            if v in full_info
        }
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="ssurgo",
                    variables=user_vars,
                    query_params=query_params,
                    rows_returned=len(data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    variable_info=vinfo,
                    error=_NO_COVERAGE_MSG if not data else None,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )


# ---------------------------------------------------------------------------
# MCP tools — Type 1: soil_profile
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_soil_profile_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO soil profile queries.

    Queries the SDA column catalogue for the tables joined in soil profile
    queries: ``mapunit``, ``component``, and ``chorizon``.  Use the
    ``variable`` values as the ``variables`` argument to
    ``ssurgo_soil_profile_query`` or ``ssurgo_soil_profile_bbox_query``.
    """
    return _available_vars_response(_QueryType.SOIL_PROFILE)


@mcp.tool()
def ssurgo_soil_profile_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_SOIL_PROFILE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil profile data for a point location.

    Returns per-horizon physical and chemical properties for the major soil
    components at the given location.  Default variables include texture
    (sand/silt/clay), pH, organic matter, saturated hydraulic conductivity,
    available water capacity, and bulk density.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include in the response.  Defaults to a
            curated horizon-property set.  Call
            ``ssurgo_soil_profile_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _build_soil_profile_sql,
        max_runtime_s,
        _QueryType.SOIL_PROFILE,
    )


@mcp.tool()
def ssurgo_soil_profile_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_SOIL_PROFILE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil profile data for all map units in a bounding box.

    Returns per-horizon data for every soil map unit whose boundary intersects
    the requested bounding box.  Large regions can return many records; use
    ``max_runtime_s`` to add a runtime guard.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.  Defaults to the same curated
            set as ``ssurgo_soil_profile_query``.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _build_soil_profile_sql,
        max_runtime_s,
        _QueryType.SOIL_PROFILE,
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 2: area_summary
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_area_summary_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO area summary queries.

    Queries the SDA column catalogue for ``mapunit`` and ``muaggatt``.  Use
    the ``variable`` values as the ``variables`` argument to
    ``ssurgo_area_summary_query`` or ``ssurgo_area_summary_bbox_query``.
    """
    return _available_vars_response(_QueryType.AREA_SUMMARY)


@mcp.tool()
def ssurgo_area_summary_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_AREA_SUMMARY_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO pre-aggregated area summary data for a point location.

    Returns one row per map unit with NRCS-precomputed weighted averages:
    drainage class, hydrologic group, available water storage, soil organic
    carbon stock, crop productivity index, flooding frequency, and water table
    depth.  No per-horizon aggregation is needed.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_area_summary_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _build_area_summary_sql,
        max_runtime_s,
        _QueryType.AREA_SUMMARY,
    )


@mcp.tool()
def ssurgo_area_summary_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_AREA_SUMMARY_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO area summary data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.  Defaults to the same curated
            set as ``ssurgo_area_summary_query``.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _build_area_summary_sql,
        max_runtime_s,
        _QueryType.AREA_SUMMARY,
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 3: subsurface_barriers
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_subsurface_barriers_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO subsurface barrier queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``, and
    ``corestrictions``.
    """
    return _available_vars_response(_QueryType.SUBSURFACE_BARRIERS)


@mcp.tool()
def ssurgo_subsurface_barriers_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO subsurface barrier (restrictive layer) data for a point.

    Returns depth and hardness of layers that limit rooting, drainage, or
    excavation, such as bedrock, fragipan, duripan, and cemented horizons.
    Rows with no restrictive layers will have NULL values for restriction
    columns.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_subsurface_barriers_available_variables()`` for the full
            list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _build_subsurface_barriers_sql,
        max_runtime_s,
        _QueryType.SUBSURFACE_BARRIERS,
    )


@mcp.tool()
def ssurgo_subsurface_barriers_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO subsurface barrier data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _build_subsurface_barriers_sql,
        max_runtime_s,
        _QueryType.SUBSURFACE_BARRIERS,
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 4: seasonal_hydrology
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_seasonal_hydrology_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO seasonal hydrology queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``,
    ``comonth``, and ``cosoilmoist``.
    """
    return _available_vars_response(_QueryType.SEASONAL_HYDROLOGY)


@mcp.tool()
def ssurgo_seasonal_hydrology_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO seasonal hydrology data for a point location.

    Returns monthly flooding frequency, ponding, and water table depth for
    the major soil components.  Typically 12 rows per component (one per
    calendar month).  Months with no wet-layer data will have NULL values for
    ``soimoistdept_r`` and ``soimoiststat``.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_seasonal_hydrology_available_variables()`` for the full
            list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _build_seasonal_hydrology_sql,
        max_runtime_s,
        _QueryType.SEASONAL_HYDROLOGY,
    )


@mcp.tool()
def ssurgo_seasonal_hydrology_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO seasonal hydrology data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _build_seasonal_hydrology_sql,
        max_runtime_s,
        _QueryType.SEASONAL_HYDROLOGY,
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 5: soil_suitability
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_soil_suitability_available_rule_names() -> dict[str, Any]:
    """Return all available interpretation rule names for SSURGO soil suitability queries.

    Queries ``cointerp`` for distinct ``mrulename`` values.  Use these names
    as the ``rule_names`` argument to ``ssurgo_soil_suitability_query`` or
    ``ssurgo_soil_suitability_bbox_query``.
    """
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(_SDA_URL, data={"query": _SOIL_SUITABILITY_RULES_SQL})
            resp.raise_for_status()
        latency = time.perf_counter() - t0
        records = _parse_xml(resp.text)
        rule_names = [r["mrulename"] for r in records if r.get("mrulename")]
        return _validate_suitability_rules_response(
            {
                "data": rule_names,
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={"query_type": "soil_suitability"},
                    rows_returned=len(rule_names),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_suitability_rules_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={"query_type": "soil_suitability"},
                    rows_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )


@mcp.tool()
def ssurgo_soil_suitability_query(
    latitude: float,
    longitude: float,
    rule_names: list[str] = DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil suitability (interpretation) data for a point location.

    Returns pre-computed NRCS suitability ratings for the requested
    interpretation rules.  Each row contains the rule name, a class label
    (e.g. 'Not limited', 'Very limited'), and a numeric rating (0–1).

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        rule_names: Interpretation rule names to query.  Defaults to a set
            covering construction suitability, septic systems, agricultural
            capability, and hydric soil status.  Call
            ``ssurgo_soil_suitability_available_rule_names()`` for all rules.
        max_runtime_s: Optional request timeout in seconds.
    """
    if warn := check_runtime("ssurgo", 0, 0.0, max_runtime_s):
        return _validate_grouped_geometry_response(warn)
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError(f"latitude and longitude must be finite; got {latitude!r}, {longitude!r}")
    try:
        point = PointInput(latitude=latitude, longitude=longitude)
    except ValidationError as exc:
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={"latitude": latitude, "longitude": longitude},
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )
    try:
        names = _resolve_rule_names(rule_names)
    except ValueError as exc:
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={"latitude": latitude, "longitude": longitude},
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )
    wkt = f"POINT({point.longitude} {point.latitude})"
    query_params: dict[str, Any] = {
        "latitude": point.latitude,
        "longitude": point.longitude,
        "rule_names": names,
        "max_runtime_s": max_runtime_s,
        "query_type": "soil_suitability",
    }
    t0 = time.perf_counter()
    try:
        sql = _build_soil_suitability_sql(wkt, names)
        records, latency = _fetch_sda(sql)
        grouped = _group_by_mukey(records)
        _buf = _GEOM_BBOX_BUFFER_DEG
        geo_bbox = (
            point.longitude - _buf,
            point.latitude - _buf,
            point.longitude + _buf,
            point.latitude + _buf,
        )
        geometries = _fetch_mukey_geometries(list(grouped.keys()), geo_bbox)
        data = [
            {
                "mukey": mk,
                "muname": info["muname"],
                "geometry": geometries.get(mk),
                "records": info["rows"],
            }
            for mk, info in grouped.items()
        ]
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="ssurgo",
                    query_params=query_params,
                    rows_returned=len(data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    error=_NO_COVERAGE_MSG if not data else None,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )


@mcp.tool()
def ssurgo_soil_suitability_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    rule_names: list[str] = DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil suitability data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        rule_names: Interpretation rule names to query.  Defaults to the same
            set as ``ssurgo_soil_suitability_query``.
        max_runtime_s: Optional request timeout in seconds.
    """
    try:
        bbox = BboxInput(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)
    except ValidationError as exc:
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params={
                        "min_lat": min_lat,
                        "max_lat": max_lat,
                        "min_lon": min_lon,
                        "max_lon": max_lon,
                    },
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )

    area_deg2 = (bbox.max_lat - bbox.min_lat) * (bbox.max_lon - bbox.min_lon)
    if warn := check_runtime("ssurgo", 0, area_deg2, max_runtime_s):
        return _validate_grouped_geometry_response(warn)
    base_params: dict[str, Any] = {
        "min_lat": bbox.min_lat,
        "max_lat": bbox.max_lat,
        "min_lon": bbox.min_lon,
        "max_lon": bbox.max_lon,
    }
    try:
        names = _resolve_rule_names(rule_names)
    except ValueError as exc:
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params=base_params,
                    rows_returned=0,
                    latency_s=0.0,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )
    wkt = bbox_to_wkt_polygon(bbox.model_dump())
    query_params: dict[str, Any] = {
        **base_params,
        "rule_names": names,
        "max_runtime_s": max_runtime_s,
        "query_type": "soil_suitability",
    }
    t0 = time.perf_counter()
    try:
        sql = _build_soil_suitability_sql(wkt, names)
        records, latency = _fetch_sda(sql)
        grouped = _group_by_mukey(records)
        geo_bbox = (bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat)
        geometries = _fetch_mukey_geometries(list(grouped.keys()), geo_bbox)
        data = [
            {
                "mukey": mk,
                "muname": info["muname"],
                "geometry": geometries.get(mk),
                "records": info["rows"],
            }
            for mk, info in grouped.items()
        ]
        return _validate_grouped_geometry_response(
            {
                "data": data,
                "_meta": build_meta(
                    source="ssurgo",
                    query_params=query_params,
                    rows_returned=len(data),
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    error=_NO_COVERAGE_MSG if not data else None,
                ),
            }
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return _validate_grouped_geometry_response(
            {
                "data": [],
                "_meta": build_meta(
                    source="ssurgo",
                    query_params=query_params,
                    rows_returned=0,
                    latency_s=latency,
                    license_info=LICENSE_INFO,
                    success=False,
                    error=str(exc),
                ),
            }
        )


# ---------------------------------------------------------------------------
# MCP tools — Type 6: ecological_site
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_ecological_site_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO ecological site queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``, and
    ``coecoclass``.
    """
    return _available_vars_response(_QueryType.ECOLOGICAL_SITE)


@mcp.tool()
def ssurgo_ecological_site_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO ecological site classification data for a point location.

    Returns ecological site IDs and names that link soil to its vegetation
    potential (rangeland and forest ecological sites).  Rows with no
    ecological site classification will have NULL values for ``ecoclassid``
    and related columns.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_ecological_site_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _build_ecological_site_sql,
        max_runtime_s,
        _QueryType.ECOLOGICAL_SITE,
    )


@mcp.tool()
def ssurgo_ecological_site_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO ecological site data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _build_ecological_site_sql,
        max_runtime_s,
        _QueryType.ECOLOGICAL_SITE,
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 7: parent_material
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_parent_material_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO parent material queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``,
    ``copmgrp``, and ``copm``.
    """
    return _available_vars_response(_QueryType.PARENT_MATERIAL)


@mcp.tool()
def ssurgo_parent_material_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_PARENT_MATERIAL_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO parent material data for a point location.

    Returns geological information about what the soil formed from (loess,
    alluvium, glacial till, volcanic ash, residuum, etc.) and its origin
    (igneous, sedimentary, metamorphic).  Rows with no parent material data
    will have NULL values for parent material columns.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_parent_material_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _build_parent_material_sql,
        max_runtime_s,
        _QueryType.PARENT_MATERIAL,
    )


@mcp.tool()
def ssurgo_parent_material_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_PARENT_MATERIAL_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO parent material data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _build_parent_material_sql,
        max_runtime_s,
        _QueryType.PARENT_MATERIAL,
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 8: soil_temperature
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_soil_temperature_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO soil temperature queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``,
    ``comonth``, and ``cosoiltemp``.
    """
    return _available_vars_response(_QueryType.SOIL_TEMPERATURE)


@mcp.tool()
def ssurgo_soil_temperature_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil temperature data for a point location.

    Returns mean monthly soil temperature by depth for the dominant soil
    component.  Each row represents one month at one depth increment, giving
    a full seasonal and depth profile of soil thermal conditions.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_soil_temperature_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _build_soil_temperature_sql,
        max_runtime_s,
        _QueryType.SOIL_TEMPERATURE,
    )


@mcp.tool()
def ssurgo_soil_temperature_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil temperature data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _build_soil_temperature_sql,
        max_runtime_s,
        _QueryType.SOIL_TEMPERATURE,
    )
