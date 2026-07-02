"""Parameterized integration tests for NASA POWER MERRA-2 and SYN1deg.

All tests require live S3/Zarr access.  Run with:
    uv run --extra dev pytest tests/integration/test_nasa_power_live.py -m integration -v --no-cov
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from env_data_mcp.sources.nasa_power import (
    DEFAULT_MERRA2_VARIABLES,
    DEFAULT_SYN1DEG_VARIABLES,
    DatasetType,
    TemporalResolution,
    _get_coordinates,
    _open_store,
    nasa_power_merra2_available_variables,
    nasa_power_merra2_bbox_query,
    nasa_power_merra2_query,
    nasa_power_syn1deg_available_variables,
    nasa_power_syn1deg_bbox_query,
    nasa_power_syn1deg_query,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Query geometry constants
# ---------------------------------------------------------------------------

# Yakima River WA: confirmed coverage in both MERRA-2 (1980–present) and SYN1deg (2001–present)
_LAT = 46.2531882
_LON = -119.4768203
_DATE = "2019-08-19"

# 2° × 2° bbox: wide enough to guarantee interior grid points on both the
# 0.5° MERRA-2 grid and the 1° SYN1deg grid.
_BBOX = dict(min_lat=45.5, max_lat=47.5, min_lon=-120.5, max_lon=-118.5)


# ---------------------------------------------------------------------------
# Per-dataset parameter table
# ---------------------------------------------------------------------------


@dataclass
class _DatasetCase:
    label: str
    point_fn: Callable
    bbox_fn: Callable
    avail_fn: Callable
    default_vars: list[str]
    dataset_type: DatasetType
    primary_var: str
    plausible_lo: float
    plausible_hi: float


_DATASET_CASES = [
    pytest.param(
        _DatasetCase(
            label="merra2",
            point_fn=nasa_power_merra2_query,
            bbox_fn=nasa_power_merra2_bbox_query,
            avail_fn=nasa_power_merra2_available_variables,
            default_vars=DEFAULT_MERRA2_VARIABLES,
            dataset_type=DatasetType.MERRA2,
            primary_var="T2M",
            plausible_lo=5.0,
            plausible_hi=50.0,
        ),
        id="merra2",
    ),
    pytest.param(
        _DatasetCase(
            label="syn1deg",
            point_fn=nasa_power_syn1deg_query,
            bbox_fn=nasa_power_syn1deg_bbox_query,
            avail_fn=nasa_power_syn1deg_available_variables,
            default_vars=DEFAULT_SYN1DEG_VARIABLES,
            dataset_type=DatasetType.SYN1DEG,
            primary_var="ALLSKY_SFC_SW_DWN",
            plausible_lo=0.0,
            plausible_hi=1000.0,
        ),
        id="syn1deg",
    ),
]


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=_DATASET_CASES)
def dc(request) -> _DatasetCase:
    return request.param


@pytest.fixture(scope="module")
def avail_vars(dc: _DatasetCase) -> dict:
    """Available variables; loaded once per module run."""
    return dc.avail_fn()


@pytest.fixture(scope="module")
def baseline_daily(dc: _DatasetCase) -> dict:
    """Single-day DAILY result; loaded once per dataset per module run."""
    return dc.point_fn(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        temporal_resolution=TemporalResolution.DAILY,
        variables=[dc.primary_var],
        max_runtime_s=60.0,
    )


# ---------------------------------------------------------------------------
# Test classes — all parametrized by the `dc` fixture (merra2 | syn1deg)
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """available_variables tool returns non-empty dict with correct shape."""

    def test_returns_nonempty_dict(self, dc: _DatasetCase, avail_vars: dict):
        assert isinstance(avail_vars, dict)
        assert len(avail_vars) > 0

    def test_primary_var_present(self, dc: _DatasetCase, avail_vars: dict):
        assert dc.primary_var in avail_vars["data"], (
            f"{dc.label}: {dc.primary_var} missing from available variables"
            " — upstream schema change?"
        )

    def test_primary_var_has_units_and_description(self, dc: _DatasetCase, avail_vars: dict):
        entry = avail_vars["data"][dc.primary_var]
        assert "units" in entry
        assert "description" in entry

    def test_all_default_vars_present(self, dc: _DatasetCase, avail_vars: dict):
        missing = [v for v in dc.default_vars if v not in avail_vars["data"]]
        assert not missing, f"{dc.label}: default variables absent from available set: {missing}"


class TestPointQueryStructure:
    """Baseline single-day DAILY point query: structure and meta fields."""

    def test_success_is_true(self, baseline_daily: dict):
        assert baseline_daily["_meta"]["success"] is True

    def test_returns_one_row(self, baseline_daily: dict):
        assert len(baseline_daily["data"][0]["records"]) == 1

    def test_date_matches_query(self, baseline_daily: dict):
        assert baseline_daily["data"][0]["records"][0]["date"] == _DATE

    def test_primary_var_present_in_row(self, dc: _DatasetCase, baseline_daily: dict):
        assert dc.primary_var in baseline_daily["data"][0]["records"][0]

    def test_primary_var_units_present(self, dc: _DatasetCase, baseline_daily: dict):
        assert f"{dc.primary_var}_units" in baseline_daily["data"][0]["records"][0]

    def test_primary_var_plausible(self, dc: _DatasetCase, baseline_daily: dict):
        val = baseline_daily["data"][0]["records"][0][dc.primary_var]
        assert dc.plausible_lo <= val <= dc.plausible_hi, (
            f"{dc.label}: {dc.primary_var}={val} outside expected range "
            f"[{dc.plausible_lo}, {dc.plausible_hi}]"
        )

    def test_meta_source_field(self, baseline_daily: dict):
        assert baseline_daily["_meta"]["source"] == "nasa_power"

    def test_meta_auth_not_required(self, baseline_daily: dict):
        assert baseline_daily["_meta"]["auth_required"] is False

    def test_meta_latency_positive(self, baseline_daily: dict):
        assert baseline_daily["_meta"]["latency_s"] > 0

    def test_meta_query_params_echoed(self, baseline_daily: dict):
        qp = baseline_daily["_meta"]["query_params"]
        assert qp["latitude"] == _LAT
        assert qp["longitude"] == _LON
        assert qp["start_date"] == _DATE
        assert qp["end_date"] == _DATE
        assert qp["temporal_resolution"] == "daily"

    def test_meta_variable_info_present(self, dc: _DatasetCase, baseline_daily: dict):
        vi = baseline_daily["_meta"]["variable_info"]
        assert dc.primary_var in vi
        assert "units" in vi[dc.primary_var]
        assert "description" in vi[dc.primary_var]

    def test_meta_license_nonempty(self, baseline_daily: dict):
        assert baseline_daily["_meta"]["license"] != ""

    def test_default_variables_returned(self, dc: _DatasetCase):
        result = dc.point_fn(
            latitude=_LAT,
            longitude=_LON,
            start_date=_DATE,
            end_date=_DATE,
            temporal_resolution=TemporalResolution.DAILY,
            max_runtime_s=60.0,
        )
        assert result["_meta"]["success"] is True
        row = result["data"][0]["records"][0]
        found = [v for v in dc.default_vars if v in row]
        assert len(found) > 0, f"{dc.label}: no default variables present in output row"


# ---------------------------------------------------------------------------
# Temporal resolution parametrization
# ---------------------------------------------------------------------------


@dataclass
class _TemporalCase:
    resolution: TemporalResolution
    start_date: str
    end_date: str
    expected_n: int
    max_rt: float


_TEMPORAL_CASES = [
    pytest.param(
        _TemporalCase(
            resolution=TemporalResolution.DAILY,
            start_date="2019-08-15",
            end_date="2019-08-21",
            expected_n=7,
            max_rt=30.0,
        ),
        id="daily_7d",
    ),
    pytest.param(
        _TemporalCase(
            resolution=TemporalResolution.MONTHLY,
            start_date="2019-01-01",
            end_date="2019-12-31",
            expected_n=12,
            max_rt=30.0,
        ),
        id="monthly_12mo",
    ),
    pytest.param(
        _TemporalCase(
            resolution=TemporalResolution.ANNUAL,
            start_date="2015-01-01",
            end_date="2019-12-31",
            expected_n=5,
            max_rt=30.0,
        ),
        id="annual_5yr",
    ),
    pytest.param(
        _TemporalCase(
            resolution=TemporalResolution.HOURLY,
            start_date="2019-08-19",
            end_date="2019-08-19",
            expected_n=24,
            max_rt=120.0,
        ),
        id="hourly_1d",
    ),
]


@pytest.fixture(scope="module", params=_TEMPORAL_CASES)
def tc(request) -> _TemporalCase:
    return request.param


@pytest.fixture(scope="module")
def temporal_result(dc: _DatasetCase, tc: _TemporalCase) -> dict:
    """Single point query for each temporal resolution and dataset; loaded once per resolution
    per test run.
    """
    return dc.point_fn(
        latitude=_LAT,
        longitude=_LON,
        start_date=tc.start_date,
        end_date=tc.end_date,
        temporal_resolution=tc.resolution,
        variables=[dc.primary_var],
        max_runtime_s=tc.max_rt,
    )


class TestTemporalResolution:
    """Point queries for DAILY / MONTHLY / ANNUAL / HOURLY produce expected record counts."""

    def test_record_count_matches_date_range(
        self,
        dc: _DatasetCase,
        tc: _TemporalCase,
        temporal_result: dict,
    ):
        assert temporal_result["_meta"]["success"] is True, (
            f"{dc.label}/{tc.resolution.value}: query failed — {temporal_result['_meta'].get('error')}"  # noqa: E501
        )
        assert len(temporal_result["data"][0]["records"]) == tc.expected_n, (
            f"{dc.label}/{tc.resolution.value}: expected {tc.expected_n} records, "
            f"got {len(temporal_result['data'][0]['records'])}"
        )

    def test_temporal_resolution_echoed_in_meta(self, tc: _TemporalCase, temporal_result: dict):
        assert (
            temporal_result["_meta"]["query_params"]["temporal_resolution"] == tc.resolution.value
        )


@pytest.fixture(scope="module")
def hourly_result(dc: _DatasetCase) -> dict:
    """Point query for hourly tests."""
    return dc.point_fn(
        latitude=_LAT,
        longitude=_LON,
        start_date="2019-08-19",
        end_date="2019-08-19",
        temporal_resolution=TemporalResolution.HOURLY,
        variables=[dc.primary_var],
        max_runtime_s=120.0,
    )


class TestHourlyDetails:
    """HOURLY queries produce 24 records with distinct ISO-8601 datetime strings."""

    def test_hourly_dates_are_distinct(self, dc: _DatasetCase, hourly_result: dict):
        """Verifies the int64-truncation fix in _get_coordinates for sub-day time values."""
        assert hourly_result["_meta"]["success"] is True
        records = hourly_result["data"][0]["records"]
        assert len(records) == 24, (
            f"{dc.label}: expected 24 hourly records, got {len(records)} — "
            "may indicate int64 truncation in _get_coordinates"
        )
        dates = [row["date"] for row in records]
        assert len(set(dates)) == 24, (
            f"{dc.label}: 24 hourly records but only {len(set(dates))} distinct date strings — "
            "time axis still truncating to daily resolution"
        )

    def test_hourly_date_format_includes_time(self, dc: _DatasetCase, hourly_result: dict):
        assert hourly_result["_meta"]["success"] is True
        first_date = hourly_result["data"][0]["records"][0]["date"]
        assert "T" in first_date, (
            f"{dc.label}: hourly date '{first_date}' missing time component — expected ISO datetime"
        )


@pytest.fixture(scope="module")
def clim_result(dc: _DatasetCase) -> dict:
    """Point query for climatology tests."""
    return dc.point_fn(
        latitude=_LAT,
        longitude=_LON,
        start_date="2019-01-01",
        end_date="2019-12-31",
        temporal_resolution=TemporalResolution.CLIMATOLOGY,
        variables=[dc.primary_var],
        max_runtime_s=60.0,
    )


class TestClimatologyProbe:
    """CLIMATOLOGY time axis has 13 steps (12 months + annual mean).

    Queries are filtered by the month range of start_date/end_date:
    - Full-year range (12+ months spanned) → 13 records
    - Multi-month range → N months + annual
    - Single-month range → 1 month + annual = 2 records
    The annual-mean record is always included.
    """

    def test_climatology_store_has_13_time_steps(self, dc: _DatasetCase):
        store = _open_store(dc.dataset_type, TemporalResolution.CLIMATOLOGY)
        _, _, times = _get_coordinates(store)
        assert len(times) == 13, (
            f"{dc.label}: expected 13 climatology time steps (12 months + annual), got {len(times)}"
        )

    def test_climatology_full_year_returns_13_records(self, dc: _DatasetCase, clim_result: dict):
        """Date range spanning all 12 calendar months → 13 records."""
        assert clim_result["_meta"]["success"] is True, (
            f"{dc.label}: climatology query failed — {clim_result['_meta'].get('error')}"
        )
        n = len(clim_result["data"][0]["records"])
        assert n == 13, f"{dc.label}: expected 13 climatology records (full year), got {n}"

    def test_climatology_single_month_returns_2_records(self, dc: _DatasetCase):
        """Single-month range → 1 month + annual = 2 records."""
        result = dc.point_fn(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-08-01",
            end_date="2019-08-31",
            temporal_resolution=TemporalResolution.CLIMATOLOGY,
            variables=[dc.primary_var],
            max_runtime_s=60.0,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.label}: climatology single-month query failed — {result['_meta'].get('error')}"
        )
        records = result["data"][0]["records"]
        assert len(records) == 2, (
            f"{dc.label}: expected 2 records (month-08 + annual), got {len(records)}"
        )
        dates = {r["date"] for r in records}
        assert "month-08" in dates, f"{dc.label}: 'month-08' missing from {dates}"
        assert "annual" in dates, f"{dc.label}: 'annual' missing from {dates}"

    def test_climatology_multi_month_returns_months_plus_annual(self, dc: _DatasetCase):
        """Jun–Aug range → months 6, 7, 8 + annual = 4 records."""
        result = dc.point_fn(
            latitude=_LAT,
            longitude=_LON,
            start_date="2019-06-01",
            end_date="2019-08-31",
            temporal_resolution=TemporalResolution.CLIMATOLOGY,
            variables=[dc.primary_var],
            max_runtime_s=60.0,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.label}: climatology multi-month query failed — {result['_meta'].get('error')}"
        )
        records = result["data"][0]["records"]
        assert len(records) == 4, (
            f"{dc.label}: expected 4 records (months 6-8 + annual), got {len(records)}"
        )
        dates = {r["date"] for r in records}
        for expected in ("month-06", "month-07", "month-08", "annual"):
            assert expected in dates, f"{dc.label}: '{expected}' missing from {dates}"

    def test_climatology_full_year_date_labels(self, dc: _DatasetCase, clim_result: dict):
        """Full-year query: records labeled month-01...month-12 and annual."""
        assert clim_result["_meta"]["success"] is True
        dates = {r["date"] for r in clim_result["data"][0]["records"]}
        expected = {f"month-{m:02d}" for m in range(1, 13)} | {"annual"}
        assert dates == expected, f"{dc.label}: date labels mismatch — got {sorted(dates)}"


class TestNonDefaultVariable:
    """Requesting a non-default variable returns data with that variable present."""

    def test_non_default_variable_returned(self, dc: _DatasetCase):
        all_vars = dc.avail_fn()
        extra = next((v for v in all_vars["data"] if v not in dc.default_vars), None)
        if extra is None:
            pytest.skip(f"{dc.label}: all available variables are in the default set")
        result = dc.point_fn(
            latitude=_LAT,
            longitude=_LON,
            start_date=_DATE,
            end_date=_DATE,
            temporal_resolution=TemporalResolution.DAILY,
            variables=[extra],
            max_runtime_s=60.0,
        )
        assert result["_meta"]["success"] is True
        assert extra in result["data"][0]["records"][0], (
            f"{dc.label}: non-default variable '{extra}' absent from output row"
        )


@pytest.fixture(scope="module")
def unavail_result(dc: _DatasetCase) -> dict:
    """Query for unavilable variables."""
    return dc.point_fn(
        latitude=_LAT,
        longitude=_LON,
        start_date=_DATE,
        end_date=_DATE,
        temporal_resolution=TemporalResolution.DAILY,
        variables=[dc.primary_var, "DOES_NOT_EXIST_XYZ"],
        max_runtime_s=60.0,
    )


class TestUnavailableVariable:
    """Requesting a non-existent variable name does not crash; it is reported."""

    def test_nonexistent_variable_in_unavailable_list(self, dc: _DatasetCase, unavail_result: dict):
        assert unavail_result["_meta"]["success"] is True
        assert "DOES_NOT_EXIST_XYZ" in unavail_result["_meta"]["unavailable_variables"], (
            f"{dc.label}: non-existent variable not reported in unavailable_variables"
        )

    def test_nonexistent_variable_absent_from_row(self, dc: _DatasetCase, unavail_result: dict):
        assert "DOES_NOT_EXIST_XYZ" not in unavail_result["data"][0]["records"][0]


class TestMaxRuntimeGate:
    """max_runtime_s=0.0 must block; max_runtime_s=3600.0 must allow."""

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_zero_max_runtime_blocks_query(self, dc: _DatasetCase, query_mode: str):
        if query_mode == "point":
            result = dc.point_fn(
                latitude=_LAT,
                longitude=_LON,
                start_date=_DATE,
                end_date=_DATE,
                temporal_resolution=TemporalResolution.DAILY,
                variables=[dc.primary_var],
                max_runtime_s=0.0,
            )
        else:
            result = dc.bbox_fn(
                **_BBOX,
                start_date=_DATE,
                end_date=_DATE,
                temporal_resolution=TemporalResolution.DAILY,
                variables=[dc.primary_var],
                max_runtime_s=0.0,
            )
        assert result["_meta"]["success"] is False, (
            f"{dc.label}/{query_mode}: max_runtime_s=0.0 should have blocked the query"
        )
        assert result["_meta"]["slow_query_warning"] is True
        assert result["data"] == []

    @pytest.mark.parametrize("query_mode", ["point", "bbox"])
    def test_generous_max_runtime_allows_query(self, dc: _DatasetCase, query_mode: str):
        if query_mode == "point":
            result = dc.point_fn(
                latitude=_LAT,
                longitude=_LON,
                start_date=_DATE,
                end_date=_DATE,
                temporal_resolution=TemporalResolution.DAILY,
                variables=[dc.primary_var],
                max_runtime_s=3600.0,
            )
        else:
            result = dc.bbox_fn(
                **_BBOX,
                start_date=_DATE,
                end_date=_DATE,
                temporal_resolution=TemporalResolution.DAILY,
                variables=[dc.primary_var],
                max_runtime_s=3600.0,
            )
        assert result["_meta"]["success"] is True, (
            f"{dc.label}/{query_mode}: max_runtime_s=3600.0 should have allowed the query"
        )
        assert len(result["data"]) > 0


@pytest.fixture(scope="module")
def bbox_result(dc: _DatasetCase) -> dict:
    """Bounding box query."""
    return dc.bbox_fn(
        **_BBOX,
        start_date=_DATE,
        end_date=_DATE,
        temporal_resolution=TemporalResolution.DAILY,
        variables=[dc.primary_var],
        max_runtime_s=60.0,
    )


class TestBboxQuery:
    """Bbox queries return grid points with correct structure and plausible values."""

    def test_returns_data(self, dc: _DatasetCase, bbox_result: dict):
        assert bbox_result["_meta"]["success"] is True
        assert len(bbox_result["data"]) > 0

    def test_has_interior_and_buffer_points(self, dc: _DatasetCase, bbox_result: dict):
        in_bbox = [pt for pt in bbox_result["data"] if pt["in_bbox"]]
        buffer = [pt for pt in bbox_result["data"] if not pt["in_bbox"]]
        assert len(in_bbox) >= 1, f"{dc.label}: no in_bbox=True grid points"
        assert len(buffer) >= 1, f"{dc.label}: no buffer (in_bbox=False) grid points"

    def test_grid_point_structure(self, dc: _DatasetCase, bbox_result: dict):
        for pt in bbox_result["data"]:
            assert "latitude" in pt
            assert "longitude" in pt
            assert "in_bbox" in pt
            assert "records" in pt
            assert len(pt["records"]) == 1
            assert dc.primary_var in pt["records"][0]

    def test_primary_var_plausible_at_all_points(self, dc: _DatasetCase, bbox_result: dict):
        for pt in bbox_result["data"]:
            val = pt["records"][0][dc.primary_var]
            assert dc.plausible_lo <= val <= dc.plausible_hi, (
                f"{dc.label} bbox: {dc.primary_var}={val} out of plausible range at "
                f"({pt['latitude']}, {pt['longitude']})"
            )

    def test_multi_day_records_per_grid_point(self, dc: _DatasetCase):
        result = dc.bbox_fn(
            **_BBOX,
            start_date="2019-08-17",
            end_date="2019-08-19",
            temporal_resolution=TemporalResolution.DAILY,
            variables=[dc.primary_var],
            max_runtime_s=60.0,
        )
        for pt in result["data"]:
            assert len(pt["records"]) == 3

    def test_meta_query_params_echoed(self, dc: _DatasetCase, bbox_result: dict):
        qp = bbox_result["_meta"]["query_params"]
        assert qp["min_lat"] == _BBOX["min_lat"]
        assert qp["max_lat"] == _BBOX["max_lat"]
        assert qp["temporal_resolution"] == "daily"


class TestSchemaStability:
    """Detects upstream variable renames, unit changes, and missing meta fields."""

    def test_primary_var_field_present(self, dc: _DatasetCase, baseline_daily: dict):
        row = baseline_daily["data"][0]["records"][0]
        assert dc.primary_var in row, (
            f"{dc.label}: {dc.primary_var} missing — upstream may have renamed it"
        )

    def test_primary_var_units_field_present(self, dc: _DatasetCase, baseline_daily: dict):
        row = baseline_daily["data"][0]["records"][0]
        assert f"{dc.primary_var}_units" in row, (
            f"{dc.label}: {dc.primary_var}_units missing — units no longer echoed"
        )

    def test_primary_var_physical_range(self, dc: _DatasetCase, baseline_daily: dict):
        val = baseline_daily["data"][0]["records"][0][dc.primary_var]
        assert dc.plausible_lo - 5 <= val <= dc.plausible_hi + 5, (
            f"{dc.label}: {dc.primary_var}={val} outside physical range — "
            "fill value leaked or unit changed?"
        )

    def test_variable_info_in_meta(self, dc: _DatasetCase, baseline_daily: dict):
        vi = baseline_daily["_meta"]["variable_info"]
        assert dc.primary_var in vi
        assert "units" in vi[dc.primary_var]
        assert "description" in vi[dc.primary_var]

    def test_meta_license_nonempty(self, baseline_daily: dict):
        assert baseline_daily["_meta"]["license"] != ""

    def test_meta_rows_returned_consistent(self, baseline_daily: dict):
        assert baseline_daily["_meta"]["rows_returned"] == len(baseline_daily["data"][0]["records"])
