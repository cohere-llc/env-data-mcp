"""Parameterized integration tests for NASA POWER MERRA-2 and SYN1deg.

All tests require live S3/Zarr access.  Run with:
    uv run --extra dev pytest tests/integration/test_nasa_power_live.py -m integration -v --no-cov
"""

from __future__ import annotations

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

from .common import (
    NH_MIDLAT_BBOX,
    NH_RURAL,
    AdapterSpec,
    assert_available_variables_valid,
    assert_grouped_geometry_response_valid,
    assert_meta_success,
    assert_point_results_in_bbox,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Adapter-specific validate hooks - called by test_common_live.py after
# common assertions, and directly by adapter-specific tests
# ---------------------------------------------------------------------------


def _validate_nasa_power_point_result(result: dict) -> None:
    """NASA POWER-specific assertions for a point query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "nasa_power"
    assert result["_meta"]["auth_required"] is False


def _validate_nasa_power_bbox_result(result: dict) -> None:
    """NASA POWER-specific assertions for a bbox query result."""
    assert_grouped_geometry_response_valid(result)
    assert result["_meta"]["source"] == "nasa_power"
    assert result["_meta"]["auth_required"] is False


# ---------------------------------------------------------------------------
# NASA POWER AdapterSpec instances - exported for test_common_live.py
# common assertions, and directly by adapter-specific tests
# ---------------------------------------------------------------------------

MERRA2_SPEC = AdapterSpec(
    name="nasa_power_merra2",
    available_variables=nasa_power_merra2_available_variables,
    point_query=nasa_power_merra2_query,
    bbox_query=nasa_power_merra2_bbox_query,
    supports_date_range=True,
    primary_variable="T2M",
    default_variables=DEFAULT_MERRA2_VARIABLES,
    max_runtime_s=60.0,
    extra_point_kwargs={"temporal_resolution": TemporalResolution.DAILY},
    extra_bbox_kwargs={"temporal_resolution": TemporalResolution.DAILY},
    supports_bbox_bounds_test=False,
    validate_bbox_result=_validate_nasa_power_bbox_result,
    validate_point_result=_validate_nasa_power_point_result,
)

SYN1DEG_SPEC = AdapterSpec(
    name="nasa_power_syn1deg",
    available_variables=nasa_power_syn1deg_available_variables,
    point_query=nasa_power_syn1deg_query,
    bbox_query=nasa_power_syn1deg_bbox_query,
    supports_date_range=True,
    primary_variable="ALLSKY_SFC_SW_DWN",
    default_variables=DEFAULT_SYN1DEG_VARIABLES,
    max_runtime_s=60.0,
    extra_point_kwargs={"temporal_resolution": TemporalResolution.DAILY},
    extra_bbox_kwargs={"temporal_resolution": TemporalResolution.DAILY},
    supports_bbox_bounds_test=False,
    validate_bbox_result=_validate_nasa_power_bbox_result,
    validate_point_result=_validate_nasa_power_point_result,
)


# ---------------------------------------------------------------------------
# Adapter-specific dataset parameter table
# ---------------------------------------------------------------------------


@dataclass
class _DatasetCase:
    spec: AdapterSpec
    dataset_type: DatasetType
    primary_variable_plausible_range: tuple[float, float]


_DATASET_CASES = [
    pytest.param(
        _DatasetCase(
            spec=MERRA2_SPEC,
            dataset_type=DatasetType.MERRA2,
            primary_variable_plausible_range=(-90.0, 60.0),
        ),
        id="merra2",
    ),
    pytest.param(
        _DatasetCase(
            spec=SYN1DEG_SPEC,
            dataset_type=DatasetType.SYN1DEG,
            primary_variable_plausible_range=(0.0, 1500.0),
        ),
        id="syn1deg",
    ),
]


# A single confirmed date used for record-count and date-string tests.
_SINGLE_DATE = "2019-08-19"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=_DATASET_CASES)
def dc(request) -> _DatasetCase:
    return request.param


@pytest.fixture(scope="module")
def avail_vars(dc: _DatasetCase) -> dict:
    """Available variables; loaded once per module run."""
    return dc.spec.available_variables()


@pytest.fixture(scope="module")
def nh_rural_daily(dc: _DatasetCase) -> dict:
    """Daily point query at nh_rural over the standard date window."""
    return dc.spec.point_query(
        latitude=NH_RURAL.coordinates.latitude,
        longitude=NH_RURAL.coordinates.longitude,
        start_date=NH_RURAL.start_date,
        end_date=NH_RURAL.end_date,
        max_runtime_s=dc.spec.max_runtime_s,
        **dc.spec.extra_point_kwargs,
    )


@pytest.fixture(scope="module")
def nh_midlat_bbox_daily(dc: _DatasetCase) -> dict:
    """Daily bbox query at nh_midlat over the standard date window."""
    return dc.spec.bbox_query(
        min_lat=NH_MIDLAT_BBOX.coordinates.min_lat,
        max_lat=NH_MIDLAT_BBOX.coordinates.max_lat,
        min_lon=NH_MIDLAT_BBOX.coordinates.min_lon,
        max_lon=NH_MIDLAT_BBOX.coordinates.max_lon,
        start_date=NH_MIDLAT_BBOX.start_date,
        end_date=NH_MIDLAT_BBOX.end_date,
        max_runtime_s=dc.spec.max_runtime_s,
        **dc.spec.extra_bbox_kwargs,
    )


@pytest.fixture(scope="module")
def nh_rural_single_day(dc: _DatasetCase) -> dict:
    """Daily point query at nh_rural for a single confirmed date."""
    return dc.spec.point_query(
        latitude=NH_RURAL.coordinates.latitude,
        longitude=NH_RURAL.coordinates.longitude,
        start_date=_SINGLE_DATE,
        end_date=_SINGLE_DATE,
        max_runtime_s=dc.spec.max_runtime_s,
        **dc.spec.extra_point_kwargs,
    )


# ---------------------------------------------------------------------------
# TestAvailableVariables
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """available_variables tool returns a valid schema containing expected NASA POWER variables."""

    def test_schema_and_meta(self, avail_vars: dict) -> None:
        # cached results can have 0 latency
        assert_available_variables_valid(avail_vars, min_latency=-0.01)

    def test_primary_var_present(self, dc: _DatasetCase, avail_vars: dict) -> None:
        assert dc.spec.primary_variable in avail_vars["data"], (
            f"{dc.spec.name}: {dc.spec.primary_variable!r} absent from available variables"
        )


# ---------------------------------------------------------------------------
# TestPointQuery
# ---------------------------------------------------------------------------


class TestPointQuery:
    """Daily point query at nh_rural: metadata, schema, variable info, and plausible values."""

    def test_meta_and_schema(self, nh_rural_daily: dict) -> None:
        assert_meta_success(nh_rural_daily)
        assert_grouped_geometry_response_valid(nh_rural_daily)

    def test_source_and_auth_fields(self, nh_rural_daily: dict) -> None:
        assert nh_rural_daily["_meta"]["source"] == "nasa_power"
        assert nh_rural_daily["_meta"]["auth_required"] is False

    def test_query_params_echoed(self, nh_rural_daily: dict, dc: _DatasetCase) -> None:
        qp = nh_rural_daily["_meta"]["query_params"]
        assert qp["latitude"] == pytest.approx(NH_RURAL.coordinates.latitude)
        assert qp["longitude"] == pytest.approx(NH_RURAL.coordinates.longitude)
        assert qp["start_date"] == NH_RURAL.start_date
        assert qp["end_date"] == NH_RURAL.end_date
        assert qp["temporal_resolution"] == TemporalResolution.DAILY.value
        assert qp["variables"] == dc.spec.default_variables
        assert qp["max_runtime_s"] == dc.spec.max_runtime_s

    def test_variable_info_for_requested_vars(self, dc: _DatasetCase, nh_rural_daily: dict) -> None:
        var_info = nh_rural_daily["_meta"]["variable_info"]
        assert dc.spec.primary_variable in var_info, (
            f"{dc.spec.name}: {dc.spec.primary_variable} not in variable_info"
        )
        assert var_info[dc.spec.primary_variable]["units"], (
            f"{dc.spec.primary_variable} missing non-empty units"
        )
        assert var_info[dc.spec.primary_variable]["description"], (
            f"{dc.spec.primary_variable} missing non-empty description"
        )
        for var in dc.spec.default_variables:
            assert var in var_info, f"{dc.spec.name}: {var} not in variable_info"
            assert var_info[var]["units"], f"{var} missing non-empty units"
            assert var_info[var]["description"], f"{var} missing non-empty description"

    def test_default_variables_in_records(self, dc: _DatasetCase, nh_rural_daily: dict) -> None:
        record = nh_rural_daily["data"][0]["records"][0]
        for v in dc.spec.default_variables:
            assert v in record, f"{dc.spec.name}: default variable {v} not found in output record"

    def test_primary_var_units_field_in_records(
        self, dc: _DatasetCase, nh_rural_daily: dict
    ) -> None:
        """Each variable has a co-located ``<var>_units`` field in the record."""
        record = nh_rural_daily["data"][0]["records"][0]
        assert f"{dc.spec.primary_variable}_units" in record

    def test_primary_var_plausible(self, dc: _DatasetCase, nh_rural_daily: dict) -> None:
        lo, hi = dc.primary_variable_plausible_range
        for location in nh_rural_daily["data"]:
            for record in location["records"]:
                assert dc.spec.primary_variable in record
                val = record[dc.spec.primary_variable]
                assert lo <= val <= hi, (
                    f"{dc.spec.name}: {dc.spec.primary_variable}={val} "
                    f"outside plausible range [{lo}, {hi}]"
                )

    def test_single_day_returns_one_record(self, nh_rural_single_day: dict) -> None:
        """A single-day query returns exactly one temporal record."""
        assert len(nh_rural_single_day["data"][0]["records"]) == 1

    def test_single_day_date_matches_query(self, nh_rural_single_day: dict) -> None:
        """The date string in the returned record matches the queried date."""
        assert nh_rural_single_day["data"][0]["records"][0]["date"] == _SINGLE_DATE


# ---------------------------------------------------------------------------
# TestBboxQuery
# ---------------------------------------------------------------------------


class TestBboxQuery:
    """Daily bbox query at nh_midlat: schema, metadata, and point-in-bbox consistency."""

    def test_meta_and_schema(self, nh_midlat_bbox_daily: dict) -> None:
        assert_meta_success(nh_midlat_bbox_daily)
        assert_grouped_geometry_response_valid(nh_midlat_bbox_daily)

    def test_source_and_auth_fields(self, nh_midlat_bbox_daily: dict) -> None:
        assert nh_midlat_bbox_daily["_meta"]["source"] == "nasa_power"
        assert nh_midlat_bbox_daily["_meta"]["auth_required"] is False

    def test_query_params_echoed(self, nh_midlat_bbox_daily: dict, dc: _DatasetCase) -> None:
        qp = nh_midlat_bbox_daily["_meta"]["query_params"]
        assert qp["min_lat"] == pytest.approx(NH_MIDLAT_BBOX.coordinates.min_lat)
        assert qp["max_lat"] == pytest.approx(NH_MIDLAT_BBOX.coordinates.max_lat)
        assert qp["min_lon"] == pytest.approx(NH_MIDLAT_BBOX.coordinates.min_lon)
        assert qp["max_lon"] == pytest.approx(NH_MIDLAT_BBOX.coordinates.max_lon)
        assert qp["start_date"] == NH_MIDLAT_BBOX.start_date
        assert qp["end_date"] == NH_MIDLAT_BBOX.end_date
        assert qp["temporal_resolution"] == TemporalResolution.DAILY.value
        assert qp["variables"] == dc.spec.default_variables
        assert qp["max_runtime_s"] == dc.spec.max_runtime_s

    def test_variable_info_for_requested_vars(
        self, dc: _DatasetCase, nh_midlat_bbox_daily: dict
    ) -> None:
        var_info = nh_midlat_bbox_daily["_meta"]["variable_info"]
        assert dc.spec.primary_variable in var_info, (
            f"{dc.spec.name}: {dc.spec.primary_variable} not in variable_info"
        )
        assert var_info[dc.spec.primary_variable]["units"], (
            f"{dc.spec.primary_variable} missing non-empty units"
        )
        assert var_info[dc.spec.primary_variable]["description"], (
            f"{dc.spec.primary_variable} missing non-emptry description"
        )
        for var in dc.spec.default_variables:
            assert var in var_info, f"{dc.spec.name}: {var} not in variable_info"
            assert var_info[var]["units"], f"{var} missing non-empty units"
            assert var_info[var]["description"], f"{var} missing non-empty description"

    def test_default_variables_in_records(
        self, dc: _DatasetCase, nh_midlat_bbox_daily: dict
    ) -> None:
        record = nh_midlat_bbox_daily["data"][0]["records"][0]
        for v in dc.spec.default_variables:
            assert v in record, f"{dc.spec.name}: default variable {v} not found in output record"

    def test_primary_var_units_field_in_records(
        self, dc: _DatasetCase, nh_midlat_bbox_daily: dict
    ) -> None:
        """Each variable has a co-located ``<var>_units`` field in the record."""
        record = nh_midlat_bbox_daily["data"][0]["records"][0]
        assert f"{dc.spec.primary_variable}_units" in record

    def test_primary_var_plausible(self, dc: _DatasetCase, nh_midlat_bbox_daily: dict) -> None:
        lo, hi = dc.primary_variable_plausible_range
        for location in nh_midlat_bbox_daily["data"]:
            for record in location["records"]:
                assert dc.spec.primary_variable in record
                val = record[dc.spec.primary_variable]
                assert lo <= val <= hi, (
                    f"{dc.spec.name}: {dc.spec.primary_variable}={val} "
                    f"outside plausible range [{lo}, {hi}]"
                )

    def test_point_results_subset_of_bbox_results(
        self,
        nh_rural_daily: dict,
        nh_midlat_bbox_daily: dict,
    ) -> None:
        """Every grid cell returned by the point query must also appear in the bbox results."""
        assert_point_results_in_bbox(nh_rural_daily["data"], nh_midlat_bbox_daily["data"])

    def test_in_bbox_field_present_on_all_grid_points(self, nh_midlat_bbox_daily: dict) -> None:
        """Every geometry group returned by a bbox query carries an ``in_bbox`` bool field."""
        for pt in nh_midlat_bbox_daily["data"]:
            assert "in_bbox" in pt, (
                f"grid point at ({pt.get('latitude')}, {pt.get('longitude')}) "
                "missing 'in_bbox' field"
            )
            assert isinstance(pt["in_bbox"], bool), (
                f"'in_bbox' must be bool; got {type(pt['in_bbox'])}"
            )

    def test_has_interior_and_buffer_grid_points(
        self, dc: _DatasetCase, nh_midlat_bbox_daily: dict
    ) -> None:
        """Bbox results include both interior (in_bbox=True) and buffer (in_bbox=False) cells."""
        interior = [pt for pt in nh_midlat_bbox_daily["data"] if pt.get("in_bbox")]
        buffer = [pt for pt in nh_midlat_bbox_daily["data"] if not pt.get("in_bbox")]
        assert len(interior) >= 1, (
            f"{dc.spec.name}: no interior (in_bbox=True) grid points in bbox result"
        )
        assert len(buffer) >= 1, (
            f"{dc.spec.name}: no buffer (in_bbox=False) grid points in bbox result"
        )

    def test_record_count_per_grid_point(self, nh_midlat_bbox_daily: dict) -> None:
        """Every grid point in a multi-day bbox query has one record per queried day.

        The nh_midlat fixture uses the 7-day standard date window, so each grid
        point must carry exactly 7 daily records.
        """
        for pt in nh_midlat_bbox_daily["data"]:
            assert len(pt["records"]) == 7, (
                f"Expected 7 records per grid point for 7-day query; "
                f"got {len(pt['records'])} at "
                f"({pt.get('latitude')}, {pt.get('longitude')})"
            )


# ---------------------------------------------------------------------------
# Temporal resolution parametrization (NASA POWER-specific)
# ---------------------------------------------------------------------------


@dataclass
class _TemporalCase:
    resolution: TemporalResolution
    start_date: str
    end_date: str
    expected_record_count: int
    max_runtime_s: float


_TEMPORAL_CASES = [
    pytest.param(
        _TemporalCase(
            resolution=TemporalResolution.DAILY,
            start_date="2019-08-15",
            end_date="2019-08-21",
            expected_record_count=7,
            max_runtime_s=30.0,
        ),
        id="daily_7d",
    ),
    pytest.param(
        _TemporalCase(
            resolution=TemporalResolution.MONTHLY,
            start_date="2019-01-01",
            end_date="2019-12-31",
            expected_record_count=12,
            max_runtime_s=30.0,
        ),
        id="monthly_12mo",
    ),
    pytest.param(
        _TemporalCase(
            resolution=TemporalResolution.ANNUAL,
            start_date="2015-01-01",
            end_date="2019-12-31",
            expected_record_count=5,
            max_runtime_s=30.0,
        ),
        id="annual_5yr",
    ),
    pytest.param(
        _TemporalCase(
            resolution=TemporalResolution.HOURLY,
            start_date="2019-08-19",
            end_date="2019-08-19",
            expected_record_count=24,
            max_runtime_s=120.0,
        ),
        id="hourly_1d",
    ),
]


@pytest.fixture(scope="module", params=_TEMPORAL_CASES)
def tc(request) -> _TemporalCase:
    return request.param


@pytest.fixture(scope="module")
def temporal_result(dc: _DatasetCase, tc: _TemporalCase) -> dict:
    """Point query at nh_rural for each temporal resolution; loaded once per combination."""
    return dc.spec.point_query(
        latitude=NH_RURAL.coordinates.latitude,
        longitude=NH_RURAL.coordinates.longitude,
        start_date=tc.start_date,
        end_date=tc.end_date,
        temporal_resolution=tc.resolution,
        variables=[dc.spec.primary_variable],
        max_runtime_s=tc.max_runtime_s,
    )


class TestTemporalResolution:
    """Point queries for DAILY / MONTHLY / ANNUAL / HOURLY produce expected record counts."""

    def test_meta_success(self, temporal_result: dict) -> None:
        assert_meta_success(temporal_result)

    def test_record_count_matches_date_range(
        self,
        dc: _DatasetCase,
        tc: _TemporalCase,
        temporal_result: dict,
    ):
        records = temporal_result["data"][0]["records"]
        assert len(records) == tc.expected_record_count, (
            f"{dc.spec.name}/{tc.resolution.value}: expected {tc.expected_record_count} records, "
            f"got {len(records)}"
        )

    def test_temporal_resolution_echoed_in_meta(self, tc: _TemporalCase, temporal_result: dict):
        assert (
            temporal_result["_meta"]["query_params"]["temporal_resolution"] == tc.resolution.value
        )


# ---------------------------------------------------------------------------
# TestHourlyQuery (NASA POWER-specific)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hourly_result(dc: _DatasetCase) -> dict:
    """Point query for hourly tests."""
    return dc.spec.point_query(
        latitude=NH_RURAL.coordinates.latitude,
        longitude=NH_RURAL.coordinates.longitude,
        start_date="2019-08-19",
        end_date="2019-08-19",
        temporal_resolution=TemporalResolution.HOURLY,
        variables=[dc.spec.primary_variable],
        max_runtime_s=120.0,
    )


class TestHourlyQuery:
    """HOURLY queries produce 24 records with distinct ISO-8601 datetime strings."""

    def test_meta_success(self, hourly_result: dict) -> None:
        assert_meta_success(hourly_result)

    def test_hourly_record_count(self, dc: _DatasetCase, hourly_result) -> None:
        records = hourly_result["data"][0]["records"]
        assert len(records) == 24, f"{dc.spec.name}: expected 24 hourly records, got {len(records)}"

    def test_hourly_dates_are_distinct(self, dc: _DatasetCase, hourly_result: dict):
        """Verifies the int64-truncation fix in _get_coordinates for sub-day time values."""
        assert hourly_result["_meta"]["success"] is True
        records = hourly_result["data"][0]["records"]
        assert len(records) == 24, (
            f"{dc.spec.name}: expected 24 hourly records, got {len(records)}. "
            "may indicate int64 truncation in _get_coordinates"
        )
        dates = [row["date"] for row in records]
        assert len(set(dates)) == 24, (
            f"{dc.spec.name}: 24 hourly records but only {len(set(dates))} distinct date strings. "
            "time axis still truncating to daily resolution"
        )

    def test_hourly_date_format_includes_time(self, dc: _DatasetCase, hourly_result: dict):
        assert hourly_result["_meta"]["success"] is True
        first_date = hourly_result["data"][0]["records"][0]["date"]
        assert "T" in first_date, (
            f"{dc.spec.name}: hourly date '{first_date}' missing time component. "
            "expected ISO datetime"
        )


# ---------------------------------------------------------------------------
# TestClimatologyQuery (NASA POWER-specific)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def clim_result(dc: _DatasetCase) -> dict:
    """Point query for climatology tests."""
    return dc.spec.point_query(
        latitude=NH_RURAL.coordinates.latitude,
        longitude=NH_RURAL.coordinates.longitude,
        start_date="2019-01-01",
        end_date="2019-12-31",
        temporal_resolution=TemporalResolution.CLIMATOLOGY,
        variables=[dc.spec.primary_variable],
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
            f"{dc.spec.name}: expected 13 climatology time steps (12 months + annual), "
            f"got {len(times)}"
        )

    def test_climatology_full_year_returns_13_records(self, dc: _DatasetCase, clim_result: dict):
        """Date range spanning all 12 calendar months; 13 records."""
        assert clim_result["_meta"]["success"] is True, (
            f"{dc.spec.name}: climatology query failed - {clim_result['_meta'].get('error')}"
        )
        n = len(clim_result["data"][0]["records"])
        assert n == 13, f"{dc.spec.name}: expected 13 climatology records (full year), got {n}"

    def test_climatology_single_month_returns_2_records(self, dc: _DatasetCase):
        """Single-month range → 1 month + annual = 2 records."""
        result = dc.spec.point_query(
            latitude=NH_RURAL.coordinates.latitude,
            longitude=NH_RURAL.coordinates.longitude,
            start_date="2019-08-01",
            end_date="2019-08-31",
            temporal_resolution=TemporalResolution.CLIMATOLOGY,
            variables=[dc.spec.primary_variable],
            max_runtime_s=60.0,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.spec.name}: climatology single-month query failed - "
            f"{result['_meta'].get('error')}"
        )
        records = result["data"][0]["records"]
        assert len(records) == 2, (
            f"{dc.spec.name}: expected 2 records (month-08 + annual), got {len(records)}"
        )
        dates = {r["date"] for r in records}
        assert "month-08" in dates, f"{dc.spec.name}: 'month-08' missing from {dates}"
        assert "annual" in dates, f"{dc.spec.name}: 'annual' missing from {dates}"

    def test_climatology_multi_month_returns_months_plus_annual(self, dc: _DatasetCase):
        """Jun-Aug range: months 6, 7, 8 + annual = 4 records."""
        result = dc.spec.point_query(
            latitude=NH_RURAL.coordinates.latitude,
            longitude=NH_RURAL.coordinates.longitude,
            start_date="2019-06-01",
            end_date="2019-08-31",
            temporal_resolution=TemporalResolution.CLIMATOLOGY,
            variables=[dc.spec.primary_variable],
            max_runtime_s=60.0,
        )
        assert result["_meta"]["success"] is True, (
            f"{dc.spec.name}: climatology multi-month query failed - {result['_meta'].get('error')}"
        )
        records = result["data"][0]["records"]
        assert len(records) == 4, (
            f"{dc.spec.name}: expected 4 records (months 6-8 + annual), got {len(records)}"
        )
        dates = {r["date"] for r in records}
        for expected in ("month-06", "month-07", "month-08", "annual"):
            assert expected in dates, f"{dc.spec.name}: '{expected}' missing from {dates}"

    def test_climatology_full_year_date_labels(self, dc: _DatasetCase, clim_result: dict):
        """Full-year query: records labeled month-01...month-12 and annual."""
        assert clim_result["_meta"]["success"] is True
        dates = {r["date"] for r in clim_result["data"][0]["records"]}
        expected = {f"month-{m:02d}" for m in range(1, 13)} | {"annual"}
        assert dates == expected, f"{dc.spec.name}: date labels mismatch - got {sorted(dates)}"
