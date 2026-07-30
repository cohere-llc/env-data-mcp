"""On-disk variable cache for the NASA POWER adapter.

The MCP server serves ``nasa_power_*_available_variables`` and populates the
``variable_info`` block for query responses from the committed
:file:`variables.json` shipped alongside this module, never from the Zarr
stores.  The live-fetch path is used only by the refresh script and its drift
integration test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import zarr

from env_data_mcp.helpers import load_json_cache
from env_data_mcp.scripts.refresh_variable_caches import VariableCacheEntry, register

from ._client import open_store
from ._constants import DatasetType, TemporalResolution

_VARIABLES_PATH = Path(__file__).parent / "variables.json"

# Session-level cache keyed by (DatasetType, TemporalResolution); populated
# lazily on the first _get_variable_info call from the on-disk JSON.
_VARIABLE_INFO_CACHE: dict[tuple[DatasetType, TemporalResolution], dict[str, dict[str, str]]] = {}

# Zarr coordinate arrays are not variables; skip them during introspection.
_COORDINATE_KEYS = frozenset({"lat", "lon", "time"})


# ---------------------------------------------------------------------------
# Introspection helper (used by live discovery and by test seeds)
# ---------------------------------------------------------------------------


def _variable_info_from_group(group: zarr.Group) -> dict[str, dict[str, str]]:
    """Extract ``{name: {description, units}}`` for every data variable in *group*."""
    info: dict[str, dict[str, str]] = {}
    for var in group.array_keys():
        if var in _COORDINATE_KEYS:
            continue
        arr = group[var]
        info[var] = {
            "description": str(arr.attrs.get("long_name", "")),
            "units": str(arr.attrs.get("units", "")),
        }
    return info


# ---------------------------------------------------------------------------
# Live discovery (used by the refresh script only)
# ---------------------------------------------------------------------------


def _fetch_variable_info_live(
    dataset_type: DatasetType,
    temporal_resolution: TemporalResolution,
) -> dict[str, dict[str, str]]:
    """Discover variables for one (dataset, resolution) by opening its Zarr store."""
    store = open_store(dataset_type, temporal_resolution)
    return _variable_info_from_group(store._group)


def _fetch_all_variable_info_live() -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    """Fetch variable info for every NASA POWER (dataset, resolution) pair.

    Returns a JSON-serialisable
    ``{dataset_value: {resolution_value: {variable: {...}}}}`` dict suitable
    for writing to :data:`_VARIABLES_PATH`.
    """
    return {
        ds.value: {tr.value: _fetch_variable_info_live(ds, tr) for tr in TemporalResolution}
        for ds in DatasetType
    }


# ---------------------------------------------------------------------------
# Disk-backed lookup (used by the MCP server runtime)
# ---------------------------------------------------------------------------


def _load_all_variable_info_from_disk() -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    """Return the on-disk cache as a JSON-shaped dict."""
    data: Any = load_json_cache(_VARIABLES_PATH)
    return data


def get_variable_info(
    dataset_type: DatasetType,
    temporal_resolution: TemporalResolution,
) -> dict[str, dict[str, str]]:
    """Return cached variable info for the given (dataset, resolution) pair."""
    key = (dataset_type, temporal_resolution)
    if key in _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE[key]
    all_info = _load_all_variable_info_from_disk()
    for ds in DatasetType:
        ds_block = all_info.get(ds.value, {})
        for tr in TemporalResolution:
            if tr.value in ds_block:
                _VARIABLE_INFO_CACHE[(ds, tr)] = ds_block[tr.value]
    if key not in _VARIABLE_INFO_CACHE:
        msg = (
            f"No cached variable info for NASA POWER "
            f"{dataset_type.value!r}/{temporal_resolution.value!r} in "
            f"{_VARIABLES_PATH}"
        )
        raise KeyError(msg)
    return _VARIABLE_INFO_CACHE[key]


# ---------------------------------------------------------------------------
# Registration with the refresh script
# ---------------------------------------------------------------------------


register(
    VariableCacheEntry(
        name="nasa_power",
        cache_path=_VARIABLES_PATH,
        fetch_live=_fetch_all_variable_info_live,
        load_disk=_load_all_variable_info_from_disk,
    )
)
