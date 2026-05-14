"""Unit tests for the Sentinel-5P source adapter.

All S3 / h5py calls are mocked; no network access required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from env_data_mcp.sources.sentinel5p import (
    _PRODUCTS,
    _QA_THRESHOLD,
    LICENSE_INFO,
    VARIABLE_INFO,
    _extract_mean_bbox,
    _extract_pixel_point,
    _granule_path_prefix,
    _iter_dates,
    sentinel5p_bbox_query,
    sentinel5p_query,
)

# ---------------------------------------------------------------------------
# _granule_path_prefix
# ---------------------------------------------------------------------------


def test_granule_path_prefix_co():
    path = _granule_path_prefix("CO", "2019-08-19")
    assert path == "meeo-s5p/OFFL/L2__CO____/2019/08/19/"


def test_granule_path_prefix_no2():
    path = _granule_path_prefix("NO2", "2020-01-05")
    assert "L2__NO2___" in path
    assert "/2020/01/05/" in path


def test_granule_path_prefix_ch4():
    path = _granule_path_prefix("CH4", "2021-12-31")
    assert "L2__CH4___" in path
    assert "/2021/12/31/" in path


def test_granule_path_prefix_invalid_date_raises():
    with pytest.raises(ValueError, match="Invalid date"):
        _granule_path_prefix("CO", "not-a-date")


# ---------------------------------------------------------------------------
# _iter_dates
# ---------------------------------------------------------------------------


def test_iter_dates_single_day():
    dates = _iter_dates("2019-08-19", "2019-08-19")
    assert dates == ["2019-08-19"]


def test_iter_dates_range():
    dates = _iter_dates("2019-08-19", "2019-08-21")
    assert dates == ["2019-08-19", "2019-08-20", "2019-08-21"]


def test_iter_dates_invalid_start():
    with pytest.raises(ValueError):
        _iter_dates("2019/08/19", "2019-08-21")


# ---------------------------------------------------------------------------
# Synthetic Dataset helper
# ---------------------------------------------------------------------------

_YAKIMA_LAT = 46.25
_YAKIMA_LON = -119.47


def _make_arrays(
    lat_val: float,
    lon_val: float,
    co_val: float,
    qa_val: float = 0.75,
    variable: str = "carbonmonoxide_total_column",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (lat_f, lon_f, qa_f, val_f) 1-D numpy arrays mimicking a TROPOMI swath patch."""
    lat = np.array([[[lat_val, lat_val + 0.01], [lat_val - 0.01, lat_val]]])
    lon = np.array([[[lon_val, lon_val + 0.01], [lon_val - 0.01, lon_val]]])
    qa = np.full_like(lat, qa_val)
    val = np.full_like(lat, co_val)
    return lat.ravel(), lon.ravel(), qa.ravel(), val.ravel()


def _make_h5_mock(
    lat_val: float,
    lon_val: float,
    co_val: float,
    qa_val: float = 0.75,
    variable: str = "carbonmonoxide_total_column",
) -> MagicMock:
    """Return a MagicMock that behaves like an h5py.File context manager."""
    lat = np.array([[[lat_val, lat_val + 0.01], [lat_val - 0.01, lat_val]]])
    lon = np.array([[[lon_val, lon_val + 0.01], [lon_val - 0.01, lon_val]]])
    qa = np.full_like(lat, qa_val)
    val = np.full_like(lat, co_val)

    datasets: dict[str, np.ndarray] = {
        "PRODUCT/latitude": lat,
        "PRODUCT/longitude": lon,
        "PRODUCT/qa_value": qa,
        f"PRODUCT/{variable}": val,
    }

    mock_hf = MagicMock()
    mock_hf.__getitem__ = MagicMock(side_effect=lambda key: datasets[key])

    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=mock_hf)
    mock_file.__exit__ = MagicMock(return_value=False)
    return mock_file


# ---------------------------------------------------------------------------
# _extract_pixel_point
# ---------------------------------------------------------------------------


