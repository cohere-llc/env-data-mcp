"""Unit tests for the SoilGrids disk-backed variable cache.

The live-fetch path (HTML scrape + WCS enumeration) is exercised with mocked
HTTP / mocked WebCoverageService; the disk-backed lookup is exercised
against a temporary JSON file substituted for the shipped ``variables.json``
via ``monkeypatch``.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import HTTPStatusError
from owslib.coverage.wcs100 import WebCoverageService_1_0_0

from env_data_mcp.sources.soilgrids import _var_cache
from env_data_mcp.sources.soilgrids._var_cache import BaseVariableInfo, VariableInfo
from env_data_mcp.sources.soilgrids.constants import _LAYERS_INFO_URL

# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

_VARIABLE_INFO_HTML: str = """\
<!DOCTYPE html>
<html>
<body>
  <table>
    <tr>
      <td>Name</td><td>Description</td><td>Mapped unit</td><td>Conversion factor</td><td>
      Conventional unit</td>
    </tr>
    <tr>
      <td>bdod</td><td>Bulk density</td><td>cg/cm3</td><td>100</td><td>kg/dm3</td>
    </tr>
    <tr>
      <td>cec</td><td>CEC buffered at pH7</td><td>mmol(c)/kg</td><td>10</td><td>cmol(c)/kg</td>
    </tr>
    <tr>
      <td>phh2o</td><td>pH water</td><td>pH x 10</td><td>10</td><td>-</td>
    </tr>
    <tr>
      <td>soc</td><td>Soil organic carbon</td><td>dg/kg</td><td>10</td><td>g/kg</td>
    </tr>
  </table>
  <table>
    <tr>
      <td>Top depth (cm)</td><td>0</td><td>5</td><td>15</td><td>30</td>
    </tr>
    <tr>
      <td>Bottom depth (cm)</td><td>5</td><td>15</td><td>30</td><td>60</td>
    </tr>
  </table>
</body>
</html>
"""

_VARIABLE_INFO_HTML_BAD_TABLE: str = """\
<!DOCTYPE html>
<html>
<body>
  <table>
    <tr>
      <td>Name</td><td>Description</td><td>Mapped unit</td><td>Conversion factor</td>
    </tr>
    <tr>
      <td>bdod</td><td>Bulk density</td><td>cg/cm3</td><td>100</td>
    </tr>
  </table>
</body>
</html>
"""

_VARIABLE_INFO_HTML_MISSING_CONVERSION: str = """\
<!DOCTYPE html>
<html>
<body>
  <table>
    <tr>
      <td>Name</td><td>Description</td><td>Mapped unit</td><td>Conversion factor</td><td>
      Conventional unit</td>
    </tr>
    <tr>
      <td>bdod</td><td>Bulk density</td><td>cg/cm3</td><td>100</td><td>kg/dm3</td>
    </tr>
    <tr>
      <td>phh2o</td><td>pH water</td><td>pH x 10</td><td>ten</td><td>-</td>
    </tr>
    <tr>
      <td>soc</td><td>Soil organic carbon</td><td>dg/kg</td><td>10</td><td>g/kg</td>
    </tr>
  </table>
