"""Unit tests for the SSURGO disk-backed variable cache.

The live-fetch path (PDF download + parse + XSD schema introspection) is
exercised with mocked HTTP / mocked pdfplumber; the disk-backed lookup is
exercised against a temporary JSON file substituted for the shipped
``variables.json`` via ``monkeypatch``.
"""

from __future__ import annotations

import json
import textwrap
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import pdfplumber
import pytest

import env_data_mcp.sources.ssurgo._var_cache as _var_cache
from env_data_mcp.sources.ssurgo._var_cache import (
    _PDF_URL,
    _extract_uom,
    _fetch_all_variable_info_live,
    _get_column_table_map,
    _get_variable_info,
    _load_column_metadata_live,
    _parse_col_metadata_pdf,
)
from env_data_mcp.sources.ssurgo.constants import (
    DEFAULT_AREA_SUMMARY_VARIABLES,
    DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    DEFAULT_PARENT_MATERIAL_VARIABLES,
    DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    DEFAULT_SOIL_PROFILE_VARIABLES,
    DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    _QueryType,
)

from .conftest import _SDA_URL, TABLE_SCHEMA_XMLS

# ---------------------------------------------------------------------------
# _extract_uom (pure function)
# ---------------------------------------------------------------------------


def test_extract_uom_simple_unit():
    assert _extract_uom("10 100 percent") == "percent"


def test_extract_uom_strips_domain_suffix():
    # Domain names contain underscores and appear last; strip before returning UOM.
    assert _extract_uom("10 100 percent domain_name") == "percent"


def test_extract_uom_all_numeric_returns_empty():
    assert _extract_uom("10 25 100") == ""


def test_extract_uom_empty_string():
    assert _extract_uom("") == ""


def test_extract_uom_complex_unit():
    # Units like "g/cm3" or "cmol(+)/kg" should be returned as-is.
    assert _extract_uom("4 g/cm3") == "g/cm3"


def test_extract_uom_only_domain_name_returns_empty():
    assert _extract_uom("domain_name") == ""


# ---------------------------------------------------------------------------
# _parse_col_metadata_pdf (monkeypatched pdfplumber)
# ---------------------------------------------------------------------------


def _make_fake_pdf(pages_text: list[str]):
    """Return a fake pdfplumber context manager whose pages yield fixed text."""

    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakePDF:
        def __init__(self, texts: list[str]):
            self.pages = [_FakePage(t) for t in texts]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    return _FakePDF(pages_text)


def test_parse_col_metadata_pdf_parses_table_and_column(monkeypatch):
    page_text = textwrap.dedent(
        """\
        Preamble line before any table header
        Table Physical Name: mapunit
        Seq. Col Physical Name Description
        Non-matching row without digits at start
        1 Map Unit Symbol musym mapunit_sym String Varchar(6) yes 6 domain_mapunit_sym
        """
    )
    monkeypatch.setattr(pdfplumber, "open", lambda *a, **kw: _make_fake_pdf([page_text]))
    result = _parse_col_metadata_pdf(b"fake bytes")
    assert "mapunit" in result
    assert "musym" in result["mapunit"]
    assert result["mapunit"]["musym"]["label"] == "Map Unit Symbol"


def test_parse_col_metadata_pdf_empty_pages(monkeypatch):
    monkeypatch.setattr(pdfplumber, "open", lambda *a, **kw: _make_fake_pdf([""]))
    assert _parse_col_metadata_pdf(b"fake bytes") == {}


# ---------------------------------------------------------------------------
# _load_column_metadata_live
# ---------------------------------------------------------------------------


def test_load_column_metadata_live_fetches_and_parses(httpx_mock, monkeypatch):
    monkeypatch.setattr(
        _var_cache,
        "_parse_col_metadata_pdf",
        lambda b: {"mapunit": {"musym": {"label": "Map Unit Symbol", "units": ""}}},
    )
    httpx_mock.add_response(method="GET", url=_PDF_URL, content=b"fake pdf bytes")
    result = _load_column_metadata_live()
    assert "mapunit" in result


def test_load_column_metadata_live_http_error_returns_empty(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=_PDF_URL, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
    )
    assert _load_column_metadata_live() == {}


