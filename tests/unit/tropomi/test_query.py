"""Unit tests for the TROPOMI _query module.

All HTTP calls are mocked via ``pytest-httpx``; no network access required.
"""

from __future__ import annotations

import httpx
import pytest

import env_data_mcp.sources.tropomi._query as _query_mod
from env_data_mcp.sources.tropomi._query import _get_variable_info
from env_data_mcp.sources.tropomi.constants import _CATALOG_URL_PREFIX

# ---------------------------------------------------------------------------
# mock data
# ---------------------------------------------------------------------------

_NRTI_URL = f"{_CATALOG_URL_PREFIX}NRTI/catalog.json"
_OFFL_URL = f"{_CATALOG_URL_PREFIX}OFFL/catalog.json"
_RPRO_URL = f"{_CATALOG_URL_PREFIX}RPRO/catalog.json"

_NRTI_CATALOG = {
    "links": [
        {
            "href": "https://meeo-s5p.s3.amazonaws.com/COGT/NRTI/L2__NO2___/catalog.json",
            "title": "Nitrogen Dioxide",
        },
    ]
}

_OFFL_CATALOG = {
    "links": [
        {
            "href": "https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/L2__CO____/catalog.json",
            "title": "Carbon Monoxide",
        },
        {
            "href": "https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/L2__CH4___/catalog.json",
            "title": "Methane",
        },
        # link without "title" — should be filtered out by _get_variable_info
        {
            "href": "https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/catalog.json",
        },
    ]
}

_RPRO_CATALOG = {
    "links": [
        {
            "href": "https://meeo-s5p.s3.amazonaws.com/COGT/RPRO/L2__O3____/catalog.json",
            "title": "Ozone",
        },
    ]
}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_variable_info_cache():
    """Reset the module-level cache before and after every test."""
    _query_mod._VARIABLE_INFO_CACHE.clear()
    yield
    _query_mod._VARIABLE_INFO_CACHE.clear()


def _add_catalog_mocks(httpx_mock) -> None:
    """Register the three catalog HTTP responses."""
    httpx_mock.add_response(url=_NRTI_URL, json=_NRTI_CATALOG)
    httpx_mock.add_response(url=_OFFL_URL, json=_OFFL_CATALOG)
    httpx_mock.add_response(url=_RPRO_URL, json=_RPRO_CATALOG)


# ---------------------------------------------------------------------------
# _get_variable_info
# ---------------------------------------------------------------------------


def test_get_variable_info(httpx_mock):
    """Tests expected results are returned with proper structure and values."""
    _add_catalog_mocks(httpx_mock)

    var_info = _get_variable_info()

    # 4 variables total: 1 from NRTI, 2 from OFFL (title-less link excluded), 1 from RPRO
    assert len(var_info) == 4

    assert "NRTI-L2_NO2" in var_info
    entry = var_info["NRTI-L2_NO2"]
    assert entry["description"] == "Near real-time: Nitrogen Dioxide"
    assert entry["units"] == "mol m-2"
    assert entry["url"] == "https://meeo-s5p.s3.amazonaws.com/COGT/NRTI/L2__NO2___/catalog.json"
    assert entry["product_type"] == "NRTI"
    assert entry["variable_name"] == "L2__NO2___"

    assert "OFFL-L2_CO" in var_info
    entry = var_info["OFFL-L2_CO"]
    assert entry["description"] == "Offline processed: Carbon Monoxide"
    assert entry["units"] == "mol m-2"
    assert entry["url"] == "https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/L2__CO____/catalog.json"
    assert entry["product_type"] == "OFFL"
    assert entry["variable_name"] == "L2__CO____"

    assert "OFFL-L2_CH4" in var_info
    entry = var_info["OFFL-L2_CH4"]
    assert entry["description"] == "Offline processed: Methane"
    assert entry["units"] == "ppb"
    assert entry["url"] == "https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/L2__CH4___/catalog.json"
    assert entry["product_type"] == "OFFL"
    assert entry["variable_name"] == "L2__CH4___"

    assert "RPRO-L2_O3" in var_info
    entry = var_info["RPRO-L2_O3"]
    assert entry["description"] == "Reprocessed: Ozone"
    assert entry["units"] == "DU"
    assert entry["url"] == "https://meeo-s5p.s3.amazonaws.com/COGT/RPRO/L2__O3____/catalog.json"
    assert entry["product_type"] == "RPRO"
    assert entry["variable_name"] == "L2__O3____"


def test_get_variable_info_raises_http_status_error(httpx_mock):
    """Tests that HTTP status errors propagate."""
    httpx_mock.add_response(url=_NRTI_URL, status_code=503)

    with pytest.raises(httpx.HTTPStatusError):
        _get_variable_info()


def test_get_variable_info_uses_cache(httpx_mock):
    """Tests that repeat calls use cached variable info."""
    _add_catalog_mocks(httpx_mock)

    first = _get_variable_info()
    second = _get_variable_info()

    # The same dict object is returned on both calls — the second call hit the cache,
    assert first is second
