"""Unit tests for _parse_xml, _fetch_sda, and consistency checks."""

from __future__ import annotations

import re
import textwrap

import pdfplumber
import pytest

import env_data_mcp.sources.ssurgo._client as _ssurgo_client
from env_data_mcp.sources.ssurgo._client import (
    _COLUMN_TABLE_CACHE,
    _PDF_URL,
    _extract_uom,
    _fetch_mukey_geometries,
    _fetch_sda,
    _get_column_table_map,
    _get_variable_info,
    _gml2_to_geojson,
    _load_column_metadata,
    _parse_gml2_coords,
    _parse_xml,
)
from env_data_mcp.sources.ssurgo.constants import (
    DEFAULT_AREA_SUMMARY_VARIABLES,
    DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    DEFAULT_PARENT_MATERIAL_VARIABLES,
    DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    DEFAULT_SOIL_PROFILE_VARIABLES,
    DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    _QueryType,
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


# ---------------------------------------------------------------------------
# _extract_uom tests (pure function, no network)
# ---------------------------------------------------------------------------


def test_extract_uom_simple_unit():
    assert _extract_uom("10 100 percent") == "percent"


def test_extract_uom_strips_domain_suffix():
    # Domain names contain underscores and appear last; strip before returning UOM
    assert _extract_uom("10 100 percent domain_name") == "percent"


def test_extract_uom_all_numeric_returns_empty():
    assert _extract_uom("10 25 100") == ""


def test_extract_uom_empty_string():
    assert _extract_uom("") == ""


def test_extract_uom_complex_unit():
    # Units like "g/cm3" or "cmol(+)/kg" should be returned as-is
    assert _extract_uom("4 g/cm3") == "g/cm3"


def test_extract_uom_only_domain_name_returns_empty():
    assert _extract_uom("domain_name") == ""


# ---------------------------------------------------------------------------
# _parse_col_metadata_pdf tests (monkeypatched pdfplumber)
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
    from env_data_mcp.sources.ssurgo._client import _parse_col_metadata_pdf

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
    from env_data_mcp.sources.ssurgo._client import _parse_col_metadata_pdf

    monkeypatch.setattr(pdfplumber, "open", lambda *a, **kw: _make_fake_pdf([""]))
    result = _parse_col_metadata_pdf(b"fake bytes")
    assert result == {}


# ---------------------------------------------------------------------------
# _load_column_metadata download path tests
# ---------------------------------------------------------------------------


def test_load_column_metadata_fetches_and_parses_pdf(httpx_mock, monkeypatch):
    monkeypatch.setattr(_ssurgo_client, "_PDF_COL_METADATA_LOADED", False)
    _ssurgo_client._PDF_COL_METADATA_CACHE.clear()
    monkeypatch.setattr(
        _ssurgo_client,
        "_parse_col_metadata_pdf",
        lambda b: {"mapunit": {"musym": {"label": "Map Unit Symbol", "units": ""}}},
    )
    httpx_mock.add_response(method="GET", url=_PDF_URL, content=b"fake pdf bytes")
    result = _load_column_metadata()
    assert "mapunit" in result


def test_load_column_metadata_http_error_returns_empty(httpx_mock, monkeypatch):
    monkeypatch.setattr(_ssurgo_client, "_PDF_COL_METADATA_LOADED", False)
    _ssurgo_client._PDF_COL_METADATA_CACHE.clear()
    httpx_mock.add_response(method="GET", url=_PDF_URL, status_code=500)
    result = _load_column_metadata()
    assert result == {}


# ---------------------------------------------------------------------------
# _get_column_table_map rebuild tests
# ---------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_get_column_table_map_rebuilds_cache_from_sda(httpx_mock):
    from .conftest import _SDA_URL, TABLE_SCHEMA_XMLS

    # Clear cache that was pre-seeded by the autouse fixture
    _COLUMN_TABLE_CACHE.clear()

    # Register a response only for mapunit; remaining tables will raise (caught
    # by except Exception: pass in _get_column_table_map, covering lines 153-154)
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=TABLE_SCHEMA_XMLS["mapunit"])

    result = _get_column_table_map()
    # mapunit schema has "mukey" and "muname"
    assert result.get("mukey") == "mapunit"
    assert result.get("muname") == "mapunit"


