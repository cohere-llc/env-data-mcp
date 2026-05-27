"""Unit tests for env_data_mcp.sources.nasa_power._client."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pandas as pd

import env_data_mcp.sources.nasa_power._client as _client_mod
from env_data_mcp.sources.nasa_power._client import (
    ZarrStoreCache,
    _get_coordinates,
    _get_variable_info,
    _open_store,
)
from env_data_mcp.sources.nasa_power.constants import DatasetType, TemporalResolution

from .conftest import (
    _MOCK_HOURLY_D_STORE,
    _MOCK_HOURLY_H_STORE,
    _MOCK_MERRA2_GROUP,
    _MOCK_MERRA2_STORE,
    _MOCK_SYN1DEG_STORE,
)

# ---------------------------------------------------------------------------
# _open_store
# ---------------------------------------------------------------------------


def test_open_store_import_error_fallback():
    """When zarr.experimental.cache_store is unavailable _open_store uses the raw store."""
    from unittest.mock import MagicMock

    mock_source = MagicMock()
    with (
        patch("env_data_mcp.sources.nasa_power._client.FsspecStore") as mock_fsspec,
        patch("zarr.open_group", return_value=_MOCK_MERRA2_GROUP),
        patch.dict(sys.modules, {"zarr.experimental.cache_store": None}),
    ):
        mock_fsspec.from_url.return_value = mock_source
        _client_mod._zarr_cache.clear()
        result = _open_store(DatasetType.MERRA2, TemporalResolution.DAILY)
    assert isinstance(result, ZarrStoreCache)


# ---------------------------------------------------------------------------
# _get_coordinates
# ---------------------------------------------------------------------------


def test_get_coordinates_shape():
    lats, lons, times = _get_coordinates(_MOCK_MERRA2_STORE)
    assert len(lats) == 3
    assert len(lons) == 3
    assert len(times) == 5


def test_get_coordinates_first_date():
    _, _, times = _get_coordinates(_MOCK_MERRA2_STORE)
    assert times[0] == pd.Timestamp("2019-08-17")


def test_get_coordinates_last_date():
    _, _, times = _get_coordinates(_MOCK_MERRA2_STORE)
    assert times[-1] == pd.Timestamp("2019-08-21")


def test_get_coordinates_cached_is_same_object():
    lats1, lons1, times1 = _get_coordinates(_MOCK_MERRA2_STORE)
    lats2, lons2, times2 = _get_coordinates(_MOCK_MERRA2_STORE)
    assert lats1 is lats2
    assert times1 is times2


# ---------------------------------------------------------------------------
# _get_variable_info
# ---------------------------------------------------------------------------


def test_get_variable_info_returns_known_keys():
    info = _get_variable_info(_MOCK_MERRA2_STORE)
    assert "T2M" in info
    assert "PRECTOTCORR" in info


def test_get_variable_info_has_units_and_description():
    info = _get_variable_info(_MOCK_MERRA2_STORE)
    assert "units" in info["T2M"]
    assert "description" in info["T2M"]


def test_get_variable_info_cached():
    info1 = _get_variable_info(_MOCK_MERRA2_STORE)
    info2 = _get_variable_info(_MOCK_MERRA2_STORE)
    assert info1 is info2


def test_get_variable_info_syn1deg():
    info = _get_variable_info(_MOCK_SYN1DEG_STORE)
    assert "ALLSKY_SFC_SW_DWN" in info


# ---------------------------------------------------------------------------
# Hourly time decoding (_get_coordinates with hourly stores)
# ---------------------------------------------------------------------------


class TestHourlyTimeDecode:
    """_get_coordinates must produce 24 distinct hourly timestamps for both encodings."""

    def test_hours_since_returns_24_times(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_H_STORE)
        assert len(times) == 24

    def test_hours_since_first_timestamp(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_H_STORE)
        assert times[0] == pd.Timestamp("2019-08-19 00:00:00")

    def test_hours_since_last_timestamp(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_H_STORE)
        assert times[-1] == pd.Timestamp("2019-08-19 23:00:00")

    def test_hours_since_all_distinct(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_H_STORE)
        assert len(set(times)) == 24

    def test_fractional_days_returns_24_times(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_D_STORE)
        assert len(times) == 24

    def test_fractional_days_first_timestamp(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_D_STORE)
        assert times[0] == pd.Timestamp("2019-08-19 00:00:00")

    def test_fractional_days_last_timestamp(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_D_STORE)
        # fractional-day encoding has ~100ns float imprecision; check within 1 ms
        assert abs(times[-1] - pd.Timestamp("2019-08-19 23:00:00")) < pd.Timedelta("1ms")

    def test_fractional_days_all_distinct(self):
        _, _, times = _get_coordinates(_MOCK_HOURLY_D_STORE)
        assert len(set(times)) == 24