# ---------------------------------------------------------------------------
# _fetch_all_variable_info_live orchestration
# ---------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_fetch_all_variable_info_live_builds_both_caches(httpx_mock, monkeypatch):
    """Refresh should return both the variable_info and column_table_map blocks."""
    # Skip PDF entirely (empty metadata → columns have empty label/units)
    monkeypatch.setattr(_var_cache, "_load_column_metadata_live", lambda: {})

    # Map every table name to its mock XSD response.
    def _fake_columns(table: str) -> list[str]:
        xml = TABLE_SCHEMA_XMLS.get(table)
        if xml is None:
            raise ConnectionError(f"no fixture for {table}")
        # Use the real XSD parser via the mocked HTTP layer.
        httpx_mock.add_response(method="POST", url=_SDA_URL, text=xml)
        from env_data_mcp.sources.ssurgo._client import _sda_table_columns

        return _sda_table_columns(table)

    monkeypatch.setattr(_var_cache, "_sda_table_columns", _fake_columns)

    result = _fetch_all_variable_info_live()

    assert set(result) == {"variable_info", "column_table_map"}
    assert set(result["variable_info"]) == {qt.value for qt in _QueryType}
    # mapunit's mukey should be in column_table_map, resolved to mapunit
    assert result["column_table_map"].get("mukey") == "mapunit"
    # soil_profile should have columns from mapunit, component, chorizon
    profile = result["variable_info"]["soil_profile"]
    assert profile["mukey"]["table"] == "mapunit"
    assert profile["mukey"]["label"] == ""  # no PDF metadata


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_fetch_all_variable_info_live_skips_failing_tables(monkeypatch):
    """Tables whose XSD introspection fails during refresh are skipped silently."""
    monkeypatch.setattr(_var_cache, "_load_column_metadata_live", lambda: {})

    def _flaky(table: str) -> list[str]:
        if table == "mapunit":
            return ["mukey", "muname"]
        raise ConnectionError(f"no response for {table}")

    monkeypatch.setattr(_var_cache, "_sda_table_columns", _flaky)

    result = _fetch_all_variable_info_live()
    # mapunit succeeded → mukey / muname are in both maps
    assert result["column_table_map"].get("mukey") == "mapunit"
    # Other tables failed silently → their columns simply aren't present
    assert "cokey" not in result["column_table_map"]


def test_fetch_all_variable_info_live_applies_pdf_metadata(monkeypatch):
    monkeypatch.setattr(
        _var_cache,
        "_load_column_metadata_live",
        lambda: {"chorizon": {"sandtotal": {"label": "Total Sand", "units": "percent"}}},
    )

    def _fake_columns(table: str) -> list[str]:
        if table == "chorizon":
            return ["sandtotal_r", "sandtotal_l"]
        return []

    monkeypatch.setattr(_var_cache, "_sda_table_columns", _fake_columns)

    result = _fetch_all_variable_info_live()
    profile = result["variable_info"]["soil_profile"]
    # _r and _l suffix stripped → both resolve to the same PDF entry
    assert profile["sandtotal_r"]["label"] == "Total Sand"
    assert profile["sandtotal_r"]["units"] == "percent"
    assert profile["sandtotal_l"]["label"] == "Total Sand"


# ---------------------------------------------------------------------------
# Disk-backed lookup
# ---------------------------------------------------------------------------


def _write_cache_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "variables.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _minimal_payload() -> dict:
    return {
        "variable_info": {
            _QueryType.SOIL_PROFILE.value: {
                "mukey": {"table": "mapunit", "label": "Mapunit Key", "units": ""},
                "sandtotal_r": {"table": "chorizon", "label": "Total Sand", "units": "percent"},
            }
        },
        "column_table_map": {
            "mukey": "mapunit",
            "sandtotal_r": "chorizon",
        },
    }


def test_get_variable_info_reads_from_disk(monkeypatch, tmp_path):
    """The disk-backed path returns per-query-type column metadata."""
    _var_cache._VARIABLE_INFO_CACHE.clear()
    _var_cache._COLUMN_TABLE_CACHE.clear()
    monkeypatch.setattr(
        _var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, _minimal_payload())
    )

    info = _get_variable_info(_QueryType.SOIL_PROFILE)
    assert info["sandtotal_r"]["table"] == "chorizon"
    assert info["sandtotal_r"]["label"] == "Total Sand"


def test_get_column_table_map_reads_from_disk(monkeypatch, tmp_path):
    _var_cache._VARIABLE_INFO_CACHE.clear()
    _var_cache._COLUMN_TABLE_CACHE.clear()
    monkeypatch.setattr(
        _var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, _minimal_payload())
    )

    ctm = _get_column_table_map()
    assert ctm["mukey"] == "mapunit"
    assert ctm["sandtotal_r"] == "chorizon"


