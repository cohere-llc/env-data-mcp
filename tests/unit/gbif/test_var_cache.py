"""Unit tests for the GBIF disk-backed variable cache.

The live-fetch path is exercised with mocked HTTP; the disk-backed lookup is
exercised against a temporary JSON file substituted for the shipped
``variables.json`` via ``monkeypatch``.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path

import httpx
import pytest

from env_data_mcp.sources.gbif import _var_cache
from env_data_mcp.sources.gbif.constants import _QueryType

_SCHEMA_ENDPOINT = "https://techdocs.gbif.org/openapi/occurrence.json"

_OCCURRENCE_RESPONSE = {
    "components": {
        "schemas": {
            "Occurrence": {
                "properties": {
                    "foo": {"description": "fooness"},
                    "bar": {"description": "baricity"},
                }
            }
        }
    }
}


@pytest.fixture(autouse=True)
def _reset_cache():
    """Ensure every test starts with a clean in-memory cache."""
    _var_cache._VARIABLE_INFO_CACHE.clear()
    yield
    _var_cache._VARIABLE_INFO_CACHE.clear()


# ---------------------------------------------------------------------------
# _fetch_variable_info_live
# ---------------------------------------------------------------------------


def test_fetch_variable_info_live_returns_parsed_schema(httpx_mock):
    httpx_mock.add_response(url=_SCHEMA_ENDPOINT, json=_OCCURRENCE_RESPONSE)

    result = _var_cache._fetch_variable_info_live(_QueryType.OCCURRENCE)

    assert result == {
        "foo": {"description": "fooness", "units": ""},
        "bar": {"description": "baricity", "units": ""},
    }


def test_fetch_variable_info_live_raises_for_status(httpx_mock):
    httpx_mock.add_response(url=_SCHEMA_ENDPOINT, status_code=HTTPStatus.NOT_FOUND)

    with pytest.raises(httpx.HTTPStatusError):
        _var_cache._fetch_variable_info_live(_QueryType.OCCURRENCE)


def test_fetch_all_variable_info_live_covers_every_query_type(httpx_mock):
    httpx_mock.add_response(url=_SCHEMA_ENDPOINT, json=_OCCURRENCE_RESPONSE)

    result = _var_cache._fetch_all_variable_info_live()

    assert set(result) == {qt.value for qt in _QueryType}
    assert result[_QueryType.OCCURRENCE.value] == {
        "foo": {"description": "fooness", "units": ""},
        "bar": {"description": "baricity", "units": ""},
    }


# ---------------------------------------------------------------------------
# _get_variable_info (disk-backed)
# ---------------------------------------------------------------------------


def _write_cache_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "variables.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_get_variable_info_reads_from_disk(monkeypatch, tmp_path):
    payload = {
        _QueryType.OCCURRENCE.value: {
            "foo": {"description": "fooness", "units": ""},
        }
    }
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, payload))

    result = _var_cache._get_variable_info(_QueryType.OCCURRENCE)

    assert result == {"foo": {"description": "fooness", "units": ""}}


def test_get_variable_info_caches_across_calls(monkeypatch, tmp_path):
    """After the first call, the on-disk file is not re-read."""
    payload = {_QueryType.OCCURRENCE.value: {"foo": {"description": "fooness", "units": ""}}}
    path = _write_cache_file(tmp_path, payload)
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", path)

    first = _var_cache._get_variable_info(_QueryType.OCCURRENCE)
    path.unlink()  # subsequent calls must not touch disk
    second = _var_cache._get_variable_info(_QueryType.OCCURRENCE)

    assert first is second
    assert first == {"foo": {"description": "fooness", "units": ""}}


def test_get_variable_info_no_network(monkeypatch, tmp_path, httpx_mock):
    """The disk-backed lookup must never issue an HTTP request."""
    payload = {_QueryType.OCCURRENCE.value: {"foo": {"description": "fooness", "units": ""}}}
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, payload))

    _var_cache._get_variable_info(_QueryType.OCCURRENCE)

    # httpx_mock fails the test if any unmocked call is issued; asserting no
    # requests were made is an extra belt-and-braces check.
    assert httpx_mock.get_requests() == []


def test_get_variable_info_raises_when_query_type_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, {}))

    with pytest.raises(KeyError, match="No variable info"):
        _var_cache._get_variable_info(_QueryType.OCCURRENCE)


# ---------------------------------------------------------------------------
# Shipped variables.json
# ---------------------------------------------------------------------------


def test_shipped_variables_json_is_wellformed():
    """The committed cache loads and covers every _QueryType."""
    data = _var_cache._load_all_variable_info_from_disk()
    for qt in _QueryType:
        assert qt.value in data, f"Missing query type {qt.value} in shipped cache"
        assert data[qt.value], f"Empty variable list for {qt.value}"
        for var_name, info in data[qt.value].items():
            assert "description" in info, f"{qt.value}.{var_name} missing description"
            assert "units" in info, f"{qt.value}.{var_name} missing units"


def test_shipped_variables_json_covers_default_variables():
    """Every default variable used by the GBIF tools is present in the cache."""
    from env_data_mcp.sources.gbif.constants import _DEFAULT_VARIABLES

    data = _var_cache._load_all_variable_info_from_disk()
    for qt, defaults in _DEFAULT_VARIABLES.items():
        cached = data[qt.value]
        missing = [v for v in defaults if v not in cached]
        assert not missing, (
            f"Default variables missing from shipped cache for {qt.value}: {missing}"
        )
