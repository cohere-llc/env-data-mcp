"""Zarr store client: open, cache, and read coordinates and variable metadata."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import zarr
from zarr.storage import FsspecStore

from .constants import _ZARR_URLS, DatasetType, TemporalResolution

# ---------------------------------------------------------------------------
# Zarr store cache
# ---------------------------------------------------------------------------


class ZarrStoreCache:
    """Cache for opened Zarr stores and their coordinate arrays."""

    def __init__(self, group: zarr.Group) -> None:
        self._group: zarr.Group = group
        self._cached_dims_for_group: zarr.Group | None = None
        self._lats: np.ndarray | None = None
        self._lons: np.ndarray | None = None
        self._times: pd.DatetimeIndex | None = None


# Module-level cache keyed by (DatasetType, TemporalResolution).
_zarr_cache: dict[tuple[DatasetType, TemporalResolution], ZarrStoreCache] = {}


def _clear_store_cache() -> None:
    """Evict all cached Zarr stores. Useful in benchmarks to force fresh opens."""
    global _zarr_cache
    _zarr_cache.clear()


# ---------------------------------------------------------------------------
# Store access
# ---------------------------------------------------------------------------


def _open_store(
    dataset_type: DatasetType, temporal_resolution: TemporalResolution
) -> ZarrStoreCache:
    """Open (and cache) the NASA POWER Zarr store with an optional in-memory cache."""
    global _zarr_cache
    cache_key = (dataset_type, temporal_resolution)
    if cache_key in _zarr_cache:
        return _zarr_cache[cache_key]

    source = FsspecStore.from_url(
        _ZARR_URLS[dataset_type][temporal_resolution],
        read_only=True,
    )
    try:
        from zarr.experimental.cache_store import CacheStore
        from zarr.storage import MemoryStore

        mem = MemoryStore()
        store: Any = CacheStore(store=source, cache_store=mem, max_size=256 * 1024 * 1024)
    except ImportError:
        store = source  # no caching if experimental module not available

    _zarr_cache[(dataset_type, temporal_resolution)] = ZarrStoreCache(
        zarr.open_group(store=store, mode="r")
    )
    return _zarr_cache[(dataset_type, temporal_resolution)]


def _get_coordinates(store: ZarrStoreCache) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """Return (lats, lons, times) for *store*, loading them once and caching.

    The cache is keyed on group identity: a different group object (e.g. a test
    mock vs. the real S3 store) triggers a fresh read so the two never share
    cached coordinates.
    """
    if store._cached_dims_for_group is store._group:
        assert store._lats is not None
        assert store._lons is not None
        assert store._times is not None
        return store._lats, store._lons, store._times

    store._lats = np.asarray(store._group["lat"][:])  # type: ignore[arg-type]
    store._lons = np.asarray(store._group["lon"][:])  # type: ignore[arg-type]

    time_arr = store._group["time"]
    raw_times: np.ndarray = np.asarray(time_arr[:])  # type: ignore[arg-type]
    time_units: str = str(time_arr.attrs.get("units", ""))
    if time_units.startswith("days since "):
        origin = pd.Timestamp(time_units[len("days since ") :].split()[0])
        store._times = origin + pd.to_timedelta(raw_times.astype(float), unit="D")
    elif time_units.startswith("hours since "):
        origin = pd.Timestamp(time_units[len("hours since ") :].split()[0])
        store._times = origin + pd.to_timedelta(raw_times.astype(float), unit="h")
    else:
        # Fallback for mocks / legacy stores that have no units attribute.
        store._times = pd.to_datetime(raw_times.astype(float), unit="D")

    store._cached_dims_for_group = store._group
    return store._lats, store._lons, store._times