</body>
</html>
"""


def _get_mock_wcs(contents: dict[str, Any] | None = None) -> WebCoverageService_1_0_0:
    mock = MagicMock(spec=WebCoverageService_1_0_0)
    mock.contents = contents or {
        "bdod_15-30cm_mean": {},
        "bdod_30-60cm_Q0.5": {},
    }
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_caches():
    """Ensure every test starts with clean in-memory caches."""
    _var_cache._BASE_VARIABLE_INFO_CACHE.clear()
    _var_cache._VARIABLE_INFO_CACHE.clear()
    yield
    _var_cache._BASE_VARIABLE_INFO_CACHE.clear()
    _var_cache._VARIABLE_INFO_CACHE.clear()


# ---------------------------------------------------------------------------
# _fetch_base_variable_list_live (HTML scrape)
# ---------------------------------------------------------------------------


def test_fetch_base_variable_list_live_returns_variables(httpx_mock):
    httpx_mock.add_response(url=_LAYERS_INFO_URL, text=_VARIABLE_INFO_HTML)

    variables = _var_cache._fetch_base_variable_list_live()

    assert len(variables) == 4
    entry = variables["bdod"]
    assert entry.name == "bdod"
    assert entry.mapped_units == "cg/cm3"
    assert entry.conversion_factor == 100.0
    assert entry.conventional_units == "kg/dm3"


def test_fetch_base_variable_list_live_raises_http_status_error(httpx_mock):
    httpx_mock.add_response(url=_LAYERS_INFO_URL, status_code=HTTPStatus.NOT_FOUND)

    with pytest.raises(HTTPStatusError):
        _var_cache._fetch_base_variable_list_live()


def test_fetch_base_variable_list_live_returns_empty_for_bad_html(httpx_mock):
    httpx_mock.add_response(url=_LAYERS_INFO_URL, text=_VARIABLE_INFO_HTML_BAD_TABLE)

    assert _var_cache._fetch_base_variable_list_live() == {}


def test_fetch_base_variable_list_live_skips_invalid_conversion(httpx_mock):
    httpx_mock.add_response(url=_LAYERS_INFO_URL, text=_VARIABLE_INFO_HTML_MISSING_CONVERSION)

    variables = _var_cache._fetch_base_variable_list_live()

    assert "phh2o" not in variables
    assert set(variables) == {"bdod", "soc"}


# ---------------------------------------------------------------------------
# _fetch_specific_variable_info_live (WCS)
# ---------------------------------------------------------------------------


def test_fetch_specific_variable_info_live_returns_coverages():
    with patch(
        "env_data_mcp.sources.soilgrids._client.WebCoverageService",
        return_value=_get_mock_wcs(),
    ):
        var_info = _var_cache._fetch_specific_variable_info_live("bdod")

    assert var_info["bdod_15-30cm_mean"] == ("15-30cm", "mean")
    assert var_info["bdod_30-60cm_Q0.5"] == ("30-60cm", "median")


@pytest.mark.parametrize(
    "contents",
    [
        pytest.param({"invalid_coverage": {}}, id="too short"),
        pytest.param({"in_valid_cover_age": {}}, id="too long"),
        pytest.param({"": {}}, id="empty"),
    ],
)
def test_fetch_specific_variable_info_live_raises_value_error(contents):
    with (
        patch(
            "env_data_mcp.sources.soilgrids._client.WebCoverageService",
            return_value=_get_mock_wcs(contents),
        ),
        pytest.raises(ValueError, match="Invalid coverage name"),
    ):
        _var_cache._fetch_specific_variable_info_live("foo")


# ---------------------------------------------------------------------------
# _fetch_all_variable_info_live
# ---------------------------------------------------------------------------


def test_fetch_all_variable_info_live_orchestrates(httpx_mock):
    httpx_mock.add_response(url=_LAYERS_INFO_URL, text=_VARIABLE_INFO_HTML)
    with patch(
        "env_data_mcp.sources.soilgrids._var_cache._fetch_specific_variable_info_live",
        side_effect=lambda base: {f"{base}_0-5cm_mean": ("0-5cm", "mean")},
    ):
        result = _var_cache._fetch_all_variable_info_live()

    assert "bdod" in result
    block = result["bdod"]
    assert block["base"]["conversion_factor"] == 100.0
    assert block["base"]["conventional_units"] == "kg/dm3"
    cov = block["coverages"]["bdod_0-5cm_mean"]
    assert cov["description"] == "Bulk density; depth: 0-5cm; quantile: mean"
    assert cov["units"] == "kg/dm3"


def test_fetch_all_variable_info_live_skips_failed_bases(httpx_mock):
    httpx_mock.add_response(url=_LAYERS_INFO_URL, text=_VARIABLE_INFO_HTML)

    def _flaky(base: str):
        if base == "phh2o":
            raise ValueError("upstream error")
        return {f"{base}_0-5cm_mean": ("0-5cm", "mean")}

    with patch(
        "env_data_mcp.sources.soilgrids._var_cache._fetch_specific_variable_info_live",
        side_effect=_flaky,
    ):
        result = _var_cache._fetch_all_variable_info_live()

    assert "phh2o" not in result
    assert {"bdod", "cec", "soc"}.issubset(result)


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


def test_base_variable_info_dict_roundtrip():
    original = BaseVariableInfo(
        name="bdod",
        description="Bulk density",
        mapped_units="cg/cm3",
        conversion_factor=100.0,
        conventional_units="kg/dm3",
    )
    restored = _var_cache._base_variable_info_from_dict(
        _var_cache._base_variable_info_to_dict(original)
    )
    assert restored == original


# ---------------------------------------------------------------------------
# Disk-backed lookup
# ---------------------------------------------------------------------------


def _write_cache_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "variables.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _bdod_payload() -> dict:
    return {
        "bdod": {
            "base": {
                "name": "bdod",
                "description": "Bulk density",
                "mapped_units": "cg/cm3",
                "conversion_factor": 100.0,
                "conventional_units": "kg/dm3",
            },
            "coverages": {
                "bdod_0-5cm_mean": {
                    "description": "Bulk density; depth: 0-5cm; quantile: mean",
                    "units": "kg/dm3",
                },
            },
        }
    }


def test_get_base_variable_list_reads_from_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, _bdod_payload()))

    result = _var_cache.get_base_variable_list()

    assert set(result) == {"bdod"}
    assert isinstance(result["bdod"], BaseVariableInfo)
    assert result["bdod"].conversion_factor == 100.0


def test_get_variable_info_reads_from_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, _bdod_payload()))

    result = _var_cache.get_variable_info("bdod")

    entry = result["bdod_0-5cm_mean"]
    assert isinstance(entry, VariableInfo)
    assert entry.units == "kg/dm3"
    assert isinstance(entry.base, BaseVariableInfo)
    assert entry.base.conversion_factor == 100.0  # load-bearing for query path


def test_get_variable_info_caches_across_calls(monkeypatch, tmp_path):
    """After the first call the on-disk file is not re-read."""
    path = _write_cache_file(tmp_path, _bdod_payload())
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", path)

    first = _var_cache.get_variable_info("bdod")
    path.unlink()  # subsequent calls must not touch disk
    second = _var_cache.get_variable_info("bdod")

    assert first is second


def test_get_variable_info_raises_when_base_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, {}))

    with pytest.raises(KeyError, match="No cached variable info"):
        _var_cache.get_variable_info("bdod")


# ---------------------------------------------------------------------------
# Shipped variables.json
# ---------------------------------------------------------------------------


def test_shipped_variables_json_is_wellformed():
    data = _var_cache._load_all_variable_info_from_disk()
    assert data, "shipped variables.json is empty"
    base_keys = {"name", "description", "mapped_units", "conversion_factor", "conventional_units"}
    for base, block in data.items():
        assert set(block) == {"base", "coverages"}, f"{base} has unexpected top-level keys"
        assert set(block["base"]) == base_keys, f"{base}.base has unexpected keys"
        assert block["coverages"], f"{base} has no coverages"
        for cov_name, cov in block["coverages"].items():
            assert set(cov) == {"description", "units"}, (
                f"{base}.{cov_name} has unexpected keys: {set(cov)}"
            )


def test_shipped_variables_json_covers_default_variables():
    from env_data_mcp.sources.soilgrids.constants import DEFAULT_VARIABLES

    data = _var_cache._load_all_variable_info_from_disk()
    all_coverages = {cov for block in data.values() for cov in block["coverages"]}
    missing = [v for v in DEFAULT_VARIABLES if v not in all_coverages]
    assert not missing, f"Default variables missing from shipped cache: {missing}"


def test_shipped_variables_json_hydrates_to_dataclasses():
    _var_cache._BASE_VARIABLE_INFO_CACHE.clear()
    _var_cache._VARIABLE_INFO_CACHE.clear()

    bases = _var_cache.get_base_variable_list()
    assert bases, "no base variables loaded from shipped cache"

    for base, bvi in bases.items():
        assert isinstance(bvi, BaseVariableInfo)
        assert bvi.name == base
        coverages = _var_cache.get_variable_info(base)
        assert coverages, f"no coverages loaded for {base}"
        for _, cov in coverages.items():
            assert isinstance(cov, VariableInfo)
            assert isinstance(cov.base, BaseVariableInfo)
            assert cov.base is bvi  # shared instance, not a copy