# ---------------------------------------------------------------------------
# _get_variable_info error path tests
# ---------------------------------------------------------------------------


def test_get_variable_info_all_tables_raise_reraises_last(monkeypatch):
    # The autouse fixture pre-seeds the cache; clear it so the function runs fully
    _ssurgo_client._VARIABLE_INFO_CACHE.pop(_QueryType.SOIL_PROFILE, None)

    def _always_raise(table):
        raise ConnectionError(f"no response for {table}")

    monkeypatch.setattr(_ssurgo_client, "_sda_table_columns", _always_raise)
    with pytest.raises(ConnectionError):
        _get_variable_info(_QueryType.SOIL_PROFILE)


def test_get_variable_info_uses_pdf_metadata_when_available(monkeypatch):
    """Covers entry.update(pdf_meta) when _PDF_COL_METADATA_CACHE has data."""
    _ssurgo_client._VARIABLE_INFO_CACHE.pop(_QueryType.SOIL_PROFILE, None)
    # Pre-populate the PDF metadata cache with a label/units entry for musym
    _ssurgo_client._PDF_COL_METADATA_CACHE["mapunit"] = {
        "musym": {"label": "Map Unit Symbol", "units": ""}
    }

    def _fake_table_columns(table: str) -> list[str]:
        if table == "mapunit":
            return ["mukey", "musym"]
        raise ConnectionError("not mocked")

    monkeypatch.setattr(_ssurgo_client, "_sda_table_columns", _fake_table_columns)
    result = _get_variable_info(_QueryType.SOIL_PROFILE)
    assert "musym" in result
    assert result["musym"].get("label") == "Map Unit Symbol"


def test_get_variable_info_no_tables_configured_raises_runtime_error(monkeypatch):
    # The autouse fixture pre-seeds the cache; clear it so the function runs fully
    _ssurgo_client._VARIABLE_INFO_CACHE.pop(_QueryType.SOIL_PROFILE, None)
    orig = _ssurgo_client._AVAIL_SQL_TABLES
    monkeypatch.setattr(_ssurgo_client, "_AVAIL_SQL_TABLES", {**orig, _QueryType.SOIL_PROFILE: ()})
    with pytest.raises(RuntimeError, match="No tables configured"):
        _get_variable_info(_QueryType.SOIL_PROFILE)


# ---------------------------------------------------------------------------
# _parse_gml2_coords tests (pure function)
# ---------------------------------------------------------------------------


def test_parse_gml2_coords_valid_pairs():
    result = _parse_gml2_coords("46.0,-119.5 46.1,-119.4")
    assert result == [[-119.5, 46.0], [-119.4, 46.1]]


def test_parse_gml2_coords_empty_string():
    assert _parse_gml2_coords("") == []


def test_parse_gml2_coords_invalid_numeric_values():
    # Non-numeric tokens should be skipped gracefully
    result = _parse_gml2_coords("bad,notanumber valid,pair")
    assert result == []


def test_parse_gml2_coords_single_token_no_comma():
    # A pair with only one element (no comma) has len < 2 and is skipped
    assert _parse_gml2_coords("46.0") == []


# ---------------------------------------------------------------------------
# _gml2_to_geojson tests
# ---------------------------------------------------------------------------

