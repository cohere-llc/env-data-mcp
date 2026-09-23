"""Unit tests for the TROPOMI _query module.

All HTTP calls are mocked via ``pytest-httpx``; no network access required.
"""

from __future__ import annotations

import re
from http import HTTPStatus
from pathlib import PurePosixPath
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest

import env_data_mcp.sources.tropomi._query as _query_mod
from env_data_mcp.sources.tropomi._constants import CDSE_ODATA_URL, ProductType
from env_data_mcp.sources.tropomi._query import (
    VariableInfo,
    _extract_date_from_netcdf_path,
    _format_results,
    _get_cogt_urls,
    _get_netcdf_file_paths,
    _query_bbox_from_file,
    _query_point_from_file,
    query_bbox,
    query_point,
)

# ---------------------------------------------------------------------------
# mock data — CDSE
# ---------------------------------------------------------------------------

_CDSE_URL_RE = re.compile(re.escape(CDSE_ODATA_URL))

_CDSE_RESPONSE = {
    "value": [
        {
            "S3Path": "/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/03/S5P_OFFL_L2__O3_____20240103T000105_20240103T000605_00001_01_010302_20240103T015502.nc"  # noqa: E501
        },
        {
            "S3Path": "/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/04/S5P_OFFL_L2__O3_____20240104T000105_20240104T000605_00002_01_010302_20240104T015502.nc"  # noqa: E501
        },
    ]
}


# ---------------------------------------------------------------------------
# _get_netcdf_file_paths
# ---------------------------------------------------------------------------


L2_CH4_VAR = VariableInfo(
    name="OFFL-L2_CH4",
    description="",
    units="",
    product_type=ProductType.OFFL,
    property_name="L2_CH4",
    underscored_name="L2__CH4___",
    cogt_name="methane_mixing_ratio",
)

L2_O3_VAR = VariableInfo(
    name="OFFL-L2_O3",
    description="",
    units="",
    product_type=ProductType.OFFL,
    property_name="L2_O3",
    underscored_name="L2__O3____",
    cogt_name="ozone_total_vertical_column",
)

L2_INVALID_VAR = VariableInfo(
    name="OFFL-L2_INVALID",
    description="",
    units="",
    product_type=ProductType.OFFL,
    property_name="L2_INVALID",
    underscored_name="L2__INVALID",
    cogt_name="invalid",
)


def test_get_netcdf_file_paths_returns_results(httpx_mock):
    """Tests results from _get_s3_file_paths() have the expected structure."""
    httpx_mock.add_response(url=_CDSE_URL_RE, json=_CDSE_RESPONSE)

    results = _get_netcdf_file_paths(
        L2_O3_VAR,
        "2024-01-03",
        "2024-01-05",
        "geography'SRID=4326;POINT(-116.4856 33.8434)'",
    )

    assert len(results) == 2
    for path in results:
        posix_path = PurePosixPath(path)
        assert len(posix_path.parts) > 1
        assert posix_path.suffix == ".nc"


def test_get_netcdf_file_paths_unknown_prefix_returns_empty_list(httpx_mock):
    """CDSE returning no matches for an unknown variable prefix yields an empty list."""
    httpx_mock.add_response(url=_CDSE_URL_RE, json={"value": []})

    results = _get_netcdf_file_paths(
        L2_INVALID_VAR,
        "2024-01-03",
        "2024-01-05",
        "geography'SRID=4326;POINT(-116.4856 33.8434)'",
    )
    assert results == []


def test_get_netcdf_file_paths_http_error_propagates(httpx_mock):
    """Tests that CDSE HTTP errors propagate as HTTPStatusError."""
    httpx_mock.add_response(url=_CDSE_URL_RE, status_code=HTTPStatus.SERVICE_UNAVAILABLE)

    with pytest.raises(httpx.HTTPStatusError):
        _get_netcdf_file_paths(
            L2_O3_VAR,
            "2024-01-03",
            "2024-01-05",
            "geography'SRID=4326;POINT(-116.4856 33.8434)'",
        )


def test_get_netcdf_file_paths_empty_results(httpx_mock):
    """Tests that an empty CDSE response returns an empty list."""
    httpx_mock.add_response(url=_CDSE_URL_RE, json={"value": []})

    results = _get_netcdf_file_paths(
        L2_O3_VAR,
        "2024-01-03",
        "2024-01-05",
        "geography'SRID=4326;POINT(-116.4856 33.8434)'",
    )

    assert results == []


