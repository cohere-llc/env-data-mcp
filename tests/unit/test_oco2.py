"""Unit tests for the OCO-2 source adapter.

All HTTP and HDF5 I/O is mocked; no network access required.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import h5py
import numpy as np
import pytest

from env_data_mcp.sources.oco2 import (
    LICENSE_INFO,
    _get_download_url,
    _granule_date,
    _granule_id,
    _grid_params,
    _open_xco2_dataset,
    _parse_xco2_bbox,
    _parse_xco2_point,
    _point_to_idx,
    oco2_bbox_query,
    oco2_query,
)

# ---------------------------------------------------------------------------
# Synthetic HDF5 fixture helpers
# ---------------------------------------------------------------------------

_YAKIMA_LAT = 46.2531882
_YAKIMA_LON = -119.4768203

# OCO-2 L3 uses a 0.5° × 0.625° grid (360 rows × 576 cols)
_NROWS = 360
_NCOLS = 576

# A realistic XCO2 value in ppm
_XCO2_YAKIMA = 408.5


def _make_oco2_hdf5(
    xco2_value: float = _XCO2_YAKIMA,
    lat: float = _YAKIMA_LAT,
    lon: float = _YAKIMA_LON,
    nrows: int = _NROWS,
    ncols: int = _NCOLS,
    fill: float = -9999.0,
) -> bytes:
    """Return bytes of a minimal HDF5 file mimicking OCO-2 L3 structure.

    The XCO2 array is fill-valued everywhere except the pixel nearest
    to (lat, lon), which is set to xco2_value.
    """
    buf = io.BytesIO()
    lat_step = 180.0 / nrows
    lon_step = 360.0 / ncols
    lat_orig = -90.0 + lat_step / 2.0
    lon_orig = -180.0 + lon_step / 2.0
    i = int(round((lat - lat_orig) / lat_step))
    j = int(round((lon - lon_orig) / lon_step))
    i = max(0, min(nrows - 1, i))
    j = max(0, min(ncols - 1, j))

    data = np.full((nrows, ncols), fill, dtype=np.float32)
    data[i, j] = xco2_value
    prec = np.full((nrows, ncols), fill, dtype=np.float32)
    prec[i, j] = 0.5

    with h5py.File(buf, "w") as hf:
        grp = hf.require_group("HDFEOS/GRIDS/OCO-2 Level 3 Gridded XCO2/Data Fields")
        ds = grp.create_dataset("XCO2", data=data)
        ds.attrs["_FillValue"] = fill
        prec_ds = grp.create_dataset("XCO2PREC", data=prec)
        prec_ds.attrs["_FillValue"] = fill

    buf.seek(0)
    return buf.read()


def _make_cmr_granule(
    title: str = "oco2_LtCO2_190819_B10206r_230413082703s",
    time_start: str = "2019-08-19T00:00:00.000Z",
    download_url: str = "https://ges-disc.gsfc.nasa.gov/data/oco2_test.he5",
) -> dict:
    return {
        "title": title,
        "producer_granule_id": title,
        "time_start": time_start,
        "links": [
            {
                "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                "href": download_url,
            }
        ],
    }


# ---------------------------------------------------------------------------
# _grid_params
# ---------------------------------------------------------------------------


def test_grid_params_1deg():
    lo, lo2, ls, ls2 = _grid_params(180, 360)
    assert ls == pytest.approx(1.0)
    assert ls2 == pytest.approx(1.0)
    assert lo == pytest.approx(-89.5)
    assert lo2 == pytest.approx(-179.5)


def test_grid_params_half_deg():
    lo, lo2, ls, ls2 = _grid_params(360, 576)
    assert ls == pytest.approx(0.5)
    assert ls2 == pytest.approx(360.0 / 576)
    assert lo == pytest.approx(-89.75)


# ---------------------------------------------------------------------------
# _point_to_idx
# ---------------------------------------------------------------------------


def test_point_to_idx_yakima_in_range():
    lat_orig, lon_orig, lat_step, lon_step = _grid_params(_NROWS, _NCOLS)
    args = (lat_orig, lon_orig, lat_step, lon_step, _NROWS, _NCOLS)
    i, j = _point_to_idx(_YAKIMA_LAT, _YAKIMA_LON, *args)
    assert 0 <= i < _NROWS
    assert 0 <= j < _NCOLS


def test_point_to_idx_clamped_high():
    lat_orig, lon_orig, lat_step, lon_step = _grid_params(_NROWS, _NCOLS)
    i, j = _point_to_idx(91.0, 181.0, lat_orig, lon_orig, lat_step, lon_step, _NROWS, _NCOLS)
    assert i == _NROWS - 1
    assert j == _NCOLS - 1


def test_point_to_idx_clamped_low():
    lat_orig, lon_orig, lat_step, lon_step = _grid_params(_NROWS, _NCOLS)
    i, j = _point_to_idx(-91.0, -181.0, lat_orig, lon_orig, lat_step, lon_step, _NROWS, _NCOLS)
    assert i == 0
    assert j == 0


# ---------------------------------------------------------------------------
# _open_xco2_dataset
# ---------------------------------------------------------------------------


def test_open_xco2_dataset_finds_dataset():
    content = _make_oco2_hdf5()
    with h5py.File(io.BytesIO(content), "r") as hf:
        ds = _open_xco2_dataset(hf)
    assert ds is not None


def test_open_xco2_dataset_fallback():
    """Fallback: XCO2 stored at a non-standard path."""
    buf = io.BytesIO()
    with h5py.File(buf, "w") as hf:
        grp = hf.require_group("CUSTOM/PATH")
        grp.create_dataset("XCO2", data=np.ones((10, 20), dtype=np.float32))
    buf.seek(0)
    with h5py.File(buf, "r") as hf:
        ds = _open_xco2_dataset(hf)
    assert ds is not None


# ---------------------------------------------------------------------------
# _parse_xco2_point
# ---------------------------------------------------------------------------


def test_parse_xco2_point_returns_value():
    content = _make_oco2_hdf5(xco2_value=408.5)
    rec = _parse_xco2_point(content, _YAKIMA_LAT, _YAKIMA_LON, "2019-08-19", "oco2_test")
    assert rec is not None
    assert abs(rec["xco2"] - 408.5) < 0.5  # nearest-cell rounding
    assert rec["units"] == "ppm"
    assert rec["date"] == "2019-08-19"
    assert rec["granule_id"] == "oco2_test"


def test_parse_xco2_point_fill_returns_none():
    """A grid entirely filled with fill values should yield None."""
    buf = io.BytesIO()
    with h5py.File(buf, "w") as hf:
        grp = hf.require_group("HDFEOS/GRIDS/OCO-2 Level 3 Gridded XCO2/Data Fields")
        ds = grp.create_dataset("XCO2", data=np.full((10, 20), -9999.0, dtype=np.float32))
        ds.attrs["_FillValue"] = -9999.0
    buf.seek(0)
    rec = _parse_xco2_point(buf.read(), _YAKIMA_LAT, _YAKIMA_LON, "2019-08-19", "test")
    assert rec is None


def test_parse_xco2_point_includes_uncertainty():
    content = _make_oco2_hdf5(xco2_value=408.5)
    rec = _parse_xco2_point(content, _YAKIMA_LAT, _YAKIMA_LON, "2019-08-19", "test")
    assert rec is not None
    assert rec["xco2_uncertainty"] is not None
    assert rec["xco2_uncertainty"] > 0.0


# ---------------------------------------------------------------------------
# _parse_xco2_bbox
# ---------------------------------------------------------------------------


def test_parse_xco2_bbox_returns_records():
    content = _make_oco2_hdf5(xco2_value=408.5)
    records = _parse_xco2_bbox(
        content,
        min_lat=44.0,
        max_lat=48.0,
        min_lon=-122.0,
        max_lon=-117.0,
        date_str="2019-08-19",
        gid="test",
    )
    assert len(records) >= 1
    values = [r["xco2"] for r in records]
    assert any(abs(v - 408.5) < 0.5 for v in values)


def test_parse_xco2_bbox_all_fill_returns_empty():
    buf = io.BytesIO()
    with h5py.File(buf, "w") as hf:
        grp = hf.require_group("HDFEOS/GRIDS/OCO-2 Level 3 Gridded XCO2/Data Fields")
        ds = grp.create_dataset("XCO2", data=np.full((10, 20), -9999.0, dtype=np.float32))
        ds.attrs["_FillValue"] = -9999.0
    buf.seek(0)
    records = _parse_xco2_bbox(buf.read(), 0.0, 10.0, 0.0, 10.0, "2019-08-19", "test")
    assert records == []


# ---------------------------------------------------------------------------
# _granule_date, _granule_id
# ---------------------------------------------------------------------------


def test_granule_date_extracts_date():
    g = {"time_start": "2019-08-19T15:00:00.000Z"}
    assert _granule_date(g) == "2019-08-19"


def test_granule_id_uses_producer_id():
    g = {"producer_granule_id": "oco2_abc", "title": "other"}
    assert _granule_id(g) == "oco2_abc"


def test_granule_id_falls_back_to_title():
    g = {"title": "oco2_abc"}
    assert _granule_id(g) == "oco2_abc"


# ---------------------------------------------------------------------------
# _get_download_url
# ---------------------------------------------------------------------------


def test_get_download_url_prefers_opendap():
    g = {
        "links": [
            {
                "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                "href": "https://ges-disc.gsfc.nasa.gov/data.he5",
            },
            {
                "rel": "http://esipfed.org/ns/fedsearch/1.1/opendap#",
                "href": "https://opendap.earthdata.nasa.gov/data.he5",
            },
        ]
    }
    url = _get_download_url(g)
    assert url is not None
    assert "opendap" in url


def test_get_download_url_falls_back_to_data():
    g = {
        "links": [
            {
                "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                "href": "https://ges-disc.gsfc.nasa.gov/data.he5",
            },
        ]
    }
    url = _get_download_url(g)
    assert url is not None
    assert "data.he5" in url


def test_get_download_url_returns_none_when_no_links():
    assert _get_download_url({"links": []}) is None


# ---------------------------------------------------------------------------
# oco2_query — no token
# ---------------------------------------------------------------------------


def test_oco2_query_no_token_returns_auth_error(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    result = oco2_query(
        latitude=_YAKIMA_LAT,
        longitude=_YAKIMA_LON,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["auth_required"] is True
    assert result["_meta"]["auth_present"] is False
    assert "EARTHDATA_TOKEN" in result["_meta"]["error"]
    assert result["data"] == []


# ---------------------------------------------------------------------------
# oco2_query — successful mocked call
# ---------------------------------------------------------------------------

_MOD = "env_data_mcp.sources.oco2"


def test_oco2_query_success(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    content = _make_oco2_hdf5(xco2_value=408.5)
    granule = _make_cmr_granule()

    with (
        patch(f"{_MOD}._cmr_search", return_value=[granule]),
        patch(f"{_MOD}._fetch_granule_bytes", return_value=content),
    ):
        result = oco2_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
        )

    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is True
    assert result["_meta"]["auth_present"] is True
    assert result["_meta"]["source"] == "oco2"
    assert len(result["data"]) == 1
    assert abs(result["data"][0]["xco2"] - 408.5) < 0.5


def test_oco2_query_no_granules_returns_success_empty(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    with patch(f"{_MOD}._cmr_search", return_value=[]):
        result = oco2_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
        )
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] is not None


def test_oco2_query_expired_token_response(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "expired-token")
    with patch(
        f"{_MOD}._cmr_search",
        side_effect=ValueError("EarthData token rejected (HTTP 401)"),
    ):
        result = oco2_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["auth_present"] is False
    assert "HTTP 401" in result["_meta"]["error"]
    assert result["data"] == []


def test_oco2_query_meta_fields(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    content = _make_oco2_hdf5(xco2_value=408.5)
    granule = _make_cmr_granule()
    with (
        patch(f"{_MOD}._cmr_search", return_value=[granule]),
        patch(f"{_MOD}._fetch_granule_bytes", return_value=content),
    ):
        result = oco2_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            start_date="2019-08-19",
            end_date="2019-08-19",
        )
    meta = result["_meta"]
    assert meta["license"] == LICENSE_INFO["license"]
    assert meta["license_url"] == LICENSE_INFO["license_url"]
    assert "xco2" in meta["variable_info"]
    assert meta["latency_s"] >= 0
    assert meta["query_params"]["latitude"] == _YAKIMA_LAT


# ---------------------------------------------------------------------------
# oco2_bbox_query — no token
# ---------------------------------------------------------------------------


def test_oco2_bbox_query_no_token(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    result = oco2_bbox_query(
        min_lat=44.0,
        max_lat=48.0,
        min_lon=-122.0,
        max_lon=-117.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    assert result["_meta"]["auth_present"] is False


def test_oco2_bbox_query_success(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    content = _make_oco2_hdf5(xco2_value=408.5)
    granule = _make_cmr_granule()
    with (
        patch(f"{_MOD}._cmr_search", return_value=[granule]),
        patch(f"{_MOD}._fetch_granule_bytes", return_value=content),
    ):
        result = oco2_bbox_query(
            min_lat=44.0,
            max_lat=48.0,
            min_lon=-122.0,
            max_lon=-117.0,
            start_date="2019-08-19",
            end_date="2019-08-19",
        )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) >= 1


def test_oco2_bbox_query_echoes_clamped_bbox(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    with patch(f"{_MOD}._cmr_search", return_value=[]):
        result = oco2_bbox_query(
            min_lat=40.0,
            max_lat=48.0,
            min_lon=-125.0,
            max_lon=-115.0,
            start_date="2019-08-01",
            end_date="2019-08-31",
        )
    qp = result["_meta"]["query_params"]
    assert "min_lat" in qp
    assert "max_lat" in qp
