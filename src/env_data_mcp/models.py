"""
Pydantic input schemas shared across tool definitions.

These are used in server.py for type-validated tool parameters and can
also be used in tests and notebooks for constructing inputs programmatically.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


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