def test_get_netcdf_file_paths_paginates(httpx_mock):
    """Tests that results spanning multiple CDSE pages are all collected.

    The loop continues as long as a page returns exactly ``page_size`` (1000)
    results, and stops when a page returns fewer.
    """
    _PAGE_SIZE = 1000
    page1 = [
        {
            "S3Path": f"/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/01/S5P_OFFL_variable_{i:05d}.nc"  # noqa: E501
        }
        for i in range(_PAGE_SIZE)
    ]
    page2 = [
        {
            "S3Path": f"/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/02/S5P_OFFL_variable_{i:05d}.nc"  # noqa: E501
        }
        for i in range(3)
    ]
    # pytest-httpx returns registered responses in FIFO order for the same URL.
    httpx_mock.add_response(url=_CDSE_URL_RE, json={"value": page1})
    httpx_mock.add_response(url=_CDSE_URL_RE, json={"value": page2})

    results = _get_netcdf_file_paths(
        L2_O3_VAR,
        "2024-01-03",
        "2024-01-05",
        "geography'SRID=4326;POINT(-116.4856 33.8434)'",
    )

    assert len(results) == _PAGE_SIZE + 3
    assert (
        results[0] == "/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/01/S5P_OFFL_variable_00000.nc"
    )
    assert (
        results[_PAGE_SIZE]
        == "/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/02/S5P_OFFL_variable_00000.nc"
    )


# ---------------------------------------------------------------------------
# _get_cogt_url
# ---------------------------------------------------------------------------

# Realistic CDSE S3Path: /eodata/Sentinel-5P/TROPOMI/<folder>/<date>/<name>.nc
_CDSE_S3_PATH = (
    "/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/03/"
    "S5P_OFFL_L2__O3_____20240103T000105_20240103T000605_32856_03_020401_20240103T015600.nc"
)
_CDSE_S3_STEM = (
    "S5P_OFFL_L2__O3_____20240103T000105_20240103T000605_32856_03_020401_20240103T015600"
)


def test_get_cogt_urls_returns_two_vsicurl_paths():
    """Both returned URLs must be valid GDAL VSICURL URLs pointing to .tif files."""
    var_url, qa_url = _get_cogt_urls(_CDSE_S3_PATH, L2_O3_VAR)

    for url in (var_url, qa_url):
        assert url.startswith("/vsicurl/https://meeo-s5p.s3.amazonaws.com/")
        assert url.endswith(".tif")
        # date path and product folder must be preserved
        assert "/2024/01/03/" in url
        assert "/L2__O3____/" in url


def test_get_cogt_urls_filenames():
    """First URL embeds the COGT variable name; second embeds 'qa_value'."""
    var_url, qa_url = _get_cogt_urls(_CDSE_S3_PATH, L2_O3_VAR)

    assert PurePosixPath(var_url).name == (
        f"{_CDSE_S3_STEM}_PRODUCT_ozone_total_vertical_column_4326.tif"
    )
    assert PurePosixPath(qa_url).name == f"{_CDSE_S3_STEM}_PRODUCT_qa_value_4326.tif"


def test_get_cogt_urls_different_variable():
    """The COGT name for a different variable is substituted correctly; qa URL uses 'qa_value'."""
    ch4_s3_path = (
        "/eodata/Sentinel-5P/TROPOMI/L2__CH4___/2024/01/03/S5P_OFFL_L2__CH4___20240103T000105.nc"
    )

    var_url, qa_url = _get_cogt_urls(ch4_s3_path, L2_CH4_VAR)

    assert "/COGT/OFFL/" in var_url
    assert "_PRODUCT_methane_mixing_ratio_4326.tif" in var_url
    assert "_PRODUCT_qa_value_4326.tif" in qa_url


def test_get_cogt_urls_path_missing_tropomi_raises():
    """S3 path with no 'TROPOMI' token must raise ValueError."""
    with pytest.raises(ValueError, match="Unparsable NetCDF S3 path"):
        _get_cogt_urls("/eodata/Sentinel-5P/L2__O3____/2024/01/03/file.nc", L2_O3_VAR)


def test_get_cogt_urls_multiple_tropomi_occurrences_raises():
    """S3 path with more than one 'TROPOMI' token must raise ValueError."""
    with pytest.raises(ValueError, match="Unparsable NetCDF S3 path"):
        _get_cogt_urls(
            "/eodata/TROPOMI/Sentinel-5P/TROPOMI/L2__O3____/2024/01/03/file.nc",
            L2_O3_VAR,
        )


# ---------------------------------------------------------------------------
# _extract_date_from_netcdf_path
# ---------------------------------------------------------------------------


