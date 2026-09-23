"""Unit tests for the TROPOMI disk-backed variable cache.

The live-fetch path is exercised with mocked HTTP; the disk-backed lookup is
exercised against a temporary JSON file substituted for the shipped
``variables.json`` via ``monkeypatch``.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from env_data_mcp.sources.tropomi import _var_cache
from env_data_mcp.sources.tropomi._constants import AWS_URL, ProductType

# ---------------------------------------------------------------------------
# Catalog + S3 listing mock data
# ---------------------------------------------------------------------------

_NRTI_URL = f"{AWS_URL}COGT/NRTI/catalog.json"
_OFFL_URL = f"{AWS_URL}COGT/OFFL/catalog.json"
_RPRO_URL = f"{AWS_URL}COGT/RPRO/catalog.json"

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
        # link without "title" — should be filtered out by _fetch_full_variable_info_live
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

_S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"

# Maps (product_type, folder) → COGT variable name embedded in the .tif filename.
_COGT_VAR_NAMES: dict[tuple[str, str], str] = {
    ("NRTI", "L2__NO2___"): "nitrogendioxide_tropospheric_column",
    ("OFFL", "L2__CO____"): "carbonmonoxide_total_column",
    ("OFFL", "L2__CH4___"): "methane_mixing_ratio",
    ("OFFL", "L2__O3____"): "ozone_total_vertical_column",
    ("RPRO", "L2__O3____"): "ozone_total_vertical_column",
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache():
    """Ensure every test starts with a clean in-memory cache."""
    _var_cache._VARIABLE_INFO_CACHE.clear()
    yield
    _var_cache._VARIABLE_INFO_CACHE.clear()


# ---------------------------------------------------------------------------
# _fetch_full_variable_info_live
# ---------------------------------------------------------------------------


def test_fetch_full_variable_info_live_returns_expected_shape(httpx_mock):
    _add_catalog_mocks(httpx_mock)

    var_info = _var_cache._fetch_full_variable_info_live()

    # 5 variables: 1 NRTI, 3 OFFL (title-less link excluded), 1 RPRO
    assert len(var_info) == 5

    entry = var_info["NRTI-L2_NO2"]
    assert entry.description == "Near real-time: Nitrogen Dioxide"
    assert entry.units == "mol m-2"
    assert entry.product_type == ProductType.NRTI
    assert entry.underscored_name == "L2__NO2___"
    assert entry.cogt_name == "nitrogendioxide_tropospheric_column"

    entry = var_info["OFFL-L2_CH4"]
    assert entry.units == "ppb"
    assert entry.cogt_name == "methane_mixing_ratio"

    entry = var_info["RPRO-L2_O3"]
    assert entry.product_type == ProductType.RPRO
    assert entry.units == "DU"


def test_fetch_full_variable_info_live_propagates_http_errors(httpx_mock):
    httpx_mock.add_response(url=_OFFL_URL, status_code=HTTPStatus.SERVICE_UNAVAILABLE)

    with pytest.raises(httpx.HTTPStatusError):
        _var_cache._fetch_full_variable_info_live()


def test_fetch_all_variable_info_live_returns_json_shape(httpx_mock):
    _add_catalog_mocks(httpx_mock)

    result = _var_cache._fetch_all_variable_info_live()

    entry = result["OFFL-L2_CO"]
    assert set(entry) == {
        "name",
        "description",
        "units",
        "product_type",
        "property_name",
        "underscored_name",
        "cogt_name",
    }
    assert entry["product_type"] == "OFFL"  # StrEnum value, not enum member
    assert entry["units"] == "mol m-2"


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


def test_variable_info_dict_roundtrip():
    original = _var_cache.VariableInfo(
        name="OFFL-L2_O3",
        description="Offline processed: Ozone",
        units="DU",
        product_type=ProductType.OFFL,
        property_name="L2_O3",
        underscored_name="L2__O3____",
        cogt_name="ozone_total_vertical_column",
    )
    dumped = _var_cache._variable_info_to_dict(original)
    restored = _var_cache._variable_info_from_dict(dumped)

    assert dumped["product_type"] == "OFFL"
    assert restored == original
    assert isinstance(restored.product_type, ProductType)


# ---------------------------------------------------------------------------
# _get_full_variable_info (disk-backed)
# ---------------------------------------------------------------------------


def _write_cache_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "variables.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_get_full_variable_info_reads_from_disk(monkeypatch, tmp_path):
    payload = {
        "OFFL-L2_CO": {
            "name": "OFFL-L2_CO",
            "description": "Offline processed: Carbon Monoxide",
            "units": "mol m-2",
            "product_type": "OFFL",
            "property_name": "L2_CO",
            "underscored_name": "L2__CO____",
            "cogt_name": "carbonmonoxide_total_column",
        }
    }
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, payload))

    info = _var_cache.get_full_variable_info()

    assert set(info) == {"OFFL-L2_CO"}
    entry = info["OFFL-L2_CO"]
    assert entry.product_type == ProductType.OFFL
    assert entry.cogt_name == "carbonmonoxide_total_column"


def test_get_full_variable_info_caches_across_calls(monkeypatch, tmp_path):
    """After the first call the on-disk file is not re-read."""
    payload = {
        "OFFL-L2_CO": {
            "name": "OFFL-L2_CO",
            "description": "",
            "units": "mol m-2",
            "product_type": "OFFL",
            "property_name": "L2_CO",
            "underscored_name": "L2__CO____",
            "cogt_name": "carbonmonoxide_total_column",
        }
    }
    path = _write_cache_file(tmp_path, payload)
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", path)

    first = _var_cache.get_full_variable_info()
    path.unlink()  # subsequent calls must not touch disk
    second = _var_cache.get_full_variable_info()

    assert first is second


def test_get_variable_info_flattens_disk_entries(monkeypatch, tmp_path):
    payload = {
        "OFFL-L2_CO": {
            "name": "OFFL-L2_CO",
            "description": "Offline processed: Carbon Monoxide",
            "units": "mol m-2",
            "product_type": "OFFL",
            "property_name": "L2_CO",
            "underscored_name": "L2__CO____",
            "cogt_name": "carbonmonoxide_total_column",
        }
    }
    monkeypatch.setattr(_var_cache, "_VARIABLES_PATH", _write_cache_file(tmp_path, payload))

    result = _var_cache.get_variable_info()

    assert result == {
        "OFFL-L2_CO": {
            "description": "Offline processed: Carbon Monoxide",
            "units": "mol m-2",
        }
    }


# ---------------------------------------------------------------------------
# Shipped variables.json
# ---------------------------------------------------------------------------


def test_shipped_variables_json_is_wellformed():
    """The committed cache loads and every entry has the expected fields."""
    data = _var_cache._load_all_variable_info_from_disk()
    assert data, "shipped variables.json is empty"
    expected_keys = {
        "name",
        "description",
        "units",
        "product_type",
        "property_name",
        "underscored_name",
        "cogt_name",
    }
    for name, entry in data.items():
        assert set(entry) == expected_keys, f"{name} has unexpected keys: {set(entry)}"
        assert entry["product_type"] in {pt.value for pt in ProductType}, (
            f"{name}: bad product_type {entry['product_type']!r}"
        )


def test_shipped_variables_json_covers_default_variables():
    """Every default variable used by the TROPOMI tools is present in the cache."""
    from env_data_mcp.sources.tropomi._constants import DEFAULT_VARIABLES

    data = _var_cache._load_all_variable_info_from_disk()
    missing = [v for v in DEFAULT_VARIABLES if v not in data]
    assert not missing, f"Default variables missing from shipped cache: {missing}"


def test_shipped_variables_json_hydrates_to_dataclass_instances():
    """The shipped cache round-trips through _get_full_variable_info to _VariableInfo."""
    _var_cache._VARIABLE_INFO_CACHE.clear()
    info = _var_cache.get_full_variable_info()
    assert info, "no variables loaded from shipped cache"
    for name, vi in info.items():
        assert isinstance(vi, _var_cache.VariableInfo), f"{name} not a _VariableInfo"
        assert isinstance(vi.product_type, ProductType)


# ---------------------------------------------------------------------------
# get_equivalent_variables
# ---------------------------------------------------------------------------


def _shipped(name: str) -> _var_cache.VariableInfo:
    """Return one hydrated entry from the shipped cache."""
    return _var_cache.get_full_variable_info()[name]


def test_get_equivalent_variables_finds_other_streams():
    """A measurement published by several streams reports the others."""
    equivalents = _var_cache.get_equivalent_variables(_shipped("OFFL-L2_CO"))

    assert [info.name for info in equivalents] == ["RPRO-L2_CO", "NRTI-L2_CO"]


def test_get_equivalent_variables_prefers_reprocessed_stream():
    """The reprocessed stream is offered ahead of the near-real-time one."""
    equivalents = _var_cache.get_equivalent_variables(_shipped("OFFL-L2_CO"))

    assert equivalents[0].product_type is ProductType.RPRO


def test_get_equivalent_variables_excludes_a_different_measurement():
    """NRTI NO2 is a tropospheric column, so it never stands in for the total column."""
    offl_no2 = _shipped("OFFL-L2_NO2")
    equivalents = _var_cache.get_equivalent_variables(offl_no2)

    assert [info.name for info in equivalents] == ["RPRO-L2_NO2"]
    assert _shipped("NRTI-L2_NO2").cogt_name != offl_no2.cogt_name


def test_get_equivalent_variables_none_for_single_stream_measurement():
    """A measurement only one stream publishes has no equivalent."""
    assert _var_cache.get_equivalent_variables(_shipped("OFFL-L2_CH4")) == []


def test_get_equivalent_variables_excludes_the_variable_itself():
    """The requested variable is never offered as its own substitute."""
    offl_co = _shipped("OFFL-L2_CO")

    assert offl_co not in _var_cache.get_equivalent_variables(offl_co)
