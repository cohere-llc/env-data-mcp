"""Unit tests for the EMIT L2B Minerals source adapter.

All HTTP and HDF5 I/O is mocked; no network access required.

EMIT OPeNDAP workflow per granule:
  1. GET {opendap_url}.nc4?/location/lat,/location/lon,/mineral_metadata/mineral_name
     → HDF5 bytes containing lat/lon arrays + mineral name list
  2. GET {opendap_url}.nc4?/spectral_abundance[i:i][j:j][0:N-1]
     → HDF5 bytes containing a 1×1×N abundance array
"""

from __future__ import annotations

import io
from unittest.mock import patch

import h5py
import numpy as np
import pytest

from env_data_mcp.sources.emit import (
    LICENSE_INFO,
    _decode_mineral_names,
    _extract_pixels_in_bbox,
    _fetch_opendap_nc4,
    _find_nearest_pixel,
    _get_dataset,
    _get_opendap_url,
    _granule_date,
    _granule_id,
    emit_bbox_query,
    emit_query,
)

# ---------------------------------------------------------------------------
# Representative query coords
# ---------------------------------------------------------------------------

_LAT = 36.1
_LON = -115.2  # Nevada desert — should have interesting mineralogy

_MINERAL_NAMES = ["Calcite", "Kaolinite", "Montmorillonite"]
_ABUNDANCES = np.array([0.25, 0.10, 0.005], dtype=np.float32)  # 3rd is below threshold

# ---------------------------------------------------------------------------
# Synthetic HDF5 fixtures
# ---------------------------------------------------------------------------

# Small 4×5 scene for fast tests
_NROWS, _NCOLS = 4, 5

# Build a simple lat/lon grid centred at (_LAT, _LON) for testing
_LATS = np.array(
    [[_LAT + 0.1 * (r - 1) for _ in range(_NCOLS)] for r in range(_NROWS)],
    dtype=np.float32,
)
_LONS = np.array(
    [[_LON + 0.1 * (c - 2) for c in range(_NCOLS)] for _ in range(_NROWS)],
    dtype=np.float32,
)


def _make_lat_lon_nc4(lats: np.ndarray = _LATS, lons: np.ndarray = _LONS) -> bytes:
    """Return bytes of a minimal HDF5 file containing lat, lon, and mineral names."""
    buf = io.BytesIO()
    with h5py.File(buf, "w") as hf:
        loc = hf.require_group("location")
        loc.create_dataset("lat", data=lats)
        loc.create_dataset("lon", data=lons)
        mm = hf.require_group("mineral_metadata")
        dt = h5py.special_dtype(vlen=str)
        ds = mm.create_dataset("mineral_name", (len(_MINERAL_NAMES),), dtype=dt)
        for k, name in enumerate(_MINERAL_NAMES):
            ds[k] = name
    buf.seek(0)
    return buf.read()


def _make_abundance_nc4(
    abundances: np.ndarray = _ABUNDANCES,
    i: int = 0,
    j: int = 0,
) -> bytes:
    """Return bytes of a minimal HDF5 file containing a 1×1×N spectral_abundance array."""
    buf = io.BytesIO()
    n = len(abundances)
    data = abundances.reshape(1, 1, n)
    with h5py.File(buf, "w") as hf:
        hf.create_dataset("spectral_abundance", data=data)
    buf.seek(0)
    return buf.read()


def _make_cmr_granule(
    gid: str = "emit20231015t120000_l2b_min_v001",
    time_start: str = "2023-10-15T12:00:00.000Z",
    opendap_url: str = "https://opendap.earthdata.nasa.gov/emit/l2b/emit20231015.nc",
) -> dict:
    return {
        "producer_granule_id": gid,
        "title": gid,
        "time_start": time_start,
        "links": [
            {
                "rel": "http://esipfed.org/ns/fedsearch/1.1/opendap#",
                "href": opendap_url,
            }
        ],
    }


# ---------------------------------------------------------------------------
# _get_dataset
# ---------------------------------------------------------------------------


def test_get_dataset_primary_path():
    content = _make_lat_lon_nc4()
    with h5py.File(io.BytesIO(content), "r") as hf:
        ds = _get_dataset(hf, "/location/lat", "location/lat", "lat")
    assert ds is not None


