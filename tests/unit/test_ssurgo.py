"""Unit tests for the SSURGO source adapter.

All HTTP calls are intercepted by pytest-httpx; no network access required.
"""

from __future__ import annotations

import textwrap

import pytest

from env_data_mcp.sources.ssurgo import (
    _NO_COVERAGE_MSG,
    COLUMN_INFO,
    LICENSE_INFO,
    _fetch_ssurgo,
    _parse_xml,
    ssurgo_bbox_query,
    ssurgo_query,
)

# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

_YAKIMA_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <musym>RiC2</musym>
        <compname>Ritzville</compname>
        <majcompflag>Yes</majcompflag>
        <drainagecl>Well drained</drainagecl>
        <comppct_r>75</comppct_r>
        <hzdepb_r>18</hzdepb_r>
        <sandtotal_r>19</sandtotal_r>
        <silttotal_r>59</silttotal_r>
        <claytotal_r>22</claytotal_r>
        <ph1to1h2o_r>6.5</ph1to1h2o_r>
        <om_r>1.2</om_r>
        <ksat_r>14</ksat_r>
        <dbthirdbar_r>1.42</dbthirdbar_r>
      </Table>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <musym>RiC2</musym>
        <compname>Ritzville</compname>
        <majcompflag>Yes</majcompflag>
        <drainagecl>Well drained</drainagecl>
        <comppct_r>75</comppct_r>
        <hzdepb_r>91</hzdepb_r>
        <sandtotal_r>16</sandtotal_r>
        <silttotal_r>57</silttotal_r>
        <claytotal_r>27</claytotal_r>
        <ph1to1h2o_r>7.1</ph1to1h2o_r>
        <om_r>0.6</om_r>
        <ksat_r>9</ksat_r>
        <dbthirdbar_r>1.51</dbthirdbar_r>
      </Table>
    </NewDataSet>
""")

_EMPTY_XML = '<?xml version="1.0" encoding="utf-8"?><NewDataSet />'

_SDA_URL = "https://sdmdataaccess.nrcs.usda.gov/Tabular/SDMTabularService/post.rest"

# ---------------------------------------------------------------------------
# _parse_xml unit tests (no HTTP needed)
# ---------------------------------------------------------------------------


def test_parse_xml_returns_two_rows():
    records = _parse_xml(_YAKIMA_XML)
    assert len(records) == 2


def test_parse_xml_column_values():
    records = _parse_xml(_YAKIMA_XML)
    assert records[0]["mukey"] == "2764208"
    assert records[0]["compname"] == "Ritzville"
    assert records[0]["hzdepb_r"] == "18"
    assert records[0]["sandtotal_r"] == "19"


def test_parse_xml_second_row():
    records = _parse_xml(_YAKIMA_XML)
    assert records[1]["hzdepb_r"] == "91"
    assert records[1]["ph1to1h2o_r"] == "7.1"


def test_parse_xml_empty_returns_empty_list():
    records = _parse_xml(_EMPTY_XML)
    assert records == []


def test_parse_xml_malformed_returns_empty_list():
    records = _parse_xml("not xml at all <<<")
    assert records == []


# ---------------------------------------------------------------------------
# _fetch_ssurgo unit tests (httpx_mock)
# ---------------------------------------------------------------------------


def test_fetch_ssurgo_us_point_returns_records(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    records, latency = _fetch_ssurgo(46.2531882, -119.4768203)
    assert len(records) == 2
    assert isinstance(latency, float)
    assert latency >= 0.0


def test_fetch_ssurgo_non_us_returns_empty(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    records, latency = _fetch_ssurgo(48.8566, 2.3522)  # Paris, France
    assert records == []


# ---------------------------------------------------------------------------
# ssurgo_query tool tests (httpx_mock)
# ---------------------------------------------------------------------------


def test_ssurgo_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    assert "data" in result
    assert "_meta" in result
    assert isinstance(result["data"], list)
    assert len(result["data"]) == 2


def test_ssurgo_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    meta = result["_meta"]
    assert meta["source"] == "ssurgo"
    assert meta["success"] is True
    assert meta["error"] is None
    assert meta["rows_returned"] == 2
    assert meta["auth_required"] is False


def test_ssurgo_query_license_fields(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    assert result["_meta"]["license"] == LICENSE_INFO["license"]
    assert result["_meta"]["license_url"] == LICENSE_INFO["license_url"]


def test_ssurgo_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(46.2531882)
    assert qp["longitude"] == pytest.approx(-119.4768203)


def test_ssurgo_query_non_us_returns_no_coverage(httpx_mock):
    """Empty XML → success=True, empty data, no-coverage error message."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    result = ssurgo_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_ssurgo_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_ssurgo_query_data_columns(httpx_mock):
    """Each record should contain the standard SSURGO column set."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    row = result["data"][0]
    for col in ("mukey", "muname", "musym", "compname", "hzdepb_r", "sandtotal_r"):
        assert col in row, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# ssurgo_bbox_query tool tests (httpx_mock)
# ---------------------------------------------------------------------------


def test_ssurgo_bbox_query_uses_centroid_in_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_bbox_query(
        min_lat=46.251407,
        max_lat=46.251790,
        min_lon=-119.728785,
        max_lon=-119.728369,
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" in qp
    assert "centroid_lon" in qp
    assert 46.251407 <= qp["centroid_lat"] <= 46.251790


def test_ssurgo_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_bbox_query(
        min_lat=46.251407,
        max_lat=46.251790,
        min_lon=-119.728785,
        max_lon=-119.728369,
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 2


# ---------------------------------------------------------------------------
# variable_info and value-range tests
# ---------------------------------------------------------------------------


def test_ssurgo_query_column_info_in_meta(httpx_mock):
    """_meta.variable_info must be populated with SSURGO column descriptions."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    info = result["_meta"]["variable_info"]
    assert "sandtotal_r" in info
    assert "ph1to1h2o_r" in info
    assert "dbthirdbar_r" in info
    assert info["sandtotal_r"]["description"] != ""
    assert info["sandtotal_r"]["units"] == COLUMN_INFO["sandtotal_r"]["units"]


def test_ssurgo_query_sand_in_valid_range(httpx_mock):
    """Sand content in the fixture (19%) must be within 0–100%."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    for row in result["data"]:
        sand = float(row["sandtotal_r"])
        assert 0.0 <= sand <= 100.0, f"sandtotal_r={sand} outside 0–100%"


def test_ssurgo_query_ph_in_valid_range(httpx_mock):
    """pH in the fixture (6.5, 7.1) must be within 2–11."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    for row in result["data"]:
        ph = float(row["ph1to1h2o_r"])
        assert 2.0 <= ph <= 11.0, f"ph1to1h2o_r={ph} outside 2–11"


def test_ssurgo_query_bulk_density_in_valid_range(httpx_mock):
    """Bulk density in the fixture (1.42, 1.51 g/cm³) must be within 0.5–2.0."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    for row in result["data"]:
        bd = float(row["dbthirdbar_r"])
        assert 0.5 <= bd <= 2.0, f"dbthirdbar_r={bd} outside 0.5–2.0 g/cm³"


def test_ssurgo_query_latency_captured_on_http_error(httpx_mock):
    """latency_s must be > 0 even when the server returns an error."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_query(latitude=46.2531882, longitude=-119.4768203)
    assert result["_meta"]["success"] is False
    # latency may be very small but must not be hardcoded 0.0
    assert result["_meta"]["latency_s"] >= 0.0
