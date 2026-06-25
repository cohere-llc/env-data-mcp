"""Unit tests for the TROPOMI _query module.

All HTTP calls are mocked via ``pytest-httpx``; no network access required.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx
import pytest

import env_data_mcp.sources.tropomi._query as _query_mod
from env_data_mcp.sources.tropomi._query import _get_s3_file_paths, _get_variable_info
from env_data_mcp.sources.tropomi.constants import _AWS_URL, _CDSE_ODATA_URL

# ---------------------------------------------------------------------------
# mock data — catalog
# ---------------------------------------------------------------------------

_NRTI_URL = f"{_AWS_URL}COGT/NRTI/catalog.json"
_OFFL_URL = f"{_AWS_URL}COGT/OFFL/catalog.json"
_RPRO_URL = f"{_AWS_URL}COGT/RPRO/catalog.json"

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
        {
            "href": "https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/L2__O3____/catalog.json",
            "title": "Ozone",
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
# mock data — S3 listings (COGT variable name discovery)
# ---------------------------------------------------------------------------

_S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"

# Maps (product_type, folder) → COGT variable name embedded in the .tif filename.
# Source: https://github.com/Sentinel-5P/data-on-s3/blob/master/DocsForAws/Sentinel5P_Description.md
_COGT_VAR_NAMES: dict[tuple[str, str], str] = {
    ("NRTI", "L2__NO2___"): "nitrogendioxide_tropospheric_column",
    ("OFFL", "L2__CO____"): "carbonmonoxide_total_column",
    ("OFFL", "L2__CH4___"): "methane_mixing_ratio",
    ("OFFL", "L2__O3____"): "ozone_total_vertical_column",
    ("RPRO", "L2__O3____"): "ozone_total_vertical_column",
}

_CDSE_URL_RE = re.compile(re.escape(_CDSE_ODATA_URL))

_CDSE_RESPONSE = {
    "value": [
        {
            "S3Path": "/OFFL/L2__O3____/2024/01/03/S5P_OFFL_L2__O3_____20240103T000105_20240103T000605_00001_01_010302_20240103T015502.nc"  # noqa: E501
        },
        {
            "S3Path": "/OFFL/L2__O3____/2024/01/04/S5P_OFFL_L2__O3_____20240104T000105_20240104T000605_00002_01_010302_20240104T015502.nc"  # noqa: E501
        },
    ]
}


def _s3_listing_url(product_type: str, folder: str) -> str:
    """Build the exact URL httpx sends for an S3 ListObjectsV2 request."""
    prefix = quote(f"COGT/{product_type}/{folder}/", safe="")
    return f"https://meeo-s5p.s3.amazonaws.com/?list-type=2&prefix={prefix}&max-keys=4"


def _s3_listing_xml(product_type: str, folder: str, cogt_var: str) -> str:
    """Build a minimal S3 ListBucketResult XML response."""
    key = (
        f"COGT/{product_type}/{folder}/2020/01/01/"
        f"S5P_{product_type}_{folder}_20200101T000000_20200101T000500_"
        f"00000_01_010302_20200101T010000_PRODUCT_{cogt_var}_4326.tif"
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<ListBucketResult xmlns="{_S3_NS}">'
        f"<KeyCount>1</KeyCount><MaxKeys>2</MaxKeys><IsTruncated>false</IsTruncated>"
        f"<Contents><Key>{key}</Key></Contents>"
        f"</ListBucketResult>"
    )


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
    """Register catalog JSON and S3 listing responses for all mock variables."""
    httpx_mock.add_response(url=_NRTI_URL, json=_NRTI_CATALOG)
    httpx_mock.add_response(url=_OFFL_URL, json=_OFFL_CATALOG)
    httpx_mock.add_response(url=_RPRO_URL, json=_RPRO_CATALOG)
    for (product_type, folder), cogt_var in _COGT_VAR_NAMES.items():
        httpx_mock.add_response(
            url=_s3_listing_url(product_type, folder),
            text=_s3_listing_xml(product_type, folder, cogt_var),
        )


# ---------------------------------------------------------------------------
# _get_variable_info
# ---------------------------------------------------------------------------


def test_get_variable_info(httpx_mock):
    """Tests expected results are returned with proper structure and values."""
    _add_catalog_mocks(httpx_mock)

    var_info = _get_variable_info()

    # 5 variables: 1 NRTI, 3 OFFL (title-less link excluded), 1 RPRO
    assert len(var_info) == 5

    assert "NRTI-L2_NO2" in var_info
    entry = var_info["NRTI-L2_NO2"]
    assert entry["description"] == "Near real-time: Nitrogen Dioxide"
    assert entry["units"] == "mol m-2"
    assert entry["url"] == "https://meeo-s5p.s3.amazonaws.com/COGT/NRTI/L2__NO2___/catalog.json"
    assert entry["product_type"] == "NRTI"
    assert entry["variable_folder"] == "L2__NO2___"
    assert entry["cogt_name"] == "nitrogendioxide_tropospheric_column"

    assert "OFFL-L2_CO" in var_info
    entry = var_info["OFFL-L2_CO"]
    assert entry["description"] == "Offline processed: Carbon Monoxide"
    assert entry["units"] == "mol m-2"
    assert entry["url"] == "https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/L2__CO____/catalog.json"
    assert entry["product_type"] == "OFFL"
    assert entry["variable_folder"] == "L2__CO____"
    assert entry["cogt_name"] == "carbonmonoxide_total_column"

    assert "OFFL-L2_CH4" in var_info
    entry = var_info["OFFL-L2_CH4"]
    assert entry["description"] == "Offline processed: Methane"
    assert entry["units"] == "ppb"
    assert entry["variable_folder"] == "L2__CH4___"
    assert entry["cogt_name"] == "methane_mixing_ratio"

    assert "OFFL-L2_O3" in var_info
    entry = var_info["OFFL-L2_O3"]
    assert entry["description"] == "Offline processed: Ozone"
    assert entry["units"] == "DU"
    assert entry["variable_folder"] == "L2__O3____"
    assert entry["cogt_name"] == "ozone_total_vertical_column"

    assert "RPRO-L2_O3" in var_info
    entry = var_info["RPRO-L2_O3"]
    assert entry["description"] == "Reprocessed: Ozone"
    assert entry["units"] == "DU"
    assert entry["url"] == "https://meeo-s5p.s3.amazonaws.com/COGT/RPRO/L2__O3____/catalog.json"
    assert entry["product_type"] == "RPRO"
    assert entry["variable_folder"] == "L2__O3____"
    assert entry["cogt_name"] == "ozone_total_vertical_column"


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
    # making no additional HTTP requests (all mocks were consumed by the first call).
    assert first is second


# ---------------------------------------------------------------------------
# _get_s3_file_paths
# ---------------------------------------------------------------------------


def test_get_s3_file_paths_returns_results(httpx_mock):
    """Tests results from _get_s3_file_paths() have the expected structure."""
    _add_catalog_mocks(httpx_mock)
    httpx_mock.add_response(url=_CDSE_URL_RE, json=_CDSE_RESPONSE)

    results = _get_s3_file_paths(
        "OFFL-L2_O3",
        "2024-01-03",
        "2024-01-05",
        "geography'SRID=4326;POINT(-116.4856 33.8434)'",
    )

    assert len(results) == 2
    for path in results:
        posix_path = PurePosixPath(path)
        assert len(posix_path.parts) > 1
        assert posix_path.suffix == ".nc"


def test_get_s3_file_paths_invalid_variable_raises(httpx_mock):
    """Tests that an unrecognised variable name raises ValueError."""
    _add_catalog_mocks(httpx_mock)

    with pytest.raises(ValueError, match="Invalid TROPOMI variable name"):
        _get_s3_file_paths(
            "OFFL-L2_INVALID",
            "2024-01-03",
            "2024-01-05",
            "geography'SRID=4326;POINT(-116.4856 33.8434)'",
        )


def test_get_s3_file_paths_http_error_propagates(httpx_mock):
    """Tests that CDSE HTTP errors propagate as HTTPStatusError."""
    _add_catalog_mocks(httpx_mock)
    httpx_mock.add_response(url=_CDSE_URL_RE, status_code=503)

    with pytest.raises(httpx.HTTPStatusError):
        _get_s3_file_paths(
            "OFFL-L2_O3",
            "2024-01-03",
            "2024-01-05",
            "geography'SRID=4326;POINT(-116.4856 33.8434)'",
        )


def test_get_s3_file_paths_empty_results(httpx_mock):
    """Tests that an empty CDSE response returns an empty list."""
    _add_catalog_mocks(httpx_mock)
    httpx_mock.add_response(url=_CDSE_URL_RE, json={"value": []})

    results = _get_s3_file_paths(
        "OFFL-L2_O3",
        "2024-01-03",
        "2024-01-05",
        "geography'SRID=4326;POINT(-116.4856 33.8434)'",
    )

    assert results == []


def test_get_s3_file_paths_paginates(httpx_mock):
    """Tests that results spanning multiple CDSE pages are all collected.

    The loop continues as long as a page returns exactly ``page_size`` (1000)
    results, and stops when a page returns fewer.
    """
    _add_catalog_mocks(httpx_mock)

    _PAGE_SIZE = 1000
    page1 = [
        {"S3Path": f"/OFFL/L2__O3____/2024/01/01/S5P_OFFL_variable_{i:05d}.nc"}
        for i in range(_PAGE_SIZE)
    ]
    page2 = [
        {"S3Path": f"/OFFL/L2__O3____/2024/01/02/S5P_OFFL_variable_{i:05d}.nc"} for i in range(3)
    ]
    # pytest-httpx returns registered responses in FIFO order for the same URL.
    httpx_mock.add_response(url=_CDSE_URL_RE, json={"value": page1})
    httpx_mock.add_response(url=_CDSE_URL_RE, json={"value": page2})

    results = _get_s3_file_paths(
        "OFFL-L2_O3",
        "2024-01-03",
        "2024-01-05",
        "geography'SRID=4326;POINT(-116.4856 33.8434)'",
    )

    assert len(results) == _PAGE_SIZE + 3
    assert results[0] == "/OFFL/L2__O3____/2024/01/01/S5P_OFFL_variable_00000.nc"
    assert results[_PAGE_SIZE] == "/OFFL/L2__O3____/2024/01/02/S5P_OFFL_variable_00000.nc"
