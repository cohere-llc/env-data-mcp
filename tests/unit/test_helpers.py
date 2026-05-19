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
    bbox_area_deg2,
    bbox_centroid,
    bbox_to_wkt_polygon,
    build_meta,
    check_runtime,
    estimate_runtime,
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


# ----------------------------------------------------------------------------
# bbox_area_deg2
# ---------------------------------------------------------------------------


class TestBboxAreaDeg2:
    def test_unit_box(self) -> None:
        area = bbox_area_deg2({"min_lat": 0, "max_lat": 1, "min_lon": 0, "max_lon": 1})
        assert area == pytest.approx(1.0)

    def test_pnnl_bbox(self) -> None:
        bbox = {
            "min_lat": 46.251407,
            "max_lat": 46.251790,
            "min_lon": -119.728785,
            "max_lon": -119.728369,
        }
        area = bbox_area_deg2(bbox)
        expected_area = (46.251790 - 46.251407) * (-119.728369 - -119.728785)
        assert area == pytest.approx(expected_area)

    def test_crosses_antimeridian(self) -> None:
        area = bbox_area_deg2({"min_lat": 0, "max_lat": 1, "min_lon": 179, "max_lon": -179})
        # Should be a 2° wide box crossing the antimeridian → area ≈ 2 deg².
        assert area == pytest.approx(2.0)


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
# estimate_runtime
# ---------------------------------------------------------------------------


class TestEstimateRuntime:
    def test_known_source_returns_positive(self) -> None:
        t = estimate_runtime("gbif", n_days=7, area_deg2=1.0)
        assert t > 0.0

    def test_unknown_source_returns_zero(self) -> None:
        assert estimate_runtime("nonexistent_source_xyz", n_days=7, area_deg2=1.0) == 0.0

    def test_result_is_clamped_non_negative(self) -> None:
        # A source with large negative coefficients and 0 n_days/area should still be >= 0.
        t = estimate_runtime("emit", n_days=0, area_deg2=0.0)
        assert t >= 0.0

    def test_oco2_override_applied(self) -> None:
        # For a 100-day OCO-2 query, the override formula dominates.
        # override = 2.84 + ceil(100/10) * 3.0 = 2.84 + 30 = 32.84
        t = estimate_runtime("oco2", n_days=100, area_deg2=0.0)
        assert t >= 32.84

    def test_emit_override_applied(self) -> None:
        # For a 30-day EMIT query at a point, override = 0.2 + (30//3)*1.0*3.5 = 35.2
        t = estimate_runtime("emit", n_days=30, area_deg2=0.0)
        assert t >= 35.2

    def test_emit_override_area_aware(self) -> None:
        # Larger bbox → more granules per 3-day window → higher estimate.
        t_point = estimate_runtime("emit", n_days=30, area_deg2=0.0)
        t_bbox = estimate_runtime("emit", n_days=30, area_deg2=100.0)
        assert t_bbox > t_point

    def test_sentinel5p_override_applied(self) -> None:
        # 30-day point: n_granules=30*1.0=30; ceil(30/16)=2 batches → 2.0+2*4.5=11.0 s
        t = estimate_runtime("sentinel5p", n_days=30, area_deg2=0.0)
        assert t >= 11.0

    def test_openaq_override_applied(self) -> None:
        # 100-day: override = 1.5 + 0.15*100 = 16.5 s
        t = estimate_runtime("openaq", n_days=100, area_deg2=0.0)
        assert t >= 16.5

    def test_gbif_override_more_conservative_than_model(self) -> None:
        # 365-day 100 deg²: override = 2.0 + 365*0.13 + 100*0.18 = 67.45 s
        t = estimate_runtime("gbif", n_days=365, area_deg2=100.0)
        assert t >= 67.45

    def test_scales_with_n_days_for_gbif(self) -> None:
        # GBIF beta_n_days > 0 so longer windows → higher estimate.
        t_short = estimate_runtime("gbif", n_days=1, area_deg2=1.0)
        t_long = estimate_runtime("gbif", n_days=365, area_deg2=1.0)
        assert t_long > t_short

    def test_scales_with_area_for_gbif(self) -> None:
        # GBIF beta_area_deg2 > 0.
        t_small = estimate_runtime("gbif", n_days=7, area_deg2=0.0)
        t_large = estimate_runtime("gbif", n_days=7, area_deg2=100.0)
        assert t_large > t_small

    def test_all_9_sources_parseable(self) -> None:
        sources = [
            "emit",
            "essdive",
            "gbif",
            "nasa_power",
            "oco2",
            "openaq",
            "sentinel5p",
            "soilgrids",
            "ssurgo",
        ]
        for src in sources:
            t = estimate_runtime(src, n_days=7, area_deg2=1.0)
            assert isinstance(t, float), f"{src} should return a float"
            assert t >= 0.0, f"{src} should return a non-negative estimate"


# ---------------------------------------------------------------------------
# check_runtime
# ---------------------------------------------------------------------------
# Uses the "_test" sentinel source from timing_model.json:
#   alpha=2.0, beta_n_days=1.0, beta_area_deg2=0.5  (no runtime override)
#   t(n, a) = 2.0 + 1.0·n + 0.5·a
#
# Key boundary values (default threshold = 30.0 s):
#   t(1,  0) =  3.0  → passes
#   t(27, 0) = 29.0  → passes
#   t(28, 0) = 30.0  → blocks  (not strictly < 30)
#   t(0, 56) = 30.0  → blocks  (area term alone reaches threshold)


