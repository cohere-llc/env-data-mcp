"""Unit tests for _parse_xml, _fetch_sda, and consistency checks."""

from __future__ import annotations

import re
import textwrap
from http import HTTPStatus

import pytest

from env_data_mcp.sources.ssurgo._client import (
    _fetch_mukey_geometries,
    _fetch_sda,
    _gml2_to_geojson,
    _parse_gml2_coords,
    _parse_xml,
)
from env_data_mcp.sources.ssurgo._constants import (
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
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
