"""Refresh per-adapter variable caches from live upstream sources.

Adapters persist their discovered variable metadata to a ``variables.json``
file shipped next to its source code.  At MCP server runtime, adapters read
those files directly to support requests for available variables.  This module
provides the workflow that regenerates those files against upstream sources.

Registry
--------
Adapters register a :class:`VariableCacheEntry` describing:

* the on-disk cache path,
* a ``fetch_live`` callable that pulls the current metadata from upstream and
  returns a JSON-serialisable dict, and
* a ``load_disk`` callable that reads and deserialises the on-disk cache.

The registry is populated in :func:`get_registry` by importing each adapter's
cache module for its side-effect ``register(...)`` call.

Usage
-----
Refresh a single adapter::

    python -m env_data_mcp.scripts.refresh_variable_caches --adapter gbif

Refresh everything currently registered::

    python -m env_data_mcp.scripts.refresh_variable_caches --adapter all
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from env_data_mcp.helpers import save_json_cache


@dataclass(frozen=True)
class VariableCacheEntry:
    """Registry entry describing one adapter's persisted variable cache."""

    name: str  # Short adapter name, e.g. "gbif"
    cache_path: Path  # Absolute path to the on-disk variables.json
    fetch_live: Callable[[], Any]  # Returns a JSON-serialisable dict from upstream
    load_disk: Callable[[], Any]  # Returns a JSON-serialisable dict from cache_path


_REGISTRY: dict[str, VariableCacheEntry] = {}


def register(entry: VariableCacheEntry) -> None:
    """Register (or replace) an adapter's variable-cache entry."""
    _REGISTRY[entry.name] = entry


def get_registry() -> dict[str, VariableCacheEntry]:
    """Return a snapshot of all registered adapters.

    Imports every adapter's cache module to trigger its ``register(...)`` call
    as a side-effect.  Add a new import here when migrating an adapter to the
    disk-backed variable cache.
    """
    # Adapter registrations land here as each phase is completed:
    from env_data_mcp.sources.gbif import _var_cache  # noqa: F401

    # from env_data_mcp.sources.nasa_power import _var_cache  # noqa: F401
    # from env_data_mcp.sources.tropomi import _var_cache  # noqa: F401
    # from env_data_mcp.sources.soilgrids import _var_cache  # noqa: F401
    # from env_data_mcp.sources.ssurgo import _var_cache  # noqa: F401
    return dict(_REGISTRY)


def refresh(name: str) -> Path:
    """Fetch *name*'s variables from upstream and write the on-disk cache.

    Returns the path that was written.
    """
    entry = get_registry()[name]
    data = entry.fetch_live()
    save_json_cache(entry.cache_path, data)
    return entry.cache_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh per-adapter variable caches from live upstream sources.",
    )
    parser.add_argument(
        "--adapter",
        required=True,
        help="Adapter name to refresh, or 'all' for every registered adapter.",
    )
    args = parser.parse_args(argv)

    registry = get_registry()
    if not registry:
        print("No adapters registered yet; nothing to refresh.")
        return 0

    if args.adapter == "all":
        names = sorted(registry)
    elif args.adapter in registry:
        names = [args.adapter]
    else:
        parser.error(
            f"Unknown adapter: {args.adapter!r}. Known: {sorted(registry) or '(none)'}",
        )

    for n in names:
        written = refresh(n)
        print(f"[{n}] wrote {written}")
    return 0


if __name__ == "__main__":
    # Re-import through the canonical module path so that adapter modules
    # registering via ``from env_data_mcp.scripts.refresh_variable_caches
    # import register`` populate the same _REGISTRY that ``main`` inspects.
    # Running ``python -m env_data_mcp.scripts.refresh_variable_caches``
    # otherwise loads this file twice (as ``__main__`` and under its real
    # name), leaving the module-level ``_REGISTRY`` split across two copies.
    from env_data_mcp.scripts.refresh_variable_caches import main as _main

    raise SystemExit(_main())