def test_disk_load_happens_once(monkeypatch, tmp_path):
    """The first access hydrates both caches; subsequent access does not re-read."""
    _var_cache._VARIABLE_INFO_CACHE.clear()
    _var_cache._COLUMN_TABLE_CACHE.clear()
    path = _write_cache_file(tmp_path, _minimal_payload())
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", path)

    _ = _get_variable_info(_QueryType.SOIL_PROFILE)
    path.unlink()  # subsequent calls must not touch disk
    _ = _get_column_table_map()


def test_get_variable_info_raises_when_query_type_missing(monkeypatch, tmp_path):
    _var_cache._VARIABLE_INFO_CACHE.clear()
    _var_cache._COLUMN_TABLE_CACHE.clear()
    monkeypatch.setattr(
        _var_cache,
        "_VARIABLES_PATH",
        _write_cache_file(tmp_path, {"variable_info": {}, "column_table_map": {}}),
    )

    with pytest.raises(RuntimeError, match="No cached variable info"):
        _get_variable_info(_QueryType.SOIL_PROFILE)


def test_disk_load_ignores_unknown_query_types(monkeypatch, tmp_path):
    """A stale JSON with query types not in the current build is silently skipped."""
    payload = _minimal_payload()
    payload["variable_info"]["not_a_real_qt"] = {"foo": {"table": "bar"}}
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, payload))
    _var_cache._VARIABLE_INFO_CACHE.clear()
    _var_cache._COLUMN_TABLE_CACHE.clear()

    info = _get_variable_info(_QueryType.SOIL_PROFILE)
    assert "sandtotal_r" in info


# ---------------------------------------------------------------------------
# Shipped variables.json
# ---------------------------------------------------------------------------


def test_shipped_variables_json_is_wellformed():
    """The committed cache loads and every entry has the expected fields."""
    data = _var_cache._load_all_variable_info_from_disk()
    assert set(data) == {"variable_info", "column_table_map"}
    assert set(data["variable_info"]) == {qt.value for qt in _QueryType}
    for qt_value, cols in data["variable_info"].items():
        assert cols, f"{qt_value} has no columns in shipped cache"
        for col, entry in cols.items():
            assert set(entry) >= {"table"}, f"{qt_value}.{col} missing 'table'"
            assert isinstance(entry.get("label", ""), str)
            assert isinstance(entry.get("units", ""), str)
    ctm = data["column_table_map"]
    assert ctm, "column_table_map is empty"
    assert ctm.get("mukey") == "mapunit"


_DEFAULTS_BY_QUERY_TYPE = {
    _QueryType.SOIL_PROFILE: DEFAULT_SOIL_PROFILE_VARIABLES,
    _QueryType.AREA_SUMMARY: DEFAULT_AREA_SUMMARY_VARIABLES,
    _QueryType.SUBSURFACE_BARRIERS: DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    _QueryType.SEASONAL_HYDROLOGY: DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    _QueryType.ECOLOGICAL_SITE: DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    _QueryType.PARENT_MATERIAL: DEFAULT_PARENT_MATERIAL_VARIABLES,
    _QueryType.SOIL_TEMPERATURE: DEFAULT_SOIL_TEMPERATURE_VARIABLES,
}


@pytest.mark.parametrize(
    "qt,defaults",
    list(_DEFAULTS_BY_QUERY_TYPE.items()),
    ids=[qt.value for qt in _DEFAULTS_BY_QUERY_TYPE],
)
def test_shipped_variables_json_covers_default_variables(qt, defaults):
    """Every default variable for each query type is in the shipped cache."""
    data = _var_cache._load_all_variable_info_from_disk()
    cached = data["variable_info"][qt.value]
    missing = [v for v in defaults if v not in cached]
    assert not missing, f"Default variables missing from shipped {qt.value} cache: {missing}"


def test_shipped_variables_json_covers_default_column_table_map():
    """Load-bearing columns used by sql.py resolve to a table in the shipped map."""
    data = _var_cache._load_all_variable_info_from_disk()
    ctm = data["column_table_map"]
    # Sample of load-bearing FK / PK columns from the SSURGO tables.
    for col in ("mukey", "cokey", "hzdept_r", "sandtotal_r"):
        assert ctm.get(col), f"{col} missing from shipped column_table_map"


def test_get_variable_info_reads_shipped_cache():
    """End-to-end: clear in-memory state, read real shipped JSON."""
    with (
        patch.object(_var_cache, "_VARIABLE_INFO_CACHE", {}),
        patch.object(_var_cache, "_COLUMN_TABLE_CACHE", {}),
    ):
        info = _get_variable_info(_QueryType.SOIL_PROFILE)
    assert "mukey" in info
    assert info["mukey"]["table"] == "mapunit"