def test_extract_date_from_netcdf_path_returns_date():
    """Extracts YYYY-MM-DD from a standard CDSE S3 path."""
    path = (
        "/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/03/"
        "S5P_OFFL_L2__O3_____20240103T000105_20240103T000605_00001_01_010302_20240103T015502.nc"
    )
    assert _extract_date_from_netcdf_path(path) == "2024-01-03"


def test_extract_date_from_netcdf_path_different_date():
    """Extracts the correct date when month and day differ."""
    path = (
        "/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/04/"
        "S5P_OFFL_L2__O3_____20240104T000105_20240104T000605_00002_01_010302_20240104T015502.nc"
    )
    assert _extract_date_from_netcdf_path(path) == "2024-01-04"


def test_extract_date_from_netcdf_path_too_short_raises():
    """A path with too few segments raises ValueError."""
    with pytest.raises(ValueError, match="Unparsable NetCDF path for date"):
        _extract_date_from_netcdf_path("/OFFL/L2__O3____/2024/01")


# ---------------------------------------------------------------------------
# _query_point_from_file
# ---------------------------------------------------------------------------

_NETCDF_PATH = (
    "/eodata/Sentinel-5P/TROPOMI/L2__O3____/2024/01/03/"
    "S5P_OFFL_L2__O3_____20240103T000105_20240103T000605_00001_01_010302_20240103T015502.nc"
)
_QUERY_LAT, _QUERY_LON = 33.84, -116.49  # the requested coordinate
_PIXEL_LAT, _PIXEL_LON = 33.85, -116.50  # actual pixel centre returned by rasterio


def _make_rasterio_mock(val: float, nodata=None) -> MagicMock:
    """Return a mock rasterio dataset that acts as a context manager."""
    ds = MagicMock()
    ds.nodata = nodata
    ds.index.return_value = (10, 20)
    ds.xy.return_value = (_PIXEL_LON, _PIXEL_LAT)  # rasterio returns (lon, lat)
    ds.sample.return_value = iter([np.array([val])])
    ds.__enter__.return_value = ds
    return ds


@pytest.mark.parametrize(
    "var_val,var_nodata,qa_val,qa_nodata",
    [
        (0.0, 0.0, 75.0, None),  # var equals nodata
        (float("nan"), None, 75.0, None),  # var is NaN
        (float("inf"), None, 75.0, None),  # var is Inf
        (-2e10, None, 75.0, None),  # var below -1e10 sentinel
        (0.5, None, 0.0, 0.0),  # qa equals nodata
        (0.5, None, 49.0, None),  # qa/100 = 0.49 < QA threshold of 0.5
    ],
    ids=[
        "var_nodata",
        "var_nan",
        "var_inf",
        "var_below_threshold",
        "qa_nodata",
        "qa_below_threshold",
    ],
)
def test_query_point_from_file_returns_empty_dict(var_val, var_nodata, qa_val, qa_nodata):
    """Every filtering condition returns an empty dict."""
    var_ds = _make_rasterio_mock(var_val, var_nodata)
    qa_ds = _make_rasterio_mock(qa_val, qa_nodata)
    with (
        patch("rasterio.open", side_effect=[var_ds, qa_ds]),
        patch("env_data_mcp.sources.tropomi._query.Env"),
    ):
        result = _query_point_from_file(L2_O3_VAR, _NETCDF_PATH, _QUERY_LAT, _QUERY_LON)
    assert result == {}


def test_query_point_from_file_returns_result():
    """Valid pixel values at or above the QA threshold yield a populated result dict."""
    var_ds = _make_rasterio_mock(0.42)
    qa_ds = _make_rasterio_mock(75.0)  # 75/100 = 0.75 >= 0.5 threshold
    with (
        patch("rasterio.open", side_effect=[var_ds, qa_ds]),
        patch("env_data_mcp.sources.tropomi._query.Env"),
    ):
        result = _query_point_from_file(L2_O3_VAR, _NETCDF_PATH, _QUERY_LAT, _QUERY_LON)
    assert result == {
        "variable_name": "OFFL-L2_O3",
        "date": "2024-01-03",
        "latitude": _PIXEL_LAT,
        "longitude": _PIXEL_LON,
        "value": pytest.approx(0.42),
    }


# ---------------------------------------------------------------------------
# _format_results
# ---------------------------------------------------------------------------

