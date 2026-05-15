"""Unit tests for the Sentinel-5P CDSE + COGT adapter.

All HTTP / rasterio calls are mocked; no network access required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import rasterio.transform

from env_data_mcp.sources.sentinel5p import (
    _PRODUCTS,
    LICENSE_INFO,
    VARIABLE_INFO,
    _cdse_query_granules,
    _cogt_url,
    _read_cogt_point,
    sentinel5p_bbox_query,
    sentinel5p_query,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_YAKIMA_LAT = 46.25
_YAKIMA_LON = -119.47

# A realistic granule name; date part "20190819" is at chars 20-27.
_FAKE_GRANULE = (
    "S5P_OFFL_L2__CO_____20190819T013442_20190819T031611_09572_01_010302_20190822T090800.nc"
)

# A real Affine transform covering the whole globe at ~0.037°/pixel.
_WORLD_TRANSFORM = rasterio.transform.from_bounds(-180, -90, 180, 90, 9610, 4972)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cdse_mock(granule_names: list[str]) -> MagicMock:
    """Return a mock httpx response carrying the given granule names."""
    resp = MagicMock()
    resp.json.return_value = {"value": [{"Name": n} for n in granule_names]}
    return resp


def _point_ds(sample_val: float, nodata: float = -9999.0) -> MagicMock:
    """Return a mock rasterio dataset for ``ds.sample()`` calls."""
    ds = MagicMock()
    ds.nodata = nodata
    ds.sample.return_value = [[sample_val]]
    ds.__enter__ = MagicMock(return_value=ds)
    ds.__exit__ = MagicMock(return_value=False)
    return ds


def _bbox_ds(
    data_val: float,
    nodata: float = -9999.0,
    shape: tuple[int, int] = (4, 4),
) -> MagicMock:
    """Return a mock rasterio dataset for ``ds.read(window=...)`` calls."""
    ds = MagicMock()
    ds.nodata = nodata
    ds.transform = _WORLD_TRANSFORM
    ds.read.return_value = np.full(shape, data_val, dtype=np.float32)
    ds.__enter__ = MagicMock(return_value=ds)
    ds.__exit__ = MagicMock(return_value=False)
    return ds


# ---------------------------------------------------------------------------
# _cogt_url
# ---------------------------------------------------------------------------


def test_cogt_url_co_variable():
    url = _cogt_url(_FAKE_GRANULE, "CO", "carbonmonoxide_total_column")
    assert "COGT/OFFL/L2__CO____/2019/08/19/" in url
    assert "_PRODUCT_carbonmonoxide_total_column_4326.tif" in url
    assert url.startswith("/vsicurl/https://meeo-s5p.s3.amazonaws.com/")


def test_cogt_url_qa_value():
    url = _cogt_url(_FAKE_GRANULE, "CO", "qa_value")
    assert "_PRODUCT_qa_value_4326.tif" in url


def test_cogt_url_no2():
    no2_granule = (
        "S5P_OFFL_L2__NO2____20200105T120000_20200105T134130_01234_01_010302_20200110T000000.nc"
    )
    url = _cogt_url(no2_granule, "NO2", "nitrogendioxide_tropospheric_column")
    assert "COGT/OFFL/L2__NO2___/2020/01/05/" in url


# ---------------------------------------------------------------------------
# _cdse_query_granules
# ---------------------------------------------------------------------------


def test_cdse_query_granules_point_returns_names():
    mock_resp = _cdse_mock([_FAKE_GRANULE])
    with patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp):
        names = _cdse_query_granules(
            "CO", "2019-08-19", "2019-08-19", lat=_YAKIMA_LAT, lon=_YAKIMA_LON
        )
    assert names == [_FAKE_GRANULE]


def test_cdse_query_granules_empty_returns_empty_list():
    mock_resp = _cdse_mock([])
    with patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp):
        names = _cdse_query_granules(
            "CO", "2019-08-19", "2019-08-19", lat=_YAKIMA_LAT, lon=_YAKIMA_LON
        )
    assert names == []


def test_cdse_query_granules_bbox():
    mock_resp = _cdse_mock([_FAKE_GRANULE])
    with patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp) as mock_get:
        _cdse_query_granules(
            "CO",
            "2019-08-19",
            "2019-08-19",
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-120.0,
            max_lon=-119.0,
        )
    call_kwargs = mock_get.call_args[1]
    assert "POLYGON" in call_kwargs["params"]["$filter"]


# ---------------------------------------------------------------------------
# _read_cogt_point
# ---------------------------------------------------------------------------


def test_read_cogt_point_valid_pixel():
    co_ds = _point_ds(0.035)
    qa_ds = _point_ds(75.0, nodata=255.0)
    with patch("env_data_mcp.sources.sentinel5p.rasterio.open", side_effect=[co_ds, qa_ds]):
        rec = _read_cogt_point(_FAKE_GRANULE, "CO", _YAKIMA_LAT, _YAKIMA_LON)
    assert rec is not None
    assert abs(rec["CO"] - 0.035) < 1e-9
    assert rec["date"] == "2019-08-19"
    assert rec["CO_units"] == _PRODUCTS["CO"]["units"]


def test_read_cogt_point_co_nodata_returns_none():
    co_ds = _point_ds(-9999.0, nodata=-9999.0)
    qa_ds = _point_ds(75.0, nodata=255.0)
    with patch("env_data_mcp.sources.sentinel5p.rasterio.open", side_effect=[co_ds, qa_ds]):
        rec = _read_cogt_point(_FAKE_GRANULE, "CO", _YAKIMA_LAT, _YAKIMA_LON)
    assert rec is None


def test_read_cogt_point_qa_nodata_returns_none():
    co_ds = _point_ds(0.035)
    qa_ds = _point_ds(255.0, nodata=255.0)
    with patch("env_data_mcp.sources.sentinel5p.rasterio.open", side_effect=[co_ds, qa_ds]):
        rec = _read_cogt_point(_FAKE_GRANULE, "CO", _YAKIMA_LAT, _YAKIMA_LON)
    assert rec is None


def test_read_cogt_point_low_qa_returns_none():
    # QA = 40 → 0.40 normalised < 0.5 threshold
    co_ds = _point_ds(0.035)
    qa_ds = _point_ds(40.0, nodata=255.0)
    with patch("env_data_mcp.sources.sentinel5p.rasterio.open", side_effect=[co_ds, qa_ds]):
        rec = _read_cogt_point(_FAKE_GRANULE, "CO", _YAKIMA_LAT, _YAKIMA_LON)
    assert rec is None


def test_read_cogt_point_rasterio_error_returns_none():
    with patch(
        "env_data_mcp.sources.sentinel5p.rasterio.open",
        side_effect=RuntimeError("GDAL error"),
    ):
        rec = _read_cogt_point(_FAKE_GRANULE, "CO", _YAKIMA_LAT, _YAKIMA_LON)
    assert rec is None


# ---------------------------------------------------------------------------
# sentinel5p_query MCP tool
# ---------------------------------------------------------------------------


def test_sentinel5p_query_success():
    mock_resp = _cdse_mock([_FAKE_GRANULE])
    co_ds = _point_ds(0.035)
    qa_ds = _point_ds(75.0, nodata=255.0)

    with (
        patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp),
        patch("env_data_mcp.sources.sentinel5p.rasterio.open", side_effect=[co_ds, qa_ds]),
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
    mock_resp = _cdse_mock([_FAKE_GRANULE])
    co_ds = _point_ds(0.035)
    qa_ds = _point_ds(75.0, nodata=255.0)

    with (
        patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp),
        patch("env_data_mcp.sources.sentinel5p.rasterio.open", side_effect=[co_ds, qa_ds]),
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
    mock_resp = _cdse_mock([])
    with patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp):
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


def test_sentinel5p_query_nodata_pixel_returns_empty():
    """CDSE returns a granule but the pixel is nodata — no records returned."""
    mock_resp = _cdse_mock([_FAKE_GRANULE])
    co_ds = _point_ds(-9999.0, nodata=-9999.0)
    qa_ds = _point_ds(75.0, nodata=255.0)

    with (
        patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp),
        patch("env_data_mcp.sources.sentinel5p.rasterio.open", side_effect=[co_ds, qa_ds]),
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
        product="SOX",
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
    mock_resp = _cdse_mock([])
    with patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp):
        result = sentinel5p_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
            product="CO",
        )

    assert result["_meta"]["license"] == LICENSE_INFO["license"]
    assert result["_meta"]["auth_required"] is False


def test_sentinel5p_query_http_error_returns_structured():
    with patch(
        "env_data_mcp.sources.sentinel5p.httpx.get",
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
    mock_resp = _cdse_mock([_FAKE_GRANULE])
    co_ds = _bbox_ds(0.035)
    qa_ds = _bbox_ds(75.0, nodata=255.0)

    with (
        patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp),
        patch("env_data_mcp.sources.sentinel5p.rasterio.open", side_effect=[co_ds, qa_ds]),
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
    mock_resp = _cdse_mock([_FAKE_GRANULE])
    co_ds = _bbox_ds(0.035)
    qa_ds = _bbox_ds(75.0, nodata=255.0)

    with (
        patch("env_data_mcp.sources.sentinel5p.httpx.get", return_value=mock_resp),
        patch("env_data_mcp.sources.sentinel5p.rasterio.open", side_effect=[co_ds, qa_ds]),
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
