"""Unit tests for env_data_mcp.sources.nasa_power._query."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from env_data_mcp.sources.nasa_power._constants import DatasetType, TemporalResolution
from env_data_mcp.sources.nasa_power._query import (
    _CLIM_EPOCH,
    _clim_date_label,
    _clim_time_mask,
    estimate_query_runtime_s,
    query_bbox,
    query_point,
)

from .conftest import (
    _BBOX_MAX_LAT,
    _BBOX_MAX_LON,
    _BBOX_MIN_LAT,
    _BBOX_MIN_LON,
    _CLIM_TIME_VALS,
    _HOURLY_DATE,
    _LAT,
    _LON,
    _MOCK_CLIM_STORE,
    _MOCK_HOURLY_H_STORE,
    _MOCK_MERRA2_STORE,
    _MOCK_SYN1DEG_STORE,
)

# Patch path for open_store as used inside _query.py
_PATCHopen_store = "env_data_mcp.sources.nasa_power._query.open_store"

# Climatology decoded timestamps (for _clim_time_mask tests)
_CLIM_TIMES = _CLIM_EPOCH + pd.to_timedelta(np.array(_CLIM_TIME_VALS, dtype="f4"), unit="D")

# ---------------------------------------------------------------------------
# query_point — basic tests
# ---------------------------------------------------------------------------


def testquery_point_returns_correct_date():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        groups, _ = query_point(
            _LAT,
            _LON,
            "2019-08-19",
            "2019-08-19",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert len(groups) == 1
    assert len(groups[0]["records"]) == 1
    assert groups[0]["records"][0]["date"] == "2019-08-19"


def testquery_point_multi_day_range():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        groups, _ = query_point(
            _LAT,
            _LON,
            "2019-08-17",
            "2019-08-21",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert len(groups[0]["records"]) == 5


def testquery_point_variable_values():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        groups, _ = query_point(
            _LAT,
            _LON,
            "2019-08-19",
            "2019-08-19",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert pytest.approx(groups[0]["records"][0]["T2M"], abs=0.01) == 20.0


def testquery_point_units_present():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        groups, _ = query_point(
            _LAT,
            _LON,
            "2019-08-19",
            "2019-08-19",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert "T2M_units" in groups[0]["records"][0]


def testquery_point_unavailable_variable():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        groups, unavailable = query_point(
            _LAT,
            _LON,
            "2019-08-19",
            "2019-08-19",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M", "NONEXISTENT"],
        )
    assert "NONEXISTENT" in unavailable
    assert "NONEXISTENT" not in groups[0]["records"][0]


def testquery_point_out_of_range_returns_empty():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        groups, _ = query_point(
            _LAT,
            _LON,
            "2000-01-01",
            "2000-01-31",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert groups == []


def testquery_point_syn1deg_variable():
    with patch(_PATCHopen_store, return_value=_MOCK_SYN1DEG_STORE):
        groups, _ = query_point(
            _LAT,
            _LON,
            "2019-08-19",
            "2019-08-19",
            DatasetType.SYN1DEG,
            TemporalResolution.DAILY,
            ["ALLSKY_SFC_SW_DWN"],
        )
    assert pytest.approx(groups[0]["records"][0]["ALLSKY_SFC_SW_DWN"], abs=0.01) == 210.0


def testquery_point_has_geometry():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        groups, _ = query_point(
            _LAT,
            _LON,
            "2019-08-19",
            "2019-08-19",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert "geometry" in groups[0]
    assert groups[0]["geometry"]["type"] == "Point"
    assert len(groups[0]["geometry"]["coordinates"]) == 2


def testquery_point_snaps_to_grid_cell():
    """latitude/longitude in the group reflect the snapped grid cell, not the input."""
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        groups, _ = query_point(
            _LAT,
            _LON,
            "2019-08-19",
            "2019-08-19",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert pytest.approx(groups[0]["latitude"], abs=0.01) == 46.25
    assert pytest.approx(groups[0]["longitude"], abs=0.01) == -119.25


# ---------------------------------------------------------------------------
# query_bbox — basic tests
# ---------------------------------------------------------------------------


def testquery_bbox_returns_nine_points():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        results, _ = query_bbox(
            _BBOX_MIN_LAT,
            _BBOX_MAX_LAT,
            _BBOX_MIN_LON,
            _BBOX_MAX_LON,
            "2019-08-19",
            "2019-08-19",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert len(results) == 9


def testquery_bbox_grid_point_structure():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        results, _ = query_bbox(
            _BBOX_MIN_LAT,
            _BBOX_MAX_LAT,
            _BBOX_MIN_LON,
            _BBOX_MAX_LON,
            "2019-08-17",
            "2019-08-17",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    pt = results[0]
    assert "geometry" in pt
    assert pt["geometry"]["type"] == "Point"
    assert "latitude" in pt
    assert "longitude" in pt
    assert "in_bbox" in pt
    assert "records" in pt


def testquery_bbox_in_bbox_flag():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        results, _ = query_bbox(
            _BBOX_MIN_LAT,
            _BBOX_MAX_LAT,
            _BBOX_MIN_LON,
            _BBOX_MAX_LON,
            "2019-08-17",
            "2019-08-17",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    interior = [r for r in results if r["in_bbox"]]
    assert len(interior) == 1
    assert pytest.approx(interior[0]["latitude"], abs=0.01) == 46.25
    assert pytest.approx(interior[0]["longitude"], abs=0.01) == -119.25


def testquery_bbox_records_per_point():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        results, _ = query_bbox(
            _BBOX_MIN_LAT,
            _BBOX_MAX_LAT,
            _BBOX_MIN_LON,
            _BBOX_MAX_LON,
            "2019-08-17",
            "2019-08-21",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    for pt in results:
        assert len(pt["records"]) == 5


def testquery_bbox_record_fields():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        results, _ = query_bbox(
            _BBOX_MIN_LAT,
            _BBOX_MAX_LAT,
            _BBOX_MIN_LON,
            _BBOX_MAX_LON,
            "2019-08-17",
            "2019-08-17",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    rec = results[0]["records"][0]
    assert "date" in rec
    assert "T2M" in rec
    assert "T2M_units" in rec


def testquery_bbox_unavailable_variable():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        _, unavailable = query_bbox(
            _BBOX_MIN_LAT,
            _BBOX_MAX_LAT,
            _BBOX_MIN_LON,
            _BBOX_MAX_LON,
            "2019-08-17",
            "2019-08-17",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["NONEXISTENT"],
        )
    assert "NONEXISTENT" in unavailable


def testquery_bbox_out_of_range_returns_empty():
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        results, _ = query_bbox(
            _BBOX_MIN_LAT,
            _BBOX_MAX_LAT,
            _BBOX_MIN_LON,
            _BBOX_MAX_LON,
            "2000-01-01",
            "2000-01-31",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert results == []


def testquery_bbox_all_interior_when_bbox_covers_grid():
    """When the bbox covers all grid cells every point should have in_bbox=True."""
    with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
        results, _ = query_bbox(
            45.0,
            47.0,
            -120.0,
            -118.0,
            "2019-08-17",
            "2019-08-17",
            DatasetType.MERRA2,
            TemporalResolution.DAILY,
            ["T2M"],
        )
    assert all(r["in_bbox"] for r in results)


# ---------------------------------------------------------------------------
# Hourly query_point
# ---------------------------------------------------------------------------


class TestHourlyQueryPoint:
    """query_point must return 24 records for a single-day hourly query."""

    def test_single_day_returns_24_records(self):
        with patch(_PATCHopen_store, return_value=_MOCK_HOURLY_H_STORE):
            groups, _ = query_point(
                46.25,
                -119.25,
                _HOURLY_DATE,
                _HOURLY_DATE,
                DatasetType.MERRA2,
                TemporalResolution.HOURLY,
                ["T2M"],
            )
        assert len(groups) == 1
        assert len(groups[0]["records"]) == 24

    def test_single_day_dates_are_distinct(self):
        with patch(_PATCHopen_store, return_value=_MOCK_HOURLY_H_STORE):
            groups, _ = query_point(
                46.25,
                -119.25,
                _HOURLY_DATE,
                _HOURLY_DATE,
                DatasetType.MERRA2,
                TemporalResolution.HOURLY,
                ["T2M"],
            )
        dates = [r["date"] for r in groups[0]["records"]]
        assert len(set(dates)) == 24, "Hourly dates must include time component"

    def test_date_format_is_iso_datetime(self):
        with patch(_PATCHopen_store, return_value=_MOCK_HOURLY_H_STORE):
            groups, _ = query_point(
                46.25,
                -119.25,
                _HOURLY_DATE,
                _HOURLY_DATE,
                DatasetType.MERRA2,
                TemporalResolution.HOURLY,
                ["T2M"],
            )
        records = groups[0]["records"]
        assert records[0]["date"] == "2019-08-19T00:00:00"
        assert records[23]["date"] == "2019-08-19T23:00:00"

    def test_daily_date_format_unchanged(self):
        """Non-HOURLY resolutions still use %Y-%m-%d format."""
        with patch(_PATCHopen_store, return_value=_MOCK_MERRA2_STORE):
            groups, _ = query_point(
                _LAT,
                _LON,
                "2019-08-19",
                "2019-08-19",
                DatasetType.MERRA2,
                TemporalResolution.DAILY,
                ["T2M"],
            )
        assert groups[0]["records"][0]["date"] == "2019-08-19"


# ---------------------------------------------------------------------------
# Hourly query_bbox
# ---------------------------------------------------------------------------


class TestHourlyQueryBbox:
    """query_bbox must return 24 records per grid point for a single-day hourly query."""

    def test_single_day_returns_24_records_per_point(self):
        with patch(_PATCHopen_store, return_value=_MOCK_HOURLY_H_STORE):
            results, _ = query_bbox(
                46.0,
                46.5,
                -119.5,
                -119.0,
                _HOURLY_DATE,
                _HOURLY_DATE,
                DatasetType.MERRA2,
                TemporalResolution.HOURLY,
                ["T2M"],
            )
        assert len(results) == 1  # 1×1 grid
        assert len(results[0]["records"]) == 24

    def test_bbox_record_date_format_is_iso_datetime(self):
        with patch(_PATCHopen_store, return_value=_MOCK_HOURLY_H_STORE):
            results, _ = query_bbox(
                46.0,
                46.5,
                -119.5,
                -119.0,
                _HOURLY_DATE,
                _HOURLY_DATE,
                DatasetType.MERRA2,
                TemporalResolution.HOURLY,
                ["T2M"],
            )
        recs = results[0]["records"]
        assert recs[0]["date"] == "2019-08-19T00:00:00"
        assert recs[23]["date"] == "2019-08-19T23:00:00"


# ---------------------------------------------------------------------------
# Climatology helpers — pure unit tests (no I/O)
# ---------------------------------------------------------------------------


class TestClimDateLabel:
    """_clim_date_label returns human-readable labels for climatology slots."""

    def test_january(self):
        t = pd.Timestamp("1970-01-02")  # day=2 → slot 1 = January
        assert _clim_date_label(t) == "month-01"  # type: ignore[arg-type]

    def test_december(self):
        t = pd.Timestamp("1970-01-13")  # day=13 → slot 12 = December
        assert _clim_date_label(t) == "month-12"  # type: ignore[arg-type]

    def test_annual(self):
        t = pd.Timestamp("1970-01-14")  # day=14 → slot 13 = annual
        assert _clim_date_label(t) == "annual"  # type: ignore[arg-type]

    def test_all_monthly_slots(self):
        for slot in range(1, 13):
            t = pd.Timestamp("1970-01-01") + pd.Timedelta(days=slot)
            assert _clim_date_label(t) == f"month-{slot:02d}"  # type: ignore[arg-type]


class TestClimTimeMask:
    """_clim_time_mask filters climatology time steps by month range."""

    def test_full_year_includes_all_13(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2019-01-01", "2019-12-31")
        assert mask.sum() == 13

    def test_single_month_returns_month_plus_annual(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2019-08-01", "2019-08-31")
        assert mask.sum() == 2
        assert mask[7]  # slot 8 = August
        assert mask[12]  # slot 13 = annual

    def test_summer_range_returns_3_months_plus_annual(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2019-06-01", "2019-08-31")
        assert mask.sum() == 4
        assert mask[5]  # slot 6 = June
        assert mask[6]  # slot 7 = July
        assert mask[7]  # slot 8 = August
        assert mask[12]  # slot 13 = annual

    def test_annual_slot_always_included(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2019-03-15", "2019-03-15")
        assert mask[12]

    def test_partial_month_coverage_includes_boundary_months(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2019-08-15", "2019-09-10")
        assert mask.sum() == 3
        assert mask[7]  # August
        assert mask[8]  # September
        assert mask[12]  # annual

    def test_cross_year_wrap(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2019-11-01", "2020-02-28")
        assert mask.sum() == 5
        assert mask[0]  # January
        assert mask[1]  # February
        assert mask[10]  # November
        assert mask[11]  # December
        assert mask[12]  # annual

    def test_multi_year_includes_all(self):
        mask = _clim_time_mask(_CLIM_TIMES, "2018-06-01", "2020-08-31")
        assert mask.sum() == 13


# ---------------------------------------------------------------------------
# Climatology query_point
# ---------------------------------------------------------------------------


class TestClimatologyQueryPoint:
    """query_point returns correctly filtered + labelled records for CLIMATOLOGY."""

    def _query(self, start: str, end: str) -> list[dict]:
        with patch(
            _PATCHopen_store,
            return_value=_MOCK_CLIM_STORE,
        ):
            groups, unavail = query_point(
                _LAT,
                _LON,
                start,
                end,
                DatasetType.MERRA2,
                TemporalResolution.CLIMATOLOGY,
                ["T2M"],
            )
        assert unavail == []
        return groups[0]["records"] if groups else []

    def test_full_year_returns_13_records(self):
        records = self._query("2019-01-01", "2019-12-31")
        assert len(records) == 13

    def test_single_month_returns_2_records(self):
        records = self._query("2019-08-01", "2019-08-31")
        assert len(records) == 2

    def test_date_labels_are_human_readable(self):
        records = self._query("2019-01-01", "2019-12-31")
        dates = {r["date"] for r in records}
        assert dates == {f"month-{m:02d}" for m in range(1, 13)} | {"annual"}

    def test_single_month_label(self):
        records = self._query("2019-08-01", "2019-08-31")
        dates = {r["date"] for r in records}
        assert dates == {"month-08", "annual"}

    def test_summer_range_returns_4_records(self):
        records = self._query("2019-06-01", "2019-08-31")
        assert len(records) == 4
        dates = {r["date"] for r in records}
        assert "month-06" in dates
        assert "month-07" in dates
        assert "month-08" in dates
        assert "annual" in dates


# ---------------------------------------------------------------------------
# Climatology query_bbox
# ---------------------------------------------------------------------------


class TestClimatologyQueryBbox:
    """query_bbox returns correctly filtered records for CLIMATOLOGY."""

    def _query(self, start: str, end: str) -> list[dict]:
        with patch(
            _PATCHopen_store,
            return_value=_MOCK_CLIM_STORE,
        ):
            results, unavail = query_bbox(
                _BBOX_MIN_LAT,
                _BBOX_MAX_LAT,
                _BBOX_MIN_LON,
                _BBOX_MAX_LON,
                start,
                end,
                DatasetType.MERRA2,
                TemporalResolution.CLIMATOLOGY,
                ["T2M"],
            )
        assert unavail == []
        return results

    def test_full_year_returns_13_records_per_point(self):
        results = self._query("2019-01-01", "2019-12-31")
        for pt in results:
            assert len(pt["records"]) == 13

    def test_single_month_returns_2_records_per_point(self):
        results = self._query("2019-08-01", "2019-08-31")
        for pt in results:
            assert len(pt["records"]) == 2

    def test_date_labels_in_bbox_records(self):
        results = self._query("2019-01-01", "2019-12-31")
        interior = next(r for r in results if r["in_bbox"])
        dates = {rec["date"] for rec in interior["records"]}
        assert dates == {f"month-{m:02d}" for m in range(1, 13)} | {"annual"}


# ---------------------------------------------------------------------------
# estimate_query_runtime_s branch coverage
# ---------------------------------------------------------------------------


def test_estimate_runtime_hourly_branch():
    result = estimate_query_runtime_s(
        1, TemporalResolution.HOURLY, 1, area_deg2=0.0, max_runtime_s=0.0
    )
    assert result is not None
    assert result["_meta"]["success"] is False


def test_estimate_runtime_annual_branch():
    result = estimate_query_runtime_s(
        365, TemporalResolution.ANNUAL, 1, area_deg2=0.0, max_runtime_s=0.0
    )
    assert result is not None
    assert result["_meta"]["success"] is False