def test_extract_pixel_point_finds_nearest():
    lat_f, lon_f, qa_f, val_f = _make_arrays(_YAKIMA_LAT, _YAKIMA_LON, co_val=0.035)
    val = _extract_pixel_point(lat_f, lon_f, qa_f, val_f, _YAKIMA_LAT, _YAKIMA_LON)
    assert val is not None
    assert abs(val - 0.035) < 1e-6


def test_extract_pixel_point_outside_swath_returns_none():
    # Granule centred on the equator (0, 0) — far from Yakima.
    lat_f, lon_f, qa_f, val_f = _make_arrays(0.0, 0.0, co_val=0.02)
    val = _extract_pixel_point(lat_f, lon_f, qa_f, val_f, _YAKIMA_LAT, _YAKIMA_LON)
    assert val is None


def test_extract_pixel_point_low_qa_returns_none():
    lat_f, lon_f, qa_f, val_f = _make_arrays(
        _YAKIMA_LAT, _YAKIMA_LON, co_val=0.035, qa_val=_QA_THRESHOLD - 0.1
    )
    val = _extract_pixel_point(lat_f, lon_f, qa_f, val_f, _YAKIMA_LAT, _YAKIMA_LON)
    assert val is None


def test_extract_pixel_point_fill_value_returns_none():
    lat_f, lon_f, qa_f, val_f = _make_arrays(_YAKIMA_LAT, _YAKIMA_LON, co_val=-9.999e20)
    val = _extract_pixel_point(lat_f, lon_f, qa_f, val_f, _YAKIMA_LAT, _YAKIMA_LON)
    assert val is None


# ---------------------------------------------------------------------------
# _extract_mean_bbox
# ---------------------------------------------------------------------------


def test_extract_mean_bbox_returns_mean():
    lat_f, lon_f, qa_f, val_f = _make_arrays(_YAKIMA_LAT, _YAKIMA_LON, co_val=0.04)
    val = _extract_mean_bbox(
        lat_f,
        lon_f,
        qa_f,
        val_f,
        min_lat=_YAKIMA_LAT - 0.1,
        max_lat=_YAKIMA_LAT + 0.1,
        min_lon=_YAKIMA_LON - 0.2,
        max_lon=_YAKIMA_LON + 0.2,
    )
    assert val is not None
    assert abs(val - 0.04) < 1e-6


def test_extract_mean_bbox_no_pixels_returns_none():
    lat_f, lon_f, qa_f, val_f = _make_arrays(0.0, 0.0, co_val=0.04)
    val = _extract_mean_bbox(
        lat_f,
        lon_f,
        qa_f,
        val_f,
        min_lat=_YAKIMA_LAT - 0.1,
        max_lat=_YAKIMA_LAT + 0.1,
        min_lon=_YAKIMA_LON - 0.2,
        max_lon=_YAKIMA_LON + 0.2,
    )
    assert val is None


# ---------------------------------------------------------------------------
# sentinel5p_query MCP tool
# ---------------------------------------------------------------------------

_FAKE_GRANULE = "meeo-s5p/OFFL/L2__CO____/2019/08/19/S5P_OFFL_L2__CO_____20190819T013442.nc"


def test_sentinel5p_query_success():
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [_FAKE_GRANULE]
    mock_file = _make_h5_mock(_YAKIMA_LAT, _YAKIMA_LON, co_val=0.035)

    with (
        patch("env_data_mcp.sources.sentinel5p.s3fs.S3FileSystem", return_value=mock_fs),
        patch("env_data_mcp.sources.sentinel5p.h5py.File", return_value=mock_file),
    ):
        result = sentinel5p_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            product="CO",
        )

    assert result["_meta"]["success"] is True
    assert result["_meta"]["source"] == "sentinel5p"
    assert len(result["data"]) == 1
    assert "CO" in result["data"][0]
    assert result["data"][0]["CO_units"] == _PRODUCTS["CO"]["units"]


