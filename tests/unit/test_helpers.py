"""
Unit tests for env_data_mcp.helpers.

All tests are offline — no network calls are made.
"""

from __future__ import annotations

import datetime
import warnings

import pytest

from env_data_mcp.helpers import (
    auth_missing_response,
    bbox_centroid,
    bbox_to_wkt_polygon,
    build_meta,
    clamp_bbox,
    parse_date,
)

# Minimal license_info dict used as a stand-in across tests.
_LICENSE = {
    "license": "Test License CC BY 4.0",
    "license_url": "https://example.com/license",
}

# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_valid_iso_date(self) -> None:
        assert parse_date("2019-08-15") == datetime.date(2019, 8, 15)

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert parse_date("  2019-08-15  ") == datetime.date(2019, 8, 15)

    def test_raises_on_slash_format(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_date("08/15/2019")

    def test_raises_on_european_format(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_date("15/08/2019")

    def test_raises_on_missing_leading_zeros(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_date("2019-8-5")

    def test_raises_on_datetime_string(self) -> None:
        # We accept dates only, not datetimes.
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            parse_date("2019-08-15T00:00:00")

    def test_raises_on_empty_string(self) -> None:
        with pytest.raises(ValueError):
            parse_date("")

    def test_raises_on_invalid_day(self) -> None:
        # fromisoformat will catch the out-of-range day after the regex passes.
        with pytest.raises(ValueError):
            parse_date("2019-02-30")

    def test_earliest_reasonable_date(self) -> None:
        assert parse_date("1981-01-01") == datetime.date(1981, 1, 1)


# ---------------------------------------------------------------------------
# bbox_centroid
# ---------------------------------------------------------------------------


class TestBboxCentroid:
    def test_symmetric_unit_box(self) -> None:
        lat, lon = bbox_centroid({"min_lat": 0, "max_lat": 2, "min_lon": 0, "max_lon": 2})
        assert lat == pytest.approx(1.0)
        assert lon == pytest.approx(1.0)

    def test_pnnl_bbox(self) -> None:
        bbox = {
            "min_lat": 46.251407,
            "max_lat": 46.251790,
            "min_lon": -119.728785,
            "max_lon": -119.728369,
        }
        lat, lon = bbox_centroid(bbox)
        assert lat == pytest.approx((46.251407 + 46.251790) / 2)
        assert lon == pytest.approx((-119.728785 + -119.728369) / 2)

    def test_negative_coordinates(self) -> None:
        lat, lon = bbox_centroid(
            {"min_lat": -10.0, "max_lat": -5.0, "min_lon": -20.0, "max_lon": -15.0}
        )
        assert lat == pytest.approx(-7.5)
        assert lon == pytest.approx(-17.5)

    def test_crosses_antimeridian_arithmetic(self) -> None:
        # Simple arithmetic centroid — no antimeridian wrapping needed for our sources.
        lat, lon = bbox_centroid({"min_lat": 0, "max_lat": 1, "min_lon": -1, "max_lon": 1})
        assert lon == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# bbox_to_wkt_polygon
# ---------------------------------------------------------------------------


class TestBboxToWktPolygon:
    def test_starts_with_polygon(self) -> None:
        wkt = bbox_to_wkt_polygon({"min_lat": 1, "max_lat": 2, "min_lon": 3, "max_lon": 4})
        assert wkt.startswith("POLYGON")

    def test_lon_lat_order(self) -> None:
        # WKT uses (longitude latitude) order.
        wkt = bbox_to_wkt_polygon({"min_lat": 1, "max_lat": 2, "min_lon": 3, "max_lon": 4})
        assert "3 1" in wkt  # min_lon min_lat
        assert "4 2" in wkt  # max_lon max_lat

    def test_ring_is_closed(self) -> None:
        wkt = bbox_to_wkt_polygon({"min_lat": 0, "max_lat": 1, "min_lon": 0, "max_lon": 1})
        # Strip "POLYGON ((" ... "))"
        inner = wkt[wkt.index("((") + 2 : wkt.rindex("))")]
        coords = [c.strip() for c in inner.split(",")]
        assert coords[0] == coords[-1], "WKT ring must be explicitly closed"

    def test_five_vertices(self) -> None:
        wkt = bbox_to_wkt_polygon({"min_lat": 0, "max_lat": 1, "min_lon": 0, "max_lon": 1})
        inner = wkt[wkt.index("((") + 2 : wkt.rindex("))")]
        coords = [c.strip() for c in inner.split(",")]
        assert len(coords) == 5  # 4 corners + closing repeat


# ---------------------------------------------------------------------------
# build_meta
# ---------------------------------------------------------------------------


class TestBuildMeta:
    def test_success_fields_present(self) -> None:
        meta = build_meta(
            source="test_source",
            query_params={"latitude": 1.0, "longitude": 2.0},
            rows_returned=5,
            latency_s=1.23456,
            license_info=_LICENSE,
        )
        assert meta["source"] == "test_source"
        assert meta["rows_returned"] == 5
        assert meta["success"] is True
        assert meta["error"] is None
        assert meta["auth_required"] is False
        assert meta["auth_present"] is True

    def test_license_propagated(self) -> None:
        meta = build_meta("s", {}, 0, 0.0, _LICENSE)
        assert meta["license"] == _LICENSE["license"]
        assert meta["license_url"] == _LICENSE["license_url"]

    def test_query_params_echoed(self) -> None:
        params = {"latitude": 46.253, "longitude": -119.477, "start_date": "2019-08-19"}
        meta = build_meta("s", params, 1, 0.5, _LICENSE)
        assert meta["query_params"] == params

    def test_latency_rounded_to_three_places(self) -> None:
        meta = build_meta("s", {}, 0, 1.23456789, _LICENSE)
        assert meta["latency_s"] == pytest.approx(1.235, abs=0.0005)

    def test_failure_case(self) -> None:
        meta = build_meta("s", {}, 0, 0.0, _LICENSE, success=False, error="Something went wrong")
        assert meta["success"] is False
        assert meta["error"] == "Something went wrong"

    def test_auth_fields(self) -> None:
        meta = build_meta(
            "s",
            {},
            0,
            0.0,
            _LICENSE,
            auth_required=True,
            auth_present=False,
            success=False,
        )
        assert meta["auth_required"] is True
        assert meta["auth_present"] is False

    def test_variables_included(self) -> None:
        meta = build_meta("s", {}, 3, 0.5, _LICENSE, variables=["T2M", "RH2M"])
        assert meta["variables"] == ["T2M", "RH2M"]

    def test_variables_defaults_to_empty_list(self) -> None:
        meta = build_meta("s", {}, 3, 0.5, _LICENSE)
        assert meta["variables"] == []

    def test_empty_license_info(self) -> None:
        meta = build_meta("s", {}, 0, 0.0, {})
        assert meta["license"] == ""
        assert meta["license_url"] == ""

    def test_all_expected_keys_present(self) -> None:
        meta = build_meta("s", {}, 0, 0.0, _LICENSE)
        required_keys = {
            "source",
            "variables",
            "rows_returned",
            "latency_s",
            "auth_required",
            "auth_present",
            "success",
            "error",
            "license",
            "license_url",
            "query_params",
        }
        assert required_keys.issubset(meta.keys())


# ---------------------------------------------------------------------------
# auth_missing_response
# ---------------------------------------------------------------------------


class TestAuthMissingResponse:
    def test_data_is_empty_list(self) -> None:
        resp = auth_missing_response("oco2", _LICENSE, "Creds required.", {})
        assert resp["data"] == []

    def test_meta_marks_auth_absent(self) -> None:
        resp = auth_missing_response("oco2", _LICENSE, "Creds required.", {})
        meta = resp["_meta"]
        assert meta["success"] is False
        assert meta["auth_required"] is True
        assert meta["auth_present"] is False
        assert meta["rows_returned"] == 0

    def test_error_message_propagated(self) -> None:
        msg = "EARTHDATA_USERNAME and EARTHDATA_PASSWORD required."
        resp = auth_missing_response("oco2", _LICENSE, msg, {})
        assert resp["_meta"]["error"] == msg

    def test_source_propagated(self) -> None:
        resp = auth_missing_response("essdive", _LICENSE, "msg", {})
        assert resp["_meta"]["source"] == "essdive"

    def test_query_params_echoed(self) -> None:
        params = {"latitude": 42.0, "longitude": -71.0}
        resp = auth_missing_response("s", _LICENSE, "msg", params)
        assert resp["_meta"]["query_params"] == params

    def test_license_propagated(self) -> None:
        resp = auth_missing_response("s", _LICENSE, "msg", {})
        assert resp["_meta"]["license"] == _LICENSE["license"]


# ---------------------------------------------------------------------------
# clamp_bbox
# ---------------------------------------------------------------------------


class TestClampBbox:
    def test_no_op_within_bounds(self) -> None:
        bbox = {"min_lat": 0.0, "max_lat": 1.0, "min_lon": 0.0, "max_lon": 1.0}
        result = clamp_bbox(bbox, max_degrees=10.0)
        assert result == bbox

    def test_no_op_exactly_at_limit(self) -> None:
        bbox = {"min_lat": 0.0, "max_lat": 10.0, "min_lon": 0.0, "max_lon": 10.0}
        result = clamp_bbox(bbox, max_degrees=10.0)
        assert result == bbox

    def test_clamps_oversized_lat_and_warns(self) -> None:
        bbox = {"min_lat": 0.0, "max_lat": 20.0, "min_lon": 0.0, "max_lon": 1.0}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = clamp_bbox(bbox, max_degrees=10.0)
        assert len(caught) == 1
        assert issubclass(caught[0].category, UserWarning)
        lat_span = result["max_lat"] - result["min_lat"]
        assert lat_span == pytest.approx(10.0)

    def test_clamps_oversized_lon_and_warns(self) -> None:
        bbox = {"min_lat": 0.0, "max_lat": 1.0, "min_lon": 0.0, "max_lon": 25.0}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = clamp_bbox(bbox, max_degrees=10.0)
        assert len(caught) == 1
        lon_span = result["max_lon"] - result["min_lon"]
        assert lon_span == pytest.approx(10.0)

    def test_clamps_only_oversized_dimension(self) -> None:
        # lat is fine (1°), lon is oversized (25°)
        bbox = {"min_lat": 0.0, "max_lat": 1.0, "min_lon": 0.0, "max_lon": 25.0}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = clamp_bbox(bbox, max_degrees=10.0)
        # Lat dimension should be unchanged.
        assert result["min_lat"] == 0.0
        assert result["max_lat"] == 1.0

    def test_centred_on_original_centroid(self) -> None:
        # Centroid of [0, 20] is 10.0; after clamping to 10° → [5, 15].
        bbox = {"min_lat": 0.0, "max_lat": 20.0, "min_lon": 0.0, "max_lon": 1.0}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = clamp_bbox(bbox, max_degrees=10.0)
        assert result["min_lat"] == pytest.approx(5.0)
        assert result["max_lat"] == pytest.approx(15.0)

    def test_pnnl_bbox_not_clamped(self) -> None:
        bbox = {
            "min_lat": 46.251407,
            "max_lat": 46.251790,
            "min_lon": -119.728785,
            "max_lon": -119.728369,
        }
        result = clamp_bbox(bbox)
        assert result == bbox

    def test_clamp_near_north_pole_stays_within_valid_range(self) -> None:
        # Centroid = 90, naive clamp to 10° would give max_lat = 95.
        # Fix must shift window down to [80, 90] and preserve span.
        bbox = {"min_lat": 82.0, "max_lat": 98.0, "min_lon": 0.0, "max_lon": 1.0}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = clamp_bbox(bbox, max_degrees=10.0)
        assert result["max_lat"] == pytest.approx(90.0)
        assert result["min_lat"] == pytest.approx(80.0)
        assert result["max_lat"] - result["min_lat"] == pytest.approx(10.0)

    def test_clamp_near_south_pole_stays_within_valid_range(self) -> None:
        # Centroid = -90, naive clamp to 10° would give min_lat = -95.
        # Fix must shift window up to [-90, -80] and preserve span.
        bbox = {"min_lat": -98.0, "max_lat": -82.0, "min_lon": 0.0, "max_lon": 1.0}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = clamp_bbox(bbox, max_degrees=10.0)
        assert result["min_lat"] == pytest.approx(-90.0)
        assert result["max_lat"] == pytest.approx(-80.0)
        assert result["max_lat"] - result["min_lat"] == pytest.approx(10.0)

    def test_clamp_near_antimeridian_stays_within_valid_range(self) -> None:
        # Centroid lon = 178, naive clamp to 10° would give max_lon = 183.
        # Fix must shift window left to [170, 180] and preserve span.
        bbox = {"min_lat": 0.0, "max_lat": 1.0, "min_lon": 160.0, "max_lon": 196.0}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = clamp_bbox(bbox, max_degrees=10.0)
        assert result["max_lon"] == pytest.approx(180.0)
        assert result["min_lon"] == pytest.approx(170.0)
        assert result["max_lon"] - result["min_lon"] == pytest.approx(10.0)

    def test_clamp_near_western_antimeridian_stays_within_valid_range(self) -> None:
        # Centroid lon = -178, naive clamp to 10° would give min_lon = -183.
        # Fix must shift window right to [-180, -170] and preserve span.
        bbox = {"min_lat": 0.0, "max_lat": 1.0, "min_lon": -196.0, "max_lon": -160.0}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = clamp_bbox(bbox, max_degrees=10.0)
        assert result["min_lon"] == pytest.approx(-180.0)
        assert result["max_lon"] == pytest.approx(-170.0)
        assert result["max_lon"] - result["min_lon"] == pytest.approx(10.0)
