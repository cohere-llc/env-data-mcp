"""Shared fixtures and mock endpoints for NASA EMIT unit tests."""

from __future__ import annotations

import io
import re

import h5py
import numpy as np
import pytest

from env_data_mcp.sources.nasa_emit._constants import CMR_GANULES_URL, GROUP_VARS, QUERY_ARGS
from env_data_mcp.sources.nasa_emit._query import _group_var_expr

_LAT = 46.2531882
_LON = -119.4768203
_TOKEN = "test-earthdata-token"

_GRANULE_ID = "emit20230815t000000_l2b_min_001"
_OPENDAP_BASE_URL = "https://opendap.earthdata.nasa.gov/emit/l2b/emit20230815"
# Resolved data-fetch base: _parse_granule_url() always appends ".nc4" to the CMR href.
_NC4_URL = f"{_OPENDAP_BASE_URL}.nc4"

_MINERAL_NAMES = ["Calcite", "Kaolinite"]
_FILL_MINERAL_ID = -9999

# 2x2 pixel grid; the point-query coordinates sit exactly on the (0, 0) cell
# so the nearest-pixel search is deterministic.
_LATS = np.array([[_LAT, _LAT], [_LAT + 0.01, _LAT + 0.01]])
_LONS = np.array([[_LON, _LON + 0.01], [_LON, _LON + 0.01]])

# Point-query group values for pixel (0, 0): both groups are real detections.
_POINT_GROUP_1_ID = np.array([[0]])
_POINT_GROUP_1_BD = np.array([[0.3]])
_POINT_GROUP_2_ID = np.array([[1]])
_POINT_GROUP_2_BD = np.array([[0.15]])

# Bbox-query group values for the 2x2 grid, one pixel per position:
#   (0,0): both groups real   (0,1): group_1 non-detection (id=0, depth=0.0)
#   (1,0): group_1 fill value (1,1): both groups non-detections -> dropped
_BBOX_GROUP_1_ID = np.array([[0, 0], [_FILL_MINERAL_ID, 0]])
_BBOX_GROUP_1_BD = np.array([[0.3, 0.0], [0.0, 0.0]])
_BBOX_GROUP_2_ID = np.array([[1, 1], [1, 0]])
_BBOX_GROUP_2_BD = np.array([[0.15, 0.2], [0.4, 0.0]])

_CMR_RESPONSE = {
    "feed": {
        "entry": [
            {
                "producer_granule_id": _GRANULE_ID,
                "title": _GRANULE_ID,
                "time_start": "2023-08-15T12:00:00.000Z",
                "links": [
                    {
                        "rel": "http://esipfed.org/ns/fedsearch/1.1/opendap#",
                        "href": f"{_OPENDAP_BASE_URL}.dmr",
                    }
                ],
            }
        ]
    }
}

_EMPTY_CMR_RESPONSE = {"feed": {"entry": []}}


def _make_lat_lon_nc4(
    lats: np.ndarray = _LATS,
    lons: np.ndarray = _LONS,
    names: list[str] = _MINERAL_NAMES,
) -> bytes:
    """Return HDF5 bytes shaped like the real (flattened-group) Hyrax response.

    Lat/lon and the mineral name table come back as top-level datasets with an
    underscore-group prefix, and mineral names as a fixed-width char matrix
    (one single-byte cell per character), not a vlen-string array.
    """
    buf = io.BytesIO()
    with h5py.File(buf, "w") as hf:
        hf.create_dataset("_location_lat", data=lats)
        hf.create_dataset("_location_lon", data=lons)
        width = max(len(n) for n in names) + 1
        arr = np.zeros((len(names), width), dtype="S1")
        for i, name in enumerate(names):
            for j, ch in enumerate(name.encode("utf-8")):
                arr[i, j] = bytes([ch])
        hf.create_dataset("_mineral_metadata_name", data=arr)
    buf.seek(0)
    return buf.read()


def _make_group_nc4(
    group_1_id: np.ndarray,
    group_1_band_depth: np.ndarray,
    group_2_id: np.ndarray,
    group_2_band_depth: np.ndarray,
) -> bytes:
    """Return HDF5 bytes containing the group_1/group_2 mineral_id + band_depth arrays."""
    buf = io.BytesIO()
    with h5py.File(buf, "w") as hf:
        hf.create_dataset(GROUP_VARS[0], data=group_1_id)
        hf.create_dataset(GROUP_VARS[1], data=group_1_band_depth)
        hf.create_dataset(GROUP_VARS[2], data=group_2_id)
        hf.create_dataset(GROUP_VARS[3], data=group_2_band_depth)
    buf.seek(0)
    return buf.read()


@pytest.fixture
def _set_token(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", _TOKEN)


@pytest.fixture
def _unset_token(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)


@pytest.fixture
def _cmr_mock(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(rf"^{re.escape(CMR_GANULES_URL)}.*"),
        json=_CMR_RESPONSE,
    )


@pytest.fixture
def _point_query_mock(httpx_mock, _cmr_mock):
    httpx_mock.add_response(
        url=f"{_NC4_URL}?{QUERY_ARGS}",
        content=_make_lat_lon_nc4(),
    )
    httpx_mock.add_response(
        url=f"{_NC4_URL}?{_group_var_expr(0, 0, 0, 0)}",
        content=_make_group_nc4(
            _POINT_GROUP_1_ID, _POINT_GROUP_1_BD, _POINT_GROUP_2_ID, _POINT_GROUP_2_BD
        ),
    )


@pytest.fixture
def _bbox_query_mock(httpx_mock, _cmr_mock):
    httpx_mock.add_response(
        url=f"{_NC4_URL}?{QUERY_ARGS}",
        content=_make_lat_lon_nc4(),
    )
    httpx_mock.add_response(
        url=f"{_NC4_URL}?{_group_var_expr(0, 1, 0, 1)}",
        content=_make_group_nc4(
            _BBOX_GROUP_1_ID, _BBOX_GROUP_1_BD, _BBOX_GROUP_2_ID, _BBOX_GROUP_2_BD
        ),
    )