def test_get_dataset_fallback_path():
    buf = io.BytesIO()
    with h5py.File(buf, "w") as hf:
        hf.create_dataset("lat", data=np.ones((3, 4)))
    buf.seek(0)
    with h5py.File(buf, "r") as hf:
        ds = _get_dataset(hf, "/location/lat", "lat")
    assert ds is not None


def test_get_dataset_returns_none_when_missing():
    buf = io.BytesIO()
    with h5py.File(buf, "w") as hf:
        hf.create_dataset("something_else", data=np.ones((3,)))
    buf.seek(0)
    with h5py.File(buf, "r") as hf:
        ds = _get_dataset(hf, "/location/lat", "location/lat", "lat")
    assert ds is None


# ---------------------------------------------------------------------------
# _decode_mineral_names
# ---------------------------------------------------------------------------


def test_decode_mineral_names():
    content = _make_lat_lon_nc4()
    with h5py.File(io.BytesIO(content), "r") as hf:
        ds = hf["mineral_metadata/mineral_name"]
        names = _decode_mineral_names(ds)
    assert names == _MINERAL_NAMES


def test_decode_mineral_names_bytes():
    """Mineral names stored as byte strings (older HDF5 files)."""
    buf = io.BytesIO()
    with h5py.File(buf, "w") as hf:
        arr = np.array([b"Calcite", b"Kaolinite"], dtype="S20")
        hf.create_dataset("mineral_name", data=arr)
    buf.seek(0)
    with h5py.File(buf, "r") as hf:
        ds = hf["mineral_name"]
        names = _decode_mineral_names(ds)
    assert names == ["Calcite", "Kaolinite"]


# ---------------------------------------------------------------------------
# _find_nearest_pixel
# ---------------------------------------------------------------------------


def test_find_nearest_pixel_exact_match():
    px = _find_nearest_pixel(_LATS, _LONS, float(_LATS[1, 2]), float(_LONS[1, 2]))
    assert px == (1, 2)


def test_find_nearest_pixel_approx_match():
    px = _find_nearest_pixel(_LATS, _LONS, _LAT + 0.01, _LON - 0.01)
    assert px is not None
    i, j = px
    assert 0 <= i < _NROWS
    assert 0 <= j < _NCOLS


def test_find_nearest_pixel_too_far_returns_none():
    # Query point 50° away — well beyond default 0.1° threshold
    px = _find_nearest_pixel(_LATS, _LONS, _LAT + 50.0, _LON)
    assert px is None


# ---------------------------------------------------------------------------
# _extract_pixels_in_bbox
# ---------------------------------------------------------------------------


def test_extract_pixels_in_bbox_all_inside():
    # Bbox that covers the whole mock scene
    min_lat = float(_LATS.min()) - 1.0
    max_lat = float(_LATS.max()) + 1.0
    min_lon = float(_LONS.min()) - 1.0
    max_lon = float(_LONS.max()) + 1.0
    pixels = _extract_pixels_in_bbox(_LATS, _LONS, min_lat, max_lat, min_lon, max_lon)
    assert len(pixels) == _NROWS * _NCOLS


def test_extract_pixels_in_bbox_partial():
    # Only the top row should match
    min_lat = float(_LATS[-1, 0]) - 0.001
    max_lat = float(_LATS[-1, 0]) + 0.001
    pixels = _extract_pixels_in_bbox(
        _LATS, _LONS, min_lat, max_lat, float(_LONS.min()) - 1, float(_LONS.max()) + 1
    )
    assert len(pixels) == _NCOLS


def test_extract_pixels_in_bbox_empty():
    pixels = _extract_pixels_in_bbox(_LATS, _LONS, 80.0, 90.0, 0.0, 10.0)
    assert pixels == []


# ---------------------------------------------------------------------------
# CMR helper functions
# ---------------------------------------------------------------------------


def test_granule_date_extracts_date():
    g = {"time_start": "2023-10-15T12:00:00.000Z"}
    assert _granule_date(g) == "2023-10-15"


def test_granule_id_uses_producer_id():
    g = {"producer_granule_id": "emit_abc", "title": "other"}
    assert _granule_id(g) == "emit_abc"


def test_granule_id_falls_back_to_title():
    g = {"title": "emit_abc"}
    assert _granule_id(g) == "emit_abc"


def test_get_opendap_url_found():
    g = _make_cmr_granule()
    url = _get_opendap_url(g)
    assert url is not None
    assert "opendap" in url