_FMT_BASE = {"latitude": 33.85, "longitude": -116.50}
_FMT_O3_JAN3 = {**_FMT_BASE, "date": "2024-01-03", "variable_name": "OFFL-L2_O3", "value": 0.42}
_FMT_O3_JAN4 = {**_FMT_BASE, "date": "2024-01-04", "variable_name": "OFFL-L2_O3", "value": 0.45}
_FMT_CH4_JAN3 = {**_FMT_BASE, "date": "2024-01-03", "variable_name": "OFFL-L2_CH4", "value": 1867.0}
_FMT_O3_ELSEWHERE = {
    "latitude": 40.71,
    "longitude": -74.01,
    "date": "2024-01-03",
    "variable_name": "OFFL-L2_O3",
    "value": 0.38,
}


def test_format_results_empty_input():
    """Empty input produces empty output."""
    assert _format_results([]) == []


@pytest.mark.parametrize(
    "records,expected_geo_count,expected_record_counts",
    [
        ([_FMT_O3_JAN3], 1, [1]),
        ([_FMT_O3_JAN3, _FMT_O3_JAN4], 1, [2]),  # same location, two dates → one geo
        ([_FMT_O3_JAN3, _FMT_O3_ELSEWHERE], 2, [1, 1]),  # two locations → two geos
        ([_FMT_O3_JAN3, _FMT_CH4_JAN3], 1, [1]),  # two vars, same date → one record
    ],
    ids=["single", "same_location_two_dates", "two_locations", "two_vars_same_date"],
)
def test_format_results_grouping(records, expected_geo_count, expected_record_counts):
    """Records are grouped correctly by location then by date."""
    result = _format_results(records)
    assert len(result) == expected_geo_count
    actual_counts = sorted(len(g["records"]) for g in result)
    assert actual_counts == sorted(expected_record_counts)


def test_format_results_geojson_structure():
    """Each result has a GeoJSON Point geometry, lat/lon fields, and a records list."""
    result = _format_results([_FMT_O3_JAN3])
    geo = result[0]
    assert geo["geometry"] == {"type": "Point", "coordinates": [-116.50, 33.85]}
    assert geo["latitude"] == 33.85
    assert geo["longitude"] == -116.50
    assert isinstance(geo["records"], list)
    assert "records_dict" not in geo


def test_format_results_record_has_date_and_variable_key():
    """Each date record contains a 'date' key and the variable name as a key."""
    result = _format_results([_FMT_O3_JAN3])
    record = result[0]["records"][0]
    assert record["date"] == "2024-01-03"
    assert record["OFFL-L2_O3"] == pytest.approx(0.42)


def test_format_results_merges_variables_on_same_date():
    """Two variables at the same location and date appear in a single record."""
    result = _format_results([_FMT_O3_JAN3, _FMT_CH4_JAN3])
    records = result[0]["records"]
    assert len(records) == 1
    assert records[0]["date"] == "2024-01-03"
    assert records[0]["OFFL-L2_O3"] == pytest.approx(0.42)
    assert records[0]["OFFL-L2_CH4"] == pytest.approx(1867.0)


# ---------------------------------------------------------------------------
# query_point
# ---------------------------------------------------------------------------


def test_query_point_unknown_variable_is_unavailable():
    """Variables absent from variable info are immediately marked unavailable."""
    with patch.object(_query_mod, "get_full_variable_info", return_value={}):
        results, unavailable, _ = query_point(
            latitude=_QUERY_LAT,
            longitude=_QUERY_LON,
            start_date="2024-01-03",
            end_date="2024-01-05",
            variables=["OFFL-L2_O3"],
        )
    assert results == []
    assert "OFFL-L2_O3" in unavailable


def test_query_point_no_files_variable_is_unavailable():
    """A known variable with no matching CDSE files is returned as unavailable."""
    with (
        patch.object(_query_mod, "get_full_variable_info", return_value={"OFFL-L2_O3": L2_O3_VAR}),
        patch.object(_query_mod, "_get_netcdf_file_paths", return_value=[]),
    ):
        results, unavailable, _ = query_point(
            latitude=_QUERY_LAT,
            longitude=_QUERY_LON,
            start_date="2024-01-03",
            end_date="2024-01-05",
            variables=["OFFL-L2_O3"],
        )
    assert results == []
    assert "OFFL-L2_O3" in unavailable


def test_query_point_returns_results():
    """A variable with a valid pixel read appears in results and not in unavailable."""
    mock_record = {
        "variable_name": "OFFL-L2_O3",
        "date": "2024-01-03",
        "latitude": _PIXEL_LAT,
        "longitude": _PIXEL_LON,
        "value": 0.42,
    }
    with (
        patch.object(_query_mod, "get_full_variable_info", return_value={"OFFL-L2_O3": L2_O3_VAR}),
        patch.object(_query_mod, "_get_netcdf_file_paths", return_value=[_NETCDF_PATH]),
        patch.object(_query_mod, "_query_point_from_file", return_value=mock_record),
    ):
        results, unavailable, _ = query_point(
            latitude=_QUERY_LAT,
            longitude=_QUERY_LON,
            start_date="2024-01-03",
            end_date="2024-01-05",
            variables=["OFFL-L2_O3"],
        )
    assert len(results) == 1
    assert unavailable == []
    records = results[0]["records"]
    assert len(records) == 1
    assert records[0]["OFFL-L2_O3"] == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# _query_bbox_from_file
