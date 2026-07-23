"""Drift-detection tests for per-adapter variable caches.

For every adapter registered in
:mod:`env_data_mcp.scripts.refresh_variable_caches`, this test fetches the
current variable metadata from upstream and compares it against the committed
on-disk ``variables.json``.  A mismatch fails the test, indicating the
committed cache is stale.

To rewrite the committed cache to match live upstream instead of asserting,
pass ``--update-caches``::

    pytest -m integration tests/integration/test_variable_caches_live.py \\
        --update-caches

Adapters are added to the registry as they migrate to the disk-backed
pattern; when the registry is empty this module is skipped at collection.
"""

from __future__ import annotations

import pytest

from env_data_mcp.helpers import save_json_cache
from env_data_mcp.scripts.refresh_variable_caches import get_registry

pytestmark = pytest.mark.integration

_REGISTRY = get_registry()

if not _REGISTRY:
    pytest.skip(
        "No adapters have been migrated to disk-backed variable caches yet.",
        allow_module_level=True,
    )


@pytest.mark.parametrize("name", sorted(_REGISTRY))
def test_variable_cache_matches_upstream(name: str, request: pytest.FixtureRequest) -> None:
    """Committed variables.json must equal live upstream discovery."""
    entry = _REGISTRY[name]
    live = entry.fetch_live()

    if request.config.getoption("--update-caches"):
        save_json_cache(entry.cache_path, live)
        pytest.skip(f"[{name}] cache updated at {entry.cache_path}")

    on_disk = entry.load_disk()
    assert live == on_disk, (
        f"[{name}] variable cache drift detected between upstream and "
        f"{entry.cache_path}. Re-run with --update-caches to rewrite it."
    )