def test_get_opendap_url_returns_none_when_absent():
    g = {
        "links": [
            {
                "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                "href": "https://example.com/file.nc",
            }
        ]
    }
    assert _get_opendap_url(g) is None


# ---------------------------------------------------------------------------
# emit_query — no token
# ---------------------------------------------------------------------------


def test_emit_query_no_token(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    result = emit_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2023-10-01",
        end_date="2023-10-31",
        max_runtime_s=999,
    )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["auth_required"] is True
    assert result["_meta"]["auth_present"] is False
    assert "EARTHDATA_TOKEN" in result["_meta"]["error"]
    assert result["data"] == []


# ---------------------------------------------------------------------------
# emit_query — successful mocked call
# ---------------------------------------------------------------------------

_MOD = "env_data_mcp.sources.emit"
_OPENDAP_BASE_URL = "https://opendap.earthdata.nasa.gov/emit/l2b/emit20231015.nc"


def test_emit_query_success(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    granule = _make_cmr_granule(opendap_url=_OPENDAP_BASE_URL)
    lat_lon_bytes = _make_lat_lon_nc4()
    abund_bytes = _make_abundance_nc4()

    with (
        patch(f"{_MOD}._cmr_search", return_value=[granule]),
        patch(f"{_MOD}._fetch_opendap_nc4", side_effect=[lat_lon_bytes, abund_bytes]),
    ):
        result = emit_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2023-10-01",
            end_date="2023-10-31",
            max_runtime_s=999,
        )

    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is True
    assert result["_meta"]["auth_present"] is True
    assert result["_meta"]["source"] == "emit"
    # Calcite (0.25) and Kaolinite (0.10) pass; Montmorillonite (0.005) below threshold
    assert len(result["data"]) == 2
    names = {r["mineral_name"] for r in result["data"]}
    assert "Calcite" in names
    assert "Kaolinite" in names
    assert "Montmorillonite" not in names


def test_emit_query_abundance_threshold(monkeypatch):
    """Records with abundance below threshold must be filtered out."""
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    granule = _make_cmr_granule(opendap_url=_OPENDAP_BASE_URL)
    low_abundances = np.array([0.001, 0.002, 0.003], dtype=np.float32)
    abund_bytes = _make_abundance_nc4(abundances=low_abundances)

    with (
        patch(f"{_MOD}._cmr_search", return_value=[granule]),
        patch(f"{_MOD}._fetch_opendap_nc4", side_effect=[_make_lat_lon_nc4(), abund_bytes]),
    ):
        result = emit_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2023-10-01",
            end_date="2023-10-31",
            max_runtime_s=999,
        )
    assert result["_meta"]["success"] is True
    assert result["data"] == []


def test_emit_query_no_granules(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    with patch(f"{_MOD}._cmr_search", return_value=[]):
        result = emit_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2023-10-01",
            end_date="2023-10-31",
            max_runtime_s=999,
        )
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] is not None


def test_emit_query_expired_token_opendap(monkeypatch):
    """401 from OPeNDAP raises ValueError → success=False, auth_present=True."""
    monkeypatch.setenv("EARTHDATA_TOKEN", "expired-token")
    granule = _make_cmr_granule(opendap_url=_OPENDAP_BASE_URL)

    with (
        patch(f"{_MOD}._cmr_search", return_value=[granule]),
        patch(
            f"{_MOD}._fetch_opendap_nc4",
            side_effect=ValueError("EarthData token rejected (HTTP 401)"),
        ),
    ):
        result = emit_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2023-10-01",
            end_date="2023-10-31",
            max_runtime_s=999,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["auth_present"] is True


