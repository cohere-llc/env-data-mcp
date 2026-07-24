"""Unit tests for env_data_mcp.scripts.refresh_variable_caches."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from env_data_mcp.scripts import refresh_variable_caches as rvc
from env_data_mcp.scripts.refresh_variable_caches import (
    VariableCacheEntry,
    get_registry,
    main,
    refresh,
    register,
)

# ---------------------------------------------------------------------------
# Test isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _snapshot_registry() -> Iterator[None]:
    """Preserve module-level ``_REGISTRY`` across tests.

    ``register(...)`` is called as a side-effect of importing each adapter's
    ``_var_cache`` module and each module is imported exactly once per
    interpreter session; if we snapshot an empty ``_REGISTRY`` and later
    clear it, subsequent ``get_registry()`` calls hit cached (no-op) imports
    and leave the registry permanently empty.  Priming via ``get_registry()``
    before the snapshot avoids that trap.
    """
    get_registry()  # ensure every adapter's register() has fired
    saved = dict(rvc._REGISTRY)
    yield
    rvc._REGISTRY.clear()
    rvc._REGISTRY.update(saved)


def _make_entry(
    name: str,
    cache_path: Path,
    *,
    fetch_live: Callable[[], Any] | None = None,
    load_disk: Callable[[], Any] | None = None,
) -> VariableCacheEntry:
    """Build a ``VariableCacheEntry`` with defaults for optional callables."""
    return VariableCacheEntry(
        name=name,
        cache_path=cache_path,
        fetch_live=fetch_live or (lambda: {"stub": True}),
        load_disk=load_disk or (lambda: {"stub": True}),
    )


# ---------------------------------------------------------------------------
# VariableCacheEntry
# ---------------------------------------------------------------------------


def test_variable_cache_entry_is_frozen(tmp_path):
    entry = _make_entry("foo", tmp_path / "foo.json")
    with pytest.raises((AttributeError, Exception)):
        # frozen dataclasses raise dataclasses.FrozenInstanceError (AttributeError subclass)
        entry.name = "bar"  # type: ignore[misc]


def test_variable_cache_entry_stores_all_fields(tmp_path):
    def _fetch() -> dict[str, Any]:
        return {"live": 1}

    def _load() -> dict[str, Any]:
        return {"disk": 1}

    entry = VariableCacheEntry(
        name="adapter",
        cache_path=tmp_path / "variables.json",
        fetch_live=_fetch,
        load_disk=_load,
    )

    assert entry.name == "adapter"
    assert entry.cache_path == tmp_path / "variables.json"
    assert entry.fetch_live is _fetch
    assert entry.load_disk is _load


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def test_register_adds_entry(tmp_path):
    rvc._REGISTRY.clear()
    entry = _make_entry("foo", tmp_path / "foo.json")

    register(entry)

    assert {"foo": entry} == rvc._REGISTRY


def test_register_replaces_existing_entry(tmp_path):
    rvc._REGISTRY.clear()
    first = _make_entry("foo", tmp_path / "one.json")
    second = _make_entry("foo", tmp_path / "two.json")

    register(first)
    register(second)

    assert {"foo": second} == rvc._REGISTRY


# ---------------------------------------------------------------------------
# get_registry()
# ---------------------------------------------------------------------------


def test_get_registry_returns_snapshot_not_alias():
    """Mutating the returned dict must not affect the module-level registry."""
    snapshot = get_registry()
    snapshot.clear()
    # The real registry must still contain the adapters populated during import.
    assert get_registry()


def test_get_registry_includes_all_migrated_adapters():
    """All five adapters that were migrated to disk-backed caches are registered."""
    registry = get_registry()
    assert set(registry) >= {"gbif", "nasa_power", "soilgrids", "ssurgo", "tropomi"}


def test_get_registry_entries_are_variable_cache_entries():
    registry = get_registry()
    for name, entry in registry.items():
        assert isinstance(entry, VariableCacheEntry), f"{name} is not a VariableCacheEntry"
        assert entry.name == name
        assert entry.cache_path.name == "variables.json"
        assert callable(entry.fetch_live)
        assert callable(entry.load_disk)


# ---------------------------------------------------------------------------
# refresh()
# ---------------------------------------------------------------------------


def test_refresh_writes_fetch_live_output_to_cache_path(tmp_path, monkeypatch):
    payload = {"vars": {"foo": {"description": "fooness", "units": ""}}}
    cache_path = tmp_path / "variables.json"
    entry = _make_entry("stub", cache_path, fetch_live=lambda: payload)

    monkeypatch.setattr(rvc, "get_registry", lambda: {"stub": entry})

    written = refresh("stub")

    assert written == cache_path
    assert cache_path.exists()
    assert json.loads(cache_path.read_text()) == payload


def test_refresh_returns_cache_path(tmp_path, monkeypatch):
    cache_path = tmp_path / "variables.json"
    entry = _make_entry("stub", cache_path)
    monkeypatch.setattr(rvc, "get_registry", lambda: {"stub": entry})

    assert refresh("stub") == cache_path


def test_refresh_raises_key_error_for_unknown_adapter(monkeypatch):
    monkeypatch.setattr(rvc, "get_registry", lambda: {})

    with pytest.raises(KeyError):
        refresh("does-not-exist")


def test_refresh_propagates_fetch_live_errors(tmp_path, monkeypatch):
    def _boom() -> dict[str, Any]:
        raise RuntimeError("upstream boom")

    entry = _make_entry("stub", tmp_path / "v.json", fetch_live=_boom)
    monkeypatch.setattr(rvc, "get_registry", lambda: {"stub": entry})

    with pytest.raises(RuntimeError, match="upstream boom"):
        refresh("stub")

    assert not (tmp_path / "v.json").exists(), "cache file must not be written on error"


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_requires_adapter_argument(capsys):
    """Missing --adapter triggers argparse's usage error (SystemExit 2)."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--adapter" in err