_GML2_SINGLE = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <wfs:FeatureCollection
      xmlns:wfs="http://www.opengis.net/wfs"
      xmlns:ms="http://mapserver.gis.umn.edu/mapserver"
      xmlns:gml="http://www.opengis.net/gml">
      <gml:featureMember>
        <ms:mapunitpoly>
          <ms:mukey>12345</ms:mukey>
          <gml:Polygon>
            <gml:outerBoundaryIs>
              <gml:LinearRing>
                <gml:coordinates>46,-119 46,-120 47,-120 47,-119 46,-119</gml:coordinates>
              </gml:LinearRing>
            </gml:outerBoundaryIs>
          </gml:Polygon>
        </ms:mapunitpoly>
      </gml:featureMember>
    </wfs:FeatureCollection>
    """
)


def test_gml2_to_geojson_invalid_xml_returns_empty():
    assert _gml2_to_geojson("not valid xml <<<", {"12345"}) == {}


def test_gml2_to_geojson_mukey_not_in_filter_returns_empty():
    assert _gml2_to_geojson(_GML2_SINGLE, {"99999"}) == {}


def test_gml2_to_geojson_single_polygon():
    result = _gml2_to_geojson(_GML2_SINGLE, {"12345"})
    assert "12345" in result
    assert result["12345"]["type"] == "Polygon"
    assert len(result["12345"]["coordinates"][0]) == 5


def test_gml2_to_geojson_polygon_with_inner_boundary_hole():
    """A polygon with an innerBoundaryIs element exercises lines 298-299."""
    gml = textwrap.dedent(
        """\
        <?xml version="1.0"?>
        <wfs:FeatureCollection
          xmlns:wfs="http://www.opengis.net/wfs"
          xmlns:ms="http://mapserver.gis.umn.edu/mapserver"
          xmlns:gml="http://www.opengis.net/gml">
          <gml:featureMember>
            <ms:mapunitpoly>
              <ms:mukey>55555</ms:mukey>
              <gml:Polygon>
                <gml:outerBoundaryIs>
                  <gml:LinearRing>
                    <gml:coordinates>46,-120 46,-119 47,-119 47,-120 46,-120</gml:coordinates>
                  </gml:LinearRing>
                </gml:outerBoundaryIs>
                <gml:innerBoundaryIs>
                  <gml:LinearRing>
                    <gml:coordinates>46,-119 47,-119 46,-120 46,-119</gml:coordinates>
                  </gml:LinearRing>
                </gml:innerBoundaryIs>
              </gml:Polygon>
            </ms:mapunitpoly>
          </gml:featureMember>
        </wfs:FeatureCollection>
        """
    )
    result = _gml2_to_geojson(gml, {"55555"})
    assert "55555" in result
    geom = result["55555"]
    assert geom["type"] == "Polygon"
    # coordinates[0] is outer ring, coordinates[1] is the hole
    assert len(geom["coordinates"]) == 2


def test_gml2_to_geojson_multipolygon_when_two_features_same_mukey():
    # A second polygon for the same mukey should produce MultiPolygon
    extra = textwrap.dedent(
        """\
          <gml:featureMember>
            <ms:mapunitpoly>
              <ms:mukey>12345</ms:mukey>
              <gml:Polygon>
                <gml:outerBoundaryIs>
                  <gml:LinearRing>
                    <gml:coordinates>47,-118 47,-119 48,-119 48,-118 47,-118</gml:coordinates>
                  </gml:LinearRing>
                </gml:outerBoundaryIs>
              </gml:Polygon>
            </ms:mapunitpoly>
          </gml:featureMember>
        </wfs:FeatureCollection>
        """
    )
    gml = _GML2_SINGLE.replace("</wfs:FeatureCollection>", extra)
    result = _gml2_to_geojson(gml, {"12345"})
    assert result["12345"]["type"] == "MultiPolygon"


# ---------------------------------------------------------------------------
# _fetch_mukey_geometries tests (direct, bypasses tools-level monkeypatch)
# ---------------------------------------------------------------------------


def test_fetch_mukey_geometries_empty_mukeys_returns_empty():
    assert _fetch_mukey_geometries([], (-120, 46, -119, 47)) == {}


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_fetch_mukey_geometries_http_error_returns_empty(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"https://sdmdataaccess\.sc\.egov\.usda\.gov/.*"),
        status_code=500,
    )
    result = _fetch_mukey_geometries(["12345"], (-120, 46, -119, 47))
    assert result == {}


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_fetch_mukey_geometries_returns_geometry_from_wfs(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"https://sdmdataaccess\.sc\.egov\.usda\.gov/.*"),
        text=_GML2_SINGLE,
    )
    result = _fetch_mukey_geometries(["12345"], (-120.0, 46.0, -119.0, 47.0))
    assert "12345" in result
    assert result["12345"]["type"] == "Polygon"
