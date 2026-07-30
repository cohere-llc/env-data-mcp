"""Unit tests for the NASA POWER disk-backed variable cache.

The live-fetch path is exercised against an in-memory Zarr group with the
Zarr store cache patched to return it, so no S3 access is required.  The
disk-backed lookup is exercised against a temporary JSON file substituted
for the shipped ``variables.json`` via ``monkeypatch``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from env_data_mcp.sources.nasa_power import _var_cache
from env_data_mcp.sources.nasa_power._constants import DatasetType, TemporalResolution

from .conftest import _MOCK_MERRA2_GROUP, _MOCK_MERRA2_STORE, _MOCK_SYN1DEG_STORE

# The autouse _reset_caches fixture in conftest.py pre-seeds the module cache
# from the mock groups; the tests below explicitly clear it where the cleaner
# state is required.


# ---------------------------------------------------------------------------
# _variable_info_from_group
# ---------------------------------------------------------------------------


def test_variable_info_from_group_extracts_units_and_description():
    info = _var_cache._variable_info_from_group(_MOCK_MERRA2_GROUP)
    assert "T2M" in info
    assert info["T2M"]["units"] == "C"
    assert info["T2M"]["description"] == "Temperature at 2 Meters"


def test_variable_info_from_group_skips_coordinates():
    info = _var_cache._variable_info_from_group(_MOCK_MERRA2_GROUP)
    for key in ("lat", "lon", "time"):
        assert key not in info


# ---------------------------------------------------------------------------
# _fetch_variable_info_live (via patched open_store)
# ---------------------------------------------------------------------------


def test_fetch_variable_info_live_usesopen_store():
    with patch(
        "env_data_mcp.sources.nasa_power._var_cache.open_store",
        return_value=_MOCK_MERRA2_STORE,
    ):
        info = _var_cache._fetch_variable_info_live(DatasetType.MERRA2, TemporalResolution.DAILY)
    assert "T2M" in info


def test_fetch_all_variable_info_live_covers_every_combo():
    def _pick(ds: DatasetType, _tr: TemporalResolution):
        return _MOCK_MERRA2_STORE if ds is DatasetType.MERRA2 else _MOCK_SYN1DEG_STORE

    with patch("env_data_mcp.sources.nasa_power._var_cache.open_store", side_effect=_pick):
        result = _var_cache._fetch_all_variable_info_live()

    assert set(result) == {ds.value for ds in DatasetType}
    for ds in DatasetType:
        assert set(result[ds.value]) == {tr.value for tr in TemporalResolution}
    assert "T2M" in result[DatasetType.MERRA2.value][TemporalResolution.DAILY.value]
    assert "ALLSKY_SFC_SW_DWN" in result[DatasetType.SYN1DEG.value][TemporalResolution.DAILY.value]


# ---------------------------------------------------------------------------
# _get_variable_info (disk-backed)
# ---------------------------------------------------------------------------


def _write_cache_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "variables.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_get_variable_info_reads_from_disk(monkeypatch, tmp_path):
    payload = {
        DatasetType.MERRA2.value: {
            TemporalResolution.DAILY.value: {
                "FOO": {"description": "fooness", "units": "K"},
            }
        }
    }
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, payload))
    _var_cache._VARIABLE_INFO_CACHE.clear()

    result = _var_cache.get_variable_info(DatasetType.MERRA2, TemporalResolution.DAILY)

    assert result == {"FOO": {"description": "fooness", "units": "K"}}


def test_get_variable_info_caches_across_calls(monkeypatch, tmp_path):
    """After the first call the on-disk file is not re-read."""
    payload = {
        DatasetType.MERRA2.value: {
            TemporalResolution.DAILY.value: {
                "FOO": {"description": "fooness", "units": "K"},
            }
        }
    }
    path = _write_cache_file(tmp_path, payload)
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", path)
    _var_cache._VARIABLE_INFO_CACHE.clear()

    first = _var_cache.get_variable_info(DatasetType.MERRA2, TemporalResolution.DAILY)
    path.unlink()  # subsequent calls must not touch disk
    second = _var_cache.get_variable_info(DatasetType.MERRA2, TemporalResolution.DAILY)

    assert first is second


def test_get_variable_info_raises_when_combo_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, {}))
    _var_cache._VARIABLE_INFO_CACHE.clear()

    with pytest.raises(KeyError, match="No cached variable info"):
        _var_cache.get_variable_info(DatasetType.MERRA2, TemporalResolution.DAILY)


# ---------------------------------------------------------------------------
# Shipped variables.json
# ---------------------------------------------------------------------------


def test_shipped_variables_json_is_wellformed():
    """The committed cache loads and covers every (dataset, resolution) pair."""
    _var_cache._VARIABLE_INFO_CACHE.clear()
    data = _var_cache._load_all_variable_info_from_disk()
    for ds in DatasetType:
        assert ds.value in data, f"Missing dataset {ds.value} in shipped cache"
        ds_block = data[ds.value]
        for tr in TemporalResolution:
            assert tr.value in ds_block, f"Missing {ds.value}/{tr.value} in shipped cache"
            assert ds_block[tr.value], f"Empty variable list for {ds.value}/{tr.value}"
            for var_name, info in ds_block[tr.value].items():
                assert "description" in info, (
                    f"{ds.value}/{tr.value}.{var_name} missing description"
                )
                assert "units" in info, f"{ds.value}/{tr.value}.{var_name} missing units"


def test_shipped_variables_json_covers_default_variables():
    """Every default variable used by the NASA POWER tools is in the shipped cache."""
    from env_data_mcp.sources.nasa_power._constants import (
        DEFAULT_MERRA2_VARIABLES,
        DEFAULT_SYN1DEG_VARIABLES,
    )

    _var_cache._VARIABLE_INFO_CACHE.clear()
    data = _var_cache._load_all_variable_info_from_disk()
    merra2_daily = data[DatasetType.MERRA2.value][TemporalResolution.DAILY.value]
    syn1deg_daily = data[DatasetType.SYN1DEG.value][TemporalResolution.DAILY.value]

    missing_merra2 = [v for v in DEFAULT_MERRA2_VARIABLES if v not in merra2_daily]
    missing_syn1deg = [v for v in DEFAULT_SYN1DEG_VARIABLES if v not in syn1deg_daily]

    assert not missing_merra2, f"Default MERRA-2 vars missing: {missing_merra2}"
    assert not missing_syn1deg, f"Default SYN1deg vars missing: {missing_syn1deg}"