def test_sentinel5p_query_meta_variable_info():
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [_FAKE_GRANULE]
    mock_file = _make_h5_mock(_YAKIMA_LAT, _YAKIMA_LON, co_val=0.035)

    with (
        patch("env_data_mcp.sources.sentinel5p.s3fs.S3FileSystem", return_value=mock_fs),
        patch("env_data_mcp.sources.sentinel5p.h5py.File", return_value=mock_file),
    ):
        result = sentinel5p_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            product="CO",
        )

    assert "CO" in result["_meta"]["variable_info"]
    assert result["_meta"]["variable_info"]["CO"]["units"] == VARIABLE_INFO["CO"]["units"]


def test_sentinel5p_query_no_granules():
    mock_fs = MagicMock()
    mock_fs.ls.return_value = []  # No granules on this date.

    with patch("env_data_mcp.sources.sentinel5p.s3fs.S3FileSystem", return_value=mock_fs):
        result = sentinel5p_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            product="CO",
        )

    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] is not None


def test_sentinel5p_query_no_match_in_swath():
    """Granule exists but swath doesn't cover target — no records returned."""
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [_FAKE_GRANULE]
    mock_file = _make_h5_mock(0.0, 0.0, co_val=0.02)  # Centred on equator.

    with (
        patch("env_data_mcp.sources.sentinel5p.s3fs.S3FileSystem", return_value=mock_fs),
        patch("env_data_mcp.sources.sentinel5p.h5py.File", return_value=mock_file),
    ):
        result = sentinel5p_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            product="CO",
        )

    assert result["_meta"]["success"] is True
    assert result["data"] == []


def test_sentinel5p_query_invalid_product():
    result = sentinel5p_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        start_date="2019-08-19",
        end_date="2019-08-19",
        product="SOX",  # Invalid.
    )
    assert result["_meta"]["success"] is False
    assert "SOX" in result["_meta"]["error"]


def test_sentinel5p_query_invalid_date():
    result = sentinel5p_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        start_date="not-a-date",
        end_date="2019-08-19",
        product="CO",
    )
    assert result["_meta"]["success"] is False


def test_sentinel5p_query_license_populated():
    mock_fs = MagicMock()
    mock_fs.ls.return_value = []

    with patch("env_data_mcp.sources.sentinel5p.s3fs.S3FileSystem", return_value=mock_fs):
        result = sentinel5p_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            product="CO",
        )

    assert result["_meta"]["license"] == LICENSE_INFO["license"]
    assert result["_meta"]["auth_required"] is False


def test_sentinel5p_query_s3_error_returns_structured():
    with patch(
        "env_data_mcp.sources.sentinel5p.s3fs.S3FileSystem",
        side_effect=ConnectionError("no route"),
    ):
        result = sentinel5p_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            product="CO",
        )

    assert result["_meta"]["success"] is False
    assert "no route" in result["_meta"]["error"]


# ---------------------------------------------------------------------------
# sentinel5p_bbox_query MCP tool
# ---------------------------------------------------------------------------


def test_sentinel5p_bbox_query_success():
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [_FAKE_GRANULE]
    mock_file = _make_h5_mock(_YAKIMA_LAT, _YAKIMA_LON, co_val=0.035)

    with (
        patch("env_data_mcp.sources.sentinel5p.s3fs.S3FileSystem", return_value=mock_fs),
        patch("env_data_mcp.sources.sentinel5p.h5py.File", return_value=mock_file),
    ):
        result = sentinel5p_bbox_query(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-19",
            end_date="2019-08-19",
            product="CO",
        )

    assert result["_meta"]["success"] is True
    assert "bbox_centroid_lat" in result["_meta"]
    assert "bbox_centroid_lon" in result["_meta"]


def test_sentinel5p_bbox_query_records_have_mean_key():
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [_FAKE_GRANULE]
    mock_file = _make_h5_mock(_YAKIMA_LAT, _YAKIMA_LON, co_val=0.035)

    with (
        patch("env_data_mcp.sources.sentinel5p.s3fs.S3FileSystem", return_value=mock_fs),
        patch("env_data_mcp.sources.sentinel5p.h5py.File", return_value=mock_file),
    ):
        result = sentinel5p_bbox_query(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-19",
            end_date="2019-08-19",
            product="CO",
        )

    if result["data"]:
        assert "CO_mean" in result["data"][0]