def test_main_empty_registry_prints_message_and_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr(rvc, "get_registry", lambda: {})

    rc = main(["--adapter", "anything"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "No adapters registered" in out


def test_main_unknown_adapter_calls_parser_error(monkeypatch, tmp_path, capsys):
    """Unknown --adapter (with non-empty registry) exits via parser.error."""
    entry = _make_entry("gbif", tmp_path / "gbif.json")
    monkeypatch.setattr(rvc, "get_registry", lambda: {"gbif": entry})

    with pytest.raises(SystemExit) as exc:
        main(["--adapter", "does-not-exist"])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "does-not-exist" in err


def test_main_known_adapter_refreshes_only_that_adapter(monkeypatch, tmp_path, capsys):
    """`--adapter gbif` invokes refresh() exactly once for gbif."""
    gbif_path = tmp_path / "gbif.json"
    nasa_path = tmp_path / "nasa.json"
    entries = {
        "gbif": _make_entry("gbif", gbif_path, fetch_live=lambda: {"g": 1}),
        "nasa": _make_entry("nasa", nasa_path, fetch_live=lambda: {"n": 1}),
    }
    monkeypatch.setattr(rvc, "get_registry", lambda: entries)

    rc = main(["--adapter", "gbif"])

    assert rc == 0
    assert gbif_path.exists()
    assert not nasa_path.exists()
    out = capsys.readouterr().out
    assert str(gbif_path) in out
    assert str(nasa_path) not in out


def test_main_all_refreshes_every_registered_adapter(monkeypatch, tmp_path, capsys):
    entries = {
        name: _make_entry(name, tmp_path / f"{name}.json", fetch_live=lambda k=name: {k: 1})
        for name in ("gbif", "nasa", "ssurgo")
    }
    monkeypatch.setattr(rvc, "get_registry", lambda: entries)

    rc = main(["--adapter", "all"])

    assert rc == 0
    for name in entries:
        cache_file = tmp_path / f"{name}.json"
        assert cache_file.exists(), f"{name} was not refreshed"
        assert json.loads(cache_file.read_text()) == {name: 1}
    out = capsys.readouterr().out
    for name in entries:
        assert f"[{name}]" in out


def test_main_all_processes_adapters_in_sorted_order(monkeypatch, tmp_path, capsys):
    """The 'all' code path iterates ``sorted(registry)`` for deterministic output."""
    call_order: list[str] = []

    def _make(name: str) -> VariableCacheEntry:
        return _make_entry(
            name,
            tmp_path / f"{name}.json",
            fetch_live=lambda n=name: call_order.append(n) or {"n": n},
        )

    entries = {name: _make(name) for name in ("charlie", "alpha", "bravo")}
    monkeypatch.setattr(rvc, "get_registry", lambda: entries)

    main(["--adapter", "all"])

    assert call_order == ["alpha", "bravo", "charlie"]


def test_main_help_exits_zero(capsys):
    """--help exits with code 0 and prints usage."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--adapter" in out
