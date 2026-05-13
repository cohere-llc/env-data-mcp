"""
Unit tests for env_data_mcp.models.

All tests are offline — no network calls are made.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from env_data_mcp.models import BboxInput, DateRange, PointInput

# ---------------------------------------------------------------------------
# PointInput
# ---------------------------------------------------------------------------


class TestPointInput:
    def test_valid_point(self) -> None:
        p = PointInput(latitude=46.253, longitude=-119.477)
        assert p.latitude == pytest.approx(46.253)
        assert p.longitude == pytest.approx(-119.477)

    def test_rejects_latitude_above_90(self) -> None:
        with pytest.raises(ValidationError):
            PointInput(latitude=91.0, longitude=0.0)

    def test_rejects_latitude_below_minus_90(self) -> None:
        with pytest.raises(ValidationError):
            PointInput(latitude=-91.0, longitude=0.0)

    def test_rejects_longitude_above_180(self) -> None:
        with pytest.raises(ValidationError):
            PointInput(latitude=0.0, longitude=181.0)

    def test_rejects_longitude_below_minus_180(self) -> None:
        with pytest.raises(ValidationError):
            PointInput(latitude=0.0, longitude=-181.0)

    def test_south_pole(self) -> None:
        p = PointInput(latitude=-90.0, longitude=0.0)
        assert p.latitude == -90.0

    def test_north_pole(self) -> None:
        p = PointInput(latitude=90.0, longitude=0.0)
        assert p.latitude == 90.0

    def test_antimeridian_longitude(self) -> None:
        p = PointInput(latitude=0.0, longitude=180.0)
        assert p.longitude == 180.0

    def test_negative_antimeridian_longitude(self) -> None:
        p = PointInput(latitude=0.0, longitude=-180.0)
        assert p.longitude == -180.0


# ---------------------------------------------------------------------------
# BboxInput
# ---------------------------------------------------------------------------


class TestBboxInput:
    def test_valid_bbox(self) -> None:
        b = BboxInput(min_lat=46.0, max_lat=47.0, min_lon=-120.0, max_lon=-119.0)
        assert b.min_lat == 46.0
        assert b.max_lat == 47.0
        assert b.min_lon == -120.0
        assert b.max_lon == -119.0

    def test_rejects_inverted_lat(self) -> None:
        with pytest.raises(ValidationError, match="min_lat"):
            BboxInput(min_lat=47.0, max_lat=46.0, min_lon=-120.0, max_lon=-119.0)

    def test_rejects_inverted_lon(self) -> None:
        with pytest.raises(ValidationError, match="min_lon"):
            BboxInput(min_lat=46.0, max_lat=47.0, min_lon=-119.0, max_lon=-120.0)

    def test_point_bbox_valid(self) -> None:
        # min == max is degenerate but valid (a single point as a bbox).
        b = BboxInput(min_lat=46.0, max_lat=46.0, min_lon=-119.0, max_lon=-119.0)
        assert b.min_lat == b.max_lat
        assert b.min_lon == b.max_lon

    def test_pnnl_bbox(self) -> None:
        b = BboxInput(
            min_lat=46.251407,
            max_lat=46.251790,
            min_lon=-119.728785,
            max_lon=-119.728369,
        )
        assert b.min_lat < b.max_lat
        assert b.min_lon < b.max_lon

    def test_rejects_lat_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            BboxInput(min_lat=-91.0, max_lat=0.0, min_lon=0.0, max_lon=1.0)

    def test_rejects_lon_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            BboxInput(min_lat=0.0, max_lat=1.0, min_lon=-181.0, max_lon=0.0)


# ---------------------------------------------------------------------------
# DateRange
# ---------------------------------------------------------------------------


class TestDateRange:
    def test_valid_range(self) -> None:
        d = DateRange(start_date="2023-05-01", end_date="2023-06-01")
        assert d.start_date == "2023-05-01"
        assert d.end_date == "2023-06-01"

    def test_same_date_valid(self) -> None:
        # Single-day window is valid.
        d = DateRange(start_date="2019-08-19", end_date="2019-08-19")
        assert d.start_date == d.end_date

    def test_rejects_reversed_range(self) -> None:
        with pytest.raises(ValidationError, match="start_date"):
            DateRange(start_date="2023-06-01", end_date="2023-05-01")

    def test_rejects_invalid_start_date_format(self) -> None:
        with pytest.raises(ValidationError):
            DateRange(start_date="05/01/2023", end_date="2023-06-01")

    def test_rejects_invalid_end_date_format(self) -> None:
        with pytest.raises(ValidationError):
            DateRange(start_date="2023-05-01", end_date="June 1 2023")

    def test_rejects_datetime_in_start(self) -> None:
        with pytest.raises(ValidationError):
            DateRange(start_date="2023-05-01T00:00:00", end_date="2023-06-01")
