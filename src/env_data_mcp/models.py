"""
Pydantic input and output schemas shared across tool definitions.

Input schemas are used in source modules primarily for validation.
Output schemas define the canonical response contract for every tool response
and can be used in tests and notebooks to validate the full response structure
with a single ``Model.model_validate(result)`` call.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PointInput(BaseModel):
    """A single geographic point."""

    latitude: float = Field(..., ge=-90.0, le=90.0, description="Decimal degrees, WGS84")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Decimal degrees, WGS84")


class BboxInput(BaseModel):
    """An axis-aligned geographic bounding box."""

    min_lat: float = Field(..., ge=-90.0, le=90.0)
    max_lat: float = Field(..., ge=-90.0, le=90.0)
    min_lon: float = Field(..., ge=-180.0, le=180.0)
    max_lon: float = Field(..., ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def check_bounds_order(self) -> BboxInput:
        if self.min_lat > self.max_lat:
            raise ValueError(f"min_lat ({self.min_lat}) must be ≤ max_lat ({self.max_lat})")
        if self.min_lon > self.max_lon:
            raise ValueError(f"min_lon ({self.min_lon}) must be ≤ max_lon ({self.max_lon})")
        return self


class DateRange(BaseModel):
    """An inclusive date range, both ends in ISO 8601 YYYY-MM-DD format."""

    start_date: str = Field(..., description="ISO 8601 date, e.g. '2019-08-15'")
    end_date: str = Field(..., description="ISO 8601 date, e.g. '2019-08-19'")

    @model_validator(mode="after")
    def check_date_order(self) -> DateRange:
        from env_data_mcp.helpers import parse_date

        start = parse_date(self.start_date)
        end = parse_date(self.end_date)
        if start > end:
            raise ValueError(f"start_date ({self.start_date}) must be ≤ end_date ({self.end_date})")
        return self


# ---------------------------------------------------------------------------
# Output response schemas
# ---------------------------------------------------------------------------


class ResponseMeta(BaseModel):
    """Validates the ``_meta`` block returned by every tool via ``build_meta()``.

    ``extra="allow"`` tolerates source-specific extras such as
    ``slow_query_warning`` without requiring schema changes.
    """

    model_config = ConfigDict(extra="allow")

    source: str
    success: bool
    geometries_returned: int
    total_records_returned: int
    latency_s: float
    auth_required: bool
    auth_present: bool
    error: str | None
    license: str
    license_url: str
    citation: str
    query_params: dict[str, Any]
    # Fields always emitted by build_meta() but given defaults for forward-compat
    variables: list[str] = Field(default_factory=list)
    variable_info: dict[str, Any] = Field(default_factory=dict)
    unavailable_variables: list[str] = Field(default_factory=list)
    citation_urls: list[str] | str = Field(default_factory=list)
    description: str = ""
    description_url: str = ""
    acknowledgements: str = ""


class GeoJsonGeometry(BaseModel):
    """Validates a GeoJSON geometry object (RFC 7946)."""

    model_config = ConfigDict(extra="allow")

    type: Literal[
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    ]
    coordinates: list[Any]


class GeometryGroup(BaseModel):
    """One spatially grouped entity returned by a grouped query tool.

    ``extra="allow"`` absorbs source-specific identifier fields such as
    ``mukey``/``muname`` (SSURGO), ``station_id`` (OpenAQ), etc.
    """

    model_config = ConfigDict(extra="allow")

    geometry: GeoJsonGeometry | None
    records: list[dict[str, Any]]


class GroupedGeometryResponse(BaseModel):
    """Response schema for tools that group results by a spatial entity.

    Used by SSURGO point/bbox queries and future sources that adopt the same
    ``{data: [GeometryGroup, …], _meta: …}`` pattern.
    """

    model_config = ConfigDict(populate_by_name=True)

    data: list[GeometryGroup]
    meta: ResponseMeta = Field(alias="_meta")


class ToolResponse(BaseModel):
    """Response schema for tools that return a flat list with no geometry.

    Used by SoilGrids, ESS-DIVE, and NASA POWER point queries.
    """

    model_config = ConfigDict(populate_by_name=True)

    data: list[dict[str, Any]]
    meta: ResponseMeta = Field(alias="_meta")


class VariableInfo(BaseModel):
    """Metadata for a single variable returned by an ``available_variables`` tool.

    ``extra="allow"`` allows future additions (e.g. ``valid_range``) without
    breaking existing validated responses.
    """

    model_config = ConfigDict(extra="allow")

    description: str
    units: str


class AvailableVariablesResponse(BaseModel):
    """Response schema for ``available_variables`` tools that return a column catalogue.

    The ``data`` value is a dict mapping column name → ``VariableInfo``.  This
    covers all SSURGO query types except ``soil_suitability`` (which uses
    ``SuitabilityRulesResponse`` instead).
    """

    model_config = ConfigDict(populate_by_name=True)

    data: dict[str, VariableInfo]
    meta: ResponseMeta = Field(alias="_meta")


class SuitabilityRulesResponse(BaseModel):
    """Response schema for ``ssurgo_soil_suitability_available_rule_names()``."""

    model_config = ConfigDict(populate_by_name=True)

    data: list[str]
    meta: ResponseMeta = Field(alias="_meta")
