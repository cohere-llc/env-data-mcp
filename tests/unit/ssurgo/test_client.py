"""Unit tests for _parse_xml, _fetch_sda, and consistency checks."""

from __future__ import annotations

from env_data_mcp.sources.ssurgo._client import _fetch_sda, _parse_xml
from env_data_mcp.sources.ssurgo.constants import (
    DEFAULT_AREA_SUMMARY_VARIABLES,
    DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    DEFAULT_PARENT_MATERIAL_VARIABLES,
    DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    DEFAULT_SOIL_PROFILE_VARIABLES,
    DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
)

from .conftest import _SDA_URL, EMPTY_XML, YAKIMA_XML

# ---------------------------------------------------------------------------
# _parse_xml tests (no HTTP needed)
# ---------------------------------------------------------------------------


def test_parse_xml_returns_two_rows():
    records = _parse_xml(YAKIMA_XML)
    assert len(records) == 2


def test_parse_xml_column_values():
    records = _parse_xml(YAKIMA_XML)
    assert records[0]["mukey"] == "2764208"
    assert records[0]["compname"] == "Ritzville"
    assert records[0]["hzdepb_r"] == "18"
    assert records[0]["sandtotal_r"] == "19"


def test_parse_xml_second_row():
    records = _parse_xml(YAKIMA_XML)
    assert records[1]["hzdepb_r"] == "91"
    assert records[1]["ph1to1h2o_r"] == "7.1"


def test_parse_xml_empty_returns_empty_list():
    records = _parse_xml(EMPTY_XML)
    assert records == []


def test_parse_xml_malformed_returns_empty_list():
    records = _parse_xml("not xml at all <<<")
    assert records == []


# ---------------------------------------------------------------------------
# _fetch_sda tests
# ---------------------------------------------------------------------------


def test_fetch_sda_returns_records(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=YAKIMA_XML)
    records, latency = _fetch_sda("SELECT mukey FROM mapunit WHERE 1=1")
    assert len(records) == 2
    assert isinstance(latency, float)
    assert latency >= 0.0


def test_fetch_sda_non_us_returns_empty(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=EMPTY_XML)
    records, latency = _fetch_sda("SELECT mukey FROM mapunit WHERE 1=1")
    assert records == []


# ---------------------------------------------------------------------------
# Consistency: all default variable/rule lists must be non-empty
# ---------------------------------------------------------------------------


def test_all_default_variable_lists_are_non_empty():
    assert len(DEFAULT_SOIL_PROFILE_VARIABLES) > 0
    assert len(DEFAULT_AREA_SUMMARY_VARIABLES) > 0
    assert len(DEFAULT_SUBSURFACE_BARRIERS_VARIABLES) > 0
    assert len(DEFAULT_SEASONAL_HYDROLOGY_VARIABLES) > 0
    assert len(DEFAULT_SOIL_SUITABILITY_RULE_NAMES) > 0
    assert len(DEFAULT_ECOLOGICAL_SITE_VARIABLES) > 0
    assert len(DEFAULT_PARENT_MATERIAL_VARIABLES) > 0
    assert len(DEFAULT_SOIL_TEMPERATURE_VARIABLES) > 0