# ---------------------------------------------------------------------------

_BBOX_QUERY = dict(min_lat=45.75, max_lat=46.75, min_lon=-120.0, max_lon=-119.0)

# 2x2 grid of pixel centres used across bbox tests
_GRID_SHAPE = (2, 2)
_GRID_LATS = np.array([[46.5, 46.5], [46.0, 46.0]])
_GRID_LONS = np.array([[-119.9, -119.4], [-119.9, -119.4]])
_VALID_VALS = np.array([[0.30, 0.35], [0.40, 0.45]])
_VALID_QA = np.array([[80.0, 75.0], [90.0, 85.0]])  # all >= 50 threshold


def _make_bbox_ds_mock(
    vals: np.ndarray,
    *,
    nodata: float | None = None,
    lons: np.ndarray | None = None,
    lats: np.ndarray | None = None,
) -> MagicMock:
    """Return a mock rasterio dataset for bbox reads."""
    ds = MagicMock()
    ds.nodata = nodata
    ds.read.return_value = vals
    if lons is not None and lats is not None:
        # rasterio.DatasetReader.xy() returns (xs, ys) == (lons, lats)
        ds.xy.return_value = (lons, lats)
    ds.__enter__.return_value = ds
    return ds


def _make_bbox_window() -> MagicMock:
    """Return a mock rasterio Window with row_off=col_off=0."""
    w = MagicMock()
    w.row_off = 0
    w.col_off = 0
    return w


def _call_query_bbox(var_ds: MagicMock, qa_ds: MagicMock, window: MagicMock) -> list[dict]:
    """Run _query_bbox_from_file with standard test bbox bounds and mock patches."""
    with (
        patch("rasterio.open", side_effect=[var_ds, qa_ds]),
        patch("rasterio.windows.from_bounds", return_value=window),
        patch("env_data_mcp.sources.tropomi._query.Env"),
    ):
        return _query_bbox_from_file(L2_O3_VAR, _NETCDF_PATH, **_BBOX_QUERY)


@pytest.mark.parametrize(
    "var_vals,var_nodata,qa_vals,qa_nodata",
    [
        (np.full(_GRID_SHAPE, 0.5), 0.5, np.full(_GRID_SHAPE, 75.0), None),  # var == nodata
        (np.full(_GRID_SHAPE, np.nan), None, np.full(_GRID_SHAPE, 75.0), None),  # var NaN
        (np.full(_GRID_SHAPE, np.inf), None, np.full(_GRID_SHAPE, 75.0), None),  # var Inf
        (np.full(_GRID_SHAPE, -2e10), None, np.full(_GRID_SHAPE, 75.0), None),  # var < -1e10
        (np.full(_GRID_SHAPE, 0.5), None, np.full(_GRID_SHAPE, 0.0), 0.0),  # qa == nodata
        (np.full(_GRID_SHAPE, 0.5), None, np.full(_GRID_SHAPE, 49.0), None),  # qa/100 < threshold
    ],
    ids=[
        "all_var_nodata",
        "all_var_nan",
        "all_var_inf",
        "all_var_below_sentinel",
        "all_qa_nodata",
        "all_qa_below_threshold",
    ],
)
def test_query_bbox_from_file_returns_empty_list(var_vals, var_nodata, qa_vals, qa_nodata):
    """Every per-pixel filter condition applied uniformly returns an empty list."""
    var_ds = _make_bbox_ds_mock(var_vals, nodata=var_nodata, lons=_GRID_LONS, lats=_GRID_LATS)
    qa_ds = _make_bbox_ds_mock(qa_vals, nodata=qa_nodata)
    assert _call_query_bbox(var_ds, qa_ds, _make_bbox_window()) == []


def test_query_bbox_from_file_returns_results():
    """All valid pixels in a 2x2 window yield one record per pixel."""
    var_ds = _make_bbox_ds_mock(_VALID_VALS, lons=_GRID_LONS, lats=_GRID_LATS)
    qa_ds = _make_bbox_ds_mock(_VALID_QA)

    results = _call_query_bbox(var_ds, qa_ds, _make_bbox_window())

    assert len(results) == 4
    for rec in results:
        assert rec["variable_name"] == "OFFL-L2_O3"
        assert rec["date"] == "2024-01-03"
        assert "latitude" in rec
        assert "longitude" in rec
        assert "value" in rec
    assert sorted(rec["value"] for rec in results) == pytest.approx(sorted(_VALID_VALS.ravel()))