class TestCheckRuntime:
    def test_returns_none_when_under_default_threshold(self) -> None:
        # t(1, 0) = 3.0 < 30.0 → None
        assert check_runtime("_test", n_days=1, area_deg2=0.0) is None

    def test_just_under_threshold_passes(self) -> None:
        # t(27, 0) = 29.0 < 30.0 → None
        assert check_runtime("_test", n_days=27, area_deg2=0.0) is None

    def test_at_threshold_blocks(self) -> None:
        # t(28, 0) = 30.0, threshold = 30.0 → 30.0 < 30.0 is False → blocks
        assert check_runtime("_test", n_days=28, area_deg2=0.0) is not None

    def test_returns_warning_dict_structure(self) -> None:
        # t(28, 0) = 30.0 → warning; verify full schema
        result = check_runtime("_test", n_days=28, area_deg2=0.0)
        assert result is not None
        assert result["data"] == []
        meta = result["_meta"]
        assert meta["success"] is False
        assert meta["slow_query_warning"] is True
        assert "estimated_runtime_s" in meta
        assert "threshold_s" in meta
        assert "message" in meta

    def test_estimated_runtime_exact(self) -> None:
        # t(28, 0) = 2.0 + 28 + 0 = 30.0
        result = check_runtime("_test", n_days=28, area_deg2=0.0)
        assert result is not None
        assert result["_meta"]["estimated_runtime_s"] == pytest.approx(30.0)

    def test_area_term_contributes_to_estimate(self) -> None:
        # t(0, 20) = 2.0 + 0 + 10.0 = 12.0 < 30.0 → passes
        assert check_runtime("_test", n_days=0, area_deg2=20.0) is None
        # t(0, 56) = 2.0 + 0 + 28.0 = 30.0 → blocks
        result = check_runtime("_test", n_days=0, area_deg2=56.0)
        assert result is not None
        assert result["_meta"]["estimated_runtime_s"] == pytest.approx(30.0)

    def test_default_threshold_is_30s(self) -> None:
        result = check_runtime("_test", n_days=28, area_deg2=0.0)
        assert result is not None
        assert result["_meta"]["threshold_s"] == pytest.approx(30.0)

    def test_max_runtime_s_gate_allows_query(self) -> None:
        # threshold = 10.0 * 1.2 = 12.0;  t(5, 0) = 7.0 < 12.0 → None
        assert check_runtime("_test", n_days=5, area_deg2=0.0, max_runtime_s=10.0) is None

    def test_max_runtime_s_gate_blocks_query(self) -> None:
        # threshold = 10.0 * 1.2 = 12.0;  t(10, 0) = 12.0 → not < 12.0 → blocks
        result = check_runtime("_test", n_days=10, area_deg2=0.0, max_runtime_s=10.0)
        assert result is not None
        assert result["_meta"]["slow_query_warning"] is True

    def test_threshold_is_max_runtime_times_1p2(self) -> None:
        # threshold = 5.0 * 1.2 = 6.0;  t(28, 0) = 30.0 ≥ 6.0 → blocks
        result = check_runtime("_test", n_days=28, area_deg2=0.0, max_runtime_s=5.0)
        assert result is not None
        assert result["_meta"]["threshold_s"] == pytest.approx(6.0)

    def test_max_runtime_s_zero_blocks_any_nonzero_alpha(self) -> None:
        # threshold = 0.0 * 1.2 = 0.0;  t(0, 0) = 2.0 ≥ 0.0 → blocks
        result = check_runtime("_test", n_days=0, area_deg2=0.0, max_runtime_s=0.0)
        assert result is not None
        assert result["_meta"]["slow_query_warning"] is True

    def test_unknown_source_never_blocks(self) -> None:
        # estimate_runtime returns 0.0 for unknown sources → always passes.
        assert check_runtime("no_such_source", n_days=9999, area_deg2=9999.0) is None

    def test_latency_s_is_zero(self) -> None:
        result = check_runtime("_test", n_days=28, area_deg2=0.0)
        assert result is not None
        assert result["_meta"]["latency_s"] == 0.0

    def test_headroom_suggestion_exact(self) -> None:
        # t_est=30.0; headroom = int(30.0 * 1.25) + 1 = 37 + 1 = 38
        result = check_runtime("_test", n_days=28, area_deg2=0.0)
        assert result is not None
        assert "max_runtime_s=38" in result["_meta"]["message"]

    def test_scale_factor_blocks_otherwise_passing_query(self) -> None:
        # t(5, 0) = 7.0; 7.0 * 5.0 = 35.0 ≥ 30.0 → blocks
        result = check_runtime("_test", n_days=5, area_deg2=0.0, scale_factor=5.0)
        assert result is not None
        assert result["_meta"]["estimated_runtime_s"] == pytest.approx(35.0)

    def test_scale_factor_allows_otherwise_blocking_query(self) -> None:
        # t(28, 0) = 30.0; 30.0 * 0.9 = 27.0 < 30.0 → None
        assert check_runtime("_test", n_days=28, area_deg2=0.0, scale_factor=0.9) is None