def test_emit_query_meta_fields(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    granule = _make_cmr_granule(opendap_url=_OPENDAP_BASE_URL)
    with (
        patch(f"{_MOD}._cmr_search", return_value=[granule]),
        patch(
            f"{_MOD}._fetch_opendap_nc4",
            side_effect=[_make_lat_lon_nc4(), _make_abundance_nc4()],
        ),
    ):
        result = emit_query(
            latitude=_LAT,
            longitude=_LON,
            start_date="2023-10-01",
            end_date="2023-10-31",
            max_runtime_s=999,
        )
    meta = result["_meta"]
    assert meta["license"] == LICENSE_INFO["license"]
    assert meta["license_url"] == LICENSE_INFO["license_url"]
    assert meta["latency_s"] >= 0
    assert meta["query_params"]["latitude"] == _LAT


# ---------------------------------------------------------------------------
# emit_bbox_query — no token
# ---------------------------------------------------------------------------


def _make_bbox_abundance_nc4(
    nrows: int = _NROWS,
    ncols: int = _NCOLS,
    abundances: np.ndarray = _ABUNDANCES,
) -> bytes:
    """Return bytes of an HDF5 file with spectral_abundance shape (nrows, ncols, N)."""
    buf = io.BytesIO()
    n = len(abundances)
    # Tile the per-pixel abundances across all pixels in the rectangular slice.
    data = np.tile(abundances, (nrows, ncols, 1)).reshape(nrows, ncols, n)
    with h5py.File(buf, "w") as hf:
        hf.create_dataset("spectral_abundance", data=data)
    buf.seek(0)
    return buf.read()


def test_emit_bbox_query_no_token(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    result = emit_bbox_query(
        min_lat=35.0,
        max_lat=37.0,
        min_lon=-116.0,
        max_lon=-114.0,
        start_date="2023-10-01",
        end_date="2023-10-31",
        max_runtime_s=999,
    )
    assert result["_meta"]["auth_present"] is False


def test_emit_bbox_query_success(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    granule = _make_cmr_granule(opendap_url=_OPENDAP_BASE_URL)
    n_pixels = _NROWS * _NCOLS
    # Batch fetch: 2 OPeNDAP requests per granule (lat/lon + rectangular slice)
    opendap_side_effects = [_make_lat_lon_nc4(), _make_bbox_abundance_nc4()]

    with (
        patch(f"{_MOD}._cmr_search", return_value=[granule]),
        patch(f"{_MOD}._fetch_opendap_nc4", side_effect=opendap_side_effects),
    ):
        result = emit_bbox_query(
            min_lat=float(_LATS.min()) - 0.5,
            max_lat=float(_LATS.max()) + 0.5,
            min_lon=float(_LONS.min()) - 0.5,
            max_lon=float(_LONS.max()) + 0.5,
            start_date="2023-10-01",
            end_date="2023-10-31",
            max_runtime_s=999,
        )
    assert result["_meta"]["success"] is True
    # Each pixel yields 2 records (Calcite + Kaolinite above threshold)
    assert len(result["data"]) == n_pixels * 2


def test_emit_bbox_query_echoes_clamped_bbox(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    with patch(f"{_MOD}._cmr_search", return_value=[]):
        result = emit_bbox_query(
            min_lat=35.0,
            max_lat=37.0,
            min_lon=-116.0,
            max_lon=-114.0,
            start_date="2023-10-01",
            end_date="2023-10-31",
            max_runtime_s=999,
        )
    qp = result["_meta"]["query_params"]
    assert "min_lat" in qp
    assert "max_lat" in qp


# ---------------------------------------------------------------------------
# _fetch_opendap_nc4 — 401 raises ValueError (lines 112-127)
# ---------------------------------------------------------------------------


def test_fetch_opendap_nc4_401_raises():
    from unittest.mock import MagicMock, patch

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with (
        patch("env_data_mcp.sources.emit.httpx.get", return_value=mock_resp),
        pytest.raises(ValueError, match="HTTP 401"),
    ):
        _fetch_opendap_nc4(
            "https://opendap.earthdata.nasa.gov/emit/test",
            "/location/lat",
            "bad-token",
        )


# ---------------------------------------------------------------------------
# emit_bbox_query — expired token (lines 591-593)
# ---------------------------------------------------------------------------


def test_emit_bbox_query_expired_token(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "expired")
    granule = _make_cmr_granule(opendap_url=_OPENDAP_BASE_URL)
    with (
        patch(f"{_MOD}._cmr_search", return_value=[granule]),
        patch(
            f"{_MOD}._fetch_opendap_nc4",
            side_effect=ValueError("EarthData token rejected (HTTP 401)"),
        ),
    ):
        result = emit_bbox_query(
            min_lat=35.0,
            max_lat=37.0,
            min_lon=-116.0,
            max_lon=-114.0,
            start_date="2023-10-01",
            end_date="2023-10-31",
            max_runtime_s=999,
        )
    assert result["_meta"]["success"] is False
    assert result["_meta"]["auth_present"] is True
    assert "HTTP 401" in result["_meta"]["error"]