def test_query_bbox_from_file_record_coordinates():
    """Returned coordinates come from ds.xy(), not from the requested bbox bounds."""
    var_ds = _make_bbox_ds_mock(_VALID_VALS, lons=_GRID_LONS, lats=_GRID_LATS)
    qa_ds = _make_bbox_ds_mock(_VALID_QA)

    results = _call_query_bbox(var_ds, qa_ds, _make_bbox_window())

    returned_lats = sorted(rec["latitude"] for rec in results)
    returned_lons = sorted(rec["longitude"] for rec in results)
    assert returned_lats == pytest.approx(sorted(_GRID_LATS.ravel()))
    assert returned_lons == pytest.approx(sorted(_GRID_LONS.ravel()))


def test_query_bbox_from_file_partial_var_nodata():
    """Only pixels that pass all filters appear in the result."""
    nodata_val = -999.0
    var_vals = np.array([[0.30, 0.35], [nodata_val, nodata_val]])
    qa_vals = np.full(_GRID_SHAPE, 80.0)
    var_ds = _make_bbox_ds_mock(var_vals, nodata=nodata_val, lons=_GRID_LONS, lats=_GRID_LATS)
    qa_ds = _make_bbox_ds_mock(qa_vals)

    results = _call_query_bbox(var_ds, qa_ds, _make_bbox_window())

    assert len(results) == 2
    assert sorted(rec["value"] for rec in results) == pytest.approx([0.30, 0.35])


def test_query_bbox_from_file_partial_qa_below_threshold():
    """Pixels whose qa/100 falls below the threshold are excluded; others kept."""
    # (0,0) and (1,0) pass; (0,1) and (1,1) fail
    qa_vals = np.array([[80.0, 49.0], [75.0, 30.0]])
    var_ds = _make_bbox_ds_mock(_VALID_VALS, lons=_GRID_LONS, lats=_GRID_LATS)
    qa_ds = _make_bbox_ds_mock(qa_vals)

    results = _call_query_bbox(var_ds, qa_ds, _make_bbox_window())

    assert len(results) == 2
    # passing pixels are at (0,0)=0.30 and (1,0)=0.40
    assert sorted(rec["value"] for rec in results) == pytest.approx([0.30, 0.40])


# ---------------------------------------------------------------------------
# query_bbox
# ---------------------------------------------------------------------------


def test_query_bbox_unknown_variable_is_unavailable():
    """Variables absent from variable info are immediately marked unavailable."""
    with patch.object(_query_mod, "get_full_variable_info", return_value={}):
        results, unavailable, _ = query_bbox(
            min_lat=45.75,
            max_lat=46.75,
            min_lon=-120.0,
            max_lon=-119.0,
            start_date="2024-01-03",
            end_date="2024-01-05",
            variables=["OFFL-L2_O3"],
        )
    assert results == []
    assert "OFFL-L2_O3" in unavailable


def test_query_bbox_no_files_variable_is_unavailable():
    """A known variable with no matching CDSE files is returned as unavailable."""
    with (
        patch.object(_query_mod, "get_full_variable_info", return_value={"OFFL-L2_O3": L2_O3_VAR}),
        patch.object(_query_mod, "_get_netcdf_file_paths", return_value=[]),
    ):
        results, unavailable, _ = query_bbox(
            min_lat=45.75,
            max_lat=46.75,
            min_lon=-120.0,
            max_lon=-119.0,
            start_date="2024-01-03",
            end_date="2024-01-05",
            variables=["OFFL-L2_O3"],
        )
    assert results == []
    assert "OFFL-L2_O3" in unavailable


def test_query_bbox_returns_results():
    """A variable with valid pixel reads appears in results and not in unavailable."""
    mock_records = [
        {
            "variable_name": "OFFL-L2_O3",
            "date": "2024-01-03",
            "latitude": float(_GRID_LATS[i, j]),
            "longitude": float(_GRID_LONS[i, j]),
            "value": float(_VALID_VALS[i, j]),
        }
        for i in range(2)
        for j in range(2)
    ]
    with (
        patch.object(_query_mod, "get_full_variable_info", return_value={"OFFL-L2_O3": L2_O3_VAR}),
        patch.object(_query_mod, "_get_netcdf_file_paths", return_value=[_NETCDF_PATH]),
        patch.object(_query_mod, "_query_bbox_from_file", return_value=mock_records),
    ):
        results, unavailable, _ = query_bbox(
            min_lat=45.75,
            max_lat=46.75,
            min_lon=-120.0,
            max_lon=-119.0,
            start_date="2024-01-03",
            end_date="2024-01-05",
            variables=["OFFL-L2_O3"],
        )
    assert len(results) == 4
    assert unavailable == []
    all_values = [
        record["OFFL-L2_O3"]
        for geo in results
        for record in geo["records"]
        if "OFFL-L2_O3" in record
    ]
    assert sorted(all_values) == pytest.approx(sorted(_VALID_VALS.ravel()))


# ---------------------------------------------------------------------------
# _resolve_granules — processing-stream fallback
# ---------------------------------------------------------------------------


L2_CO_OFFL_VAR = VariableInfo(
    name="OFFL-L2_CO",
    description="",
    units="mol m-2",
    product_type=ProductType.OFFL,
    property_name="L2_CO",
    underscored_name="L2__CO____",
    cogt_name="carbonmonoxide_total_column",
)

L2_CO_RPRO_VAR = VariableInfo(
    name="RPRO-L2_CO",
    description="",
    units="mol m-2",
    product_type=ProductType.RPRO,
    property_name="L2_CO",
    underscored_name="L2__CO____",
    cogt_name="carbonmonoxide_total_column",
)

_RPRO_NETCDF_PATH = (
    "/eodata/Sentinel-5P/TROPOMI/L2__CO____/2022/06/07/"
    "S5P_RPRO_L2__CO_____20220607T185134_20220607T203303_24096_03_020400_20230202T222544.nc"
)

_GEOMETRY = "geography'SRID=4326;POINT(-116.4856 33.8434)'"


def test_resolve_granules_uses_requested_stream_when_listed():
    """A stream the catalogue still lists is used as-is, with no fallback lookup."""
    with (
        patch.object(_query_mod, "_get_netcdf_file_paths", return_value=[_NETCDF_PATH]) as paths,
        patch.object(_query_mod, "get_equivalent_variables") as equivalents,
    ):
        served, resolved = _query_mod._resolve_granules(
            L2_CO_OFFL_VAR, "2024-01-03", "2024-01-05", _GEOMETRY
        )

    assert served is L2_CO_OFFL_VAR
    assert resolved == [_NETCDF_PATH]
    assert paths.call_count == 1
    equivalents.assert_not_called()


def test_resolve_granules_falls_back_to_equivalent_stream():
    """A withdrawn stream falls back to the equivalent one that is still listed."""

    def _paths(variable, *_args):
        return [_RPRO_NETCDF_PATH] if variable is L2_CO_RPRO_VAR else []

    with (
        patch.object(_query_mod, "_get_netcdf_file_paths", side_effect=_paths),
        patch.object(_query_mod, "get_equivalent_variables", return_value=[L2_CO_RPRO_VAR]),
    ):
        served, resolved = _query_mod._resolve_granules(
            L2_CO_OFFL_VAR, "2022-06-01", "2022-06-07", _GEOMETRY
        )

    assert served is L2_CO_RPRO_VAR
    assert resolved == [_RPRO_NETCDF_PATH]


def test_resolve_granules_without_any_listed_stream_returns_empty():
    """When no stream is listed for the window the requested variable comes back empty."""
    with (
        patch.object(_query_mod, "_get_netcdf_file_paths", return_value=[]),
        patch.object(_query_mod, "get_equivalent_variables", return_value=[L2_CO_RPRO_VAR]),
    ):
        served, resolved = _query_mod._resolve_granules(
            L2_CO_OFFL_VAR, "2022-06-01", "2022-06-07", _GEOMETRY
        )

    assert served is L2_CO_OFFL_VAR
    assert resolved == []


def test_resolve_granules_stops_at_the_first_listed_equivalent():
    """The preference order is honoured — a later equivalent is never queried."""
    third_stream = VariableInfo(
        name="NRTI-L2_CO",
        description="",
        units="mol m-2",
        product_type=ProductType.NRTI,
        property_name="L2_CO",
        underscored_name="L2__CO____",
        cogt_name="carbonmonoxide_total_column",
    )

    def _paths(variable, *_args):
        return [] if variable is L2_CO_OFFL_VAR else [_RPRO_NETCDF_PATH]

    with (
        patch.object(_query_mod, "_get_netcdf_file_paths", side_effect=_paths) as paths,
        patch.object(
            _query_mod, "get_equivalent_variables", return_value=[L2_CO_RPRO_VAR, third_stream]
        ),
    ):
        served, _resolved = _query_mod._resolve_granules(
            L2_CO_OFFL_VAR, "2022-06-01", "2022-06-07", _GEOMETRY
        )

    assert served is L2_CO_RPRO_VAR
    assert paths.call_count == 2


# ---------------------------------------------------------------------------
# query_point / query_bbox — substitution reporting
# ---------------------------------------------------------------------------


def _substituted_stream_patches(from_file: str, record):
    """Patches where OFFL is withdrawn for the window and RPRO serves it instead."""

    def _paths(variable, *_args):
        return [_RPRO_NETCDF_PATH] if variable is L2_CO_RPRO_VAR else []

    return (
        patch.object(
            _query_mod, "get_full_variable_info", return_value={"OFFL-L2_CO": L2_CO_OFFL_VAR}
        ),
        patch.object(_query_mod, "get_equivalent_variables", return_value=[L2_CO_RPRO_VAR]),
        patch.object(_query_mod, "_get_netcdf_file_paths", side_effect=_paths),
        patch.object(_query_mod, from_file, return_value=record),
    )


def test_query_point_serves_a_withdrawn_stream_from_its_equivalent():
    """Data is returned for a window whose requested stream the catalogue dropped."""
    mock_record = {
        "variable_name": "RPRO-L2_CO",
        "date": "2022-06-07",
        "latitude": _PIXEL_LAT,
        "longitude": _PIXEL_LON,
        "value": 0.031,
    }
    patches = _substituted_stream_patches("_query_point_from_file", mock_record)
    with patches[0], patches[1], patches[2], patches[3]:
        results, unavailable, substituted = query_point(
            latitude=_QUERY_LAT,
            longitude=_QUERY_LON,
            start_date="2022-06-01",
            end_date="2022-06-07",
            variables=["OFFL-L2_CO"],
        )

    assert len(results) == 1
    assert unavailable == []
    # values are reported under the name of the stream that served them
    record = results[0]["records"][0]
    assert record["RPRO-L2_CO"] == pytest.approx(0.031)
    assert "OFFL-L2_CO" not in record
    assert substituted == {"OFFL-L2_CO": "RPRO-L2_CO"}


def test_query_point_reports_no_substitution_for_a_listed_stream():
    """No substitution is declared when the requested stream serves the window."""
    mock_record = {
        "variable_name": "OFFL-L2_O3",
        "date": "2024-01-03",
        "latitude": _PIXEL_LAT,
        "longitude": _PIXEL_LON,
        "value": 0.42,
    }
    with (
        patch.object(_query_mod, "get_full_variable_info", return_value={"OFFL-L2_O3": L2_O3_VAR}),
        patch.object(_query_mod, "_get_netcdf_file_paths", return_value=[_NETCDF_PATH]),
        patch.object(_query_mod, "_query_point_from_file", return_value=mock_record),
    ):
        _results, _unavailable, substituted = query_point(
            latitude=_QUERY_LAT,
            longitude=_QUERY_LON,
            start_date="2024-01-03",
            end_date="2024-01-05",
            variables=["OFFL-L2_O3"],
        )

    assert substituted == {}


def test_query_bbox_serves_a_withdrawn_stream_from_its_equivalent():
    """Bbox reads follow the same fallback and labelling as point reads."""
    mock_records = [
        {
            "variable_name": "RPRO-L2_CO",
            "date": "2022-06-07",
            "latitude": float(_GRID_LATS[i, j]),
            "longitude": float(_GRID_LONS[i, j]),
            "value": float(_VALID_VALS[i, j]),
        }
        for i in range(2)
        for j in range(2)
    ]
    patches = _substituted_stream_patches("_query_bbox_from_file", mock_records)
    with patches[0], patches[1], patches[2], patches[3]:
        results, unavailable, substituted = query_bbox(
            min_lat=45.75,
            max_lat=46.75,
            min_lon=-120.0,
            max_lon=-119.0,
            start_date="2022-06-01",
            end_date="2022-06-07",
            variables=["OFFL-L2_CO"],
        )

    assert len(results) == 4
    assert unavailable == []
    assert substituted == {"OFFL-L2_CO": "RPRO-L2_CO"}
    all_values = [
        record["RPRO-L2_CO"]
        for geo in results
        for record in geo["records"]
        if "RPRO-L2_CO" in record
    ]
    assert sorted(all_values) == pytest.approx(sorted(_VALID_VALS.ravel()))
    assert not any("OFFL-L2_CO" in record for geo in results for record in geo["records"])
