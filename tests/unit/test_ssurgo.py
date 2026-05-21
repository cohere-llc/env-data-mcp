"""Unit tests for the SSURGO source adapter (8 query types, 24 MCP tools).

All HTTP calls are intercepted by pytest-httpx; no network access required.
"""

from __future__ import annotations

import textwrap

import pytest

from env_data_mcp.sources.ssurgo import (
    _AREA_SUMMARY_AVAIL_SQL,
    _COLUMN_TABLE_CACHE,
    _ECOLOGICAL_SITE_AVAIL_SQL,
    _NO_COVERAGE_MSG,
    _PARENT_MATERIAL_AVAIL_SQL,
    _SEASONAL_HYDROLOGY_AVAIL_SQL,
    _SOIL_PROFILE_AVAIL_SQL,
    _SOIL_TEMPERATURE_AVAIL_SQL,
    _SUBSURFACE_BARRIERS_AVAIL_SQL,
    _VARIABLE_INFO_CACHE,
    DEFAULT_AREA_SUMMARY_VARIABLES,
    DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    DEFAULT_PARENT_MATERIAL_VARIABLES,
    DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    DEFAULT_SOIL_PROFILE_VARIABLES,
    DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    LICENSE_INFO,
    _fetch_sda,
    _parse_xml,
    ssurgo_area_summary_available_variables,
    ssurgo_area_summary_bbox_query,
    ssurgo_area_summary_query,
    ssurgo_ecological_site_available_variables,
    ssurgo_ecological_site_bbox_query,
    ssurgo_ecological_site_query,
    ssurgo_parent_material_available_variables,
    ssurgo_parent_material_bbox_query,
    ssurgo_parent_material_query,
    ssurgo_seasonal_hydrology_available_variables,
    ssurgo_seasonal_hydrology_bbox_query,
    ssurgo_seasonal_hydrology_query,
    ssurgo_soil_profile_available_variables,
    ssurgo_soil_profile_bbox_query,
    ssurgo_soil_profile_query,
    ssurgo_soil_suitability_available_variables,
    ssurgo_soil_suitability_bbox_query,
    ssurgo_soil_suitability_query,
    ssurgo_soil_temperature_available_variables,
    ssurgo_soil_temperature_bbox_query,
    ssurgo_soil_temperature_query,
    ssurgo_subsurface_barriers_available_variables,
    ssurgo_subsurface_barriers_bbox_query,
    ssurgo_subsurface_barriers_query,
)

_SDA_URL = "https://sdmdataaccess.nrcs.usda.gov/Tabular/SDMTabularService/post.rest"

# Test-time column → table seed data (mirrors the schema queried by
# _get_column_table_map in production; kept here so tests never make a real
# network call just to qualify SELECT columns).
_COLUMN_TABLE_MAP_TEST_DATA: dict[str, str] = {
    # mapunit
    "mukey": "mapunit",
    "muname": "mapunit",
    "musym": "mapunit",
    "mukind": "mapunit",
    "muacres": "mapunit",
    "farmlndcl": "mapunit",
    "mustatus": "mapunit",
    # muaggatt
    "drclassdcd": "muaggatt",
    "drclasswettest": "muaggatt",
    "hydgrpdcd": "muaggatt",
    "aws025wta": "muaggatt",
    "aws050wta": "muaggatt",
    "aws0100wta": "muaggatt",
    "aws0150wta": "muaggatt",
    "soc0_999wta": "muaggatt",
    "nccpi2all": "muaggatt",
    "nccpi3all": "muaggatt",
    "nccpi3corn": "muaggatt",
    "nccpi3soy": "muaggatt",
    "nccpi3cottn": "muaggatt",
    "nccpi3sg": "muaggatt",
    "pctearthmc": "muaggatt",
    "rechargeratemin": "muaggatt",
    "rechargeratemax": "muaggatt",
    "hydricsoflag": "muaggatt",
    "hydricsopcta": "muaggatt",
    "flodfreqdcd": "muaggatt",
    "flodfreqmax": "muaggatt",
    "pondfreqprs": "muaggatt",
    "wtdepannmin": "muaggatt",
    "wtdepaprjunmin": "muaggatt",
    "niccdcd": "muaggatt",
    "niccdcdpct": "muaggatt",
    "cropzne": "muaggatt",
    "meanannprecip": "muaggatt",
    # component
    "cokey": "component",
    "compname": "component",
    "comppct_r": "component",
    "majcompflag": "component",
    "slope_r": "component",
    "drainagecl": "component",
    "hydgrp": "component",
    "taxclname": "component",
    "taxorder": "component",
    "taxsuborder": "component",
    "taxgrtgroup": "component",
    "taxsubgrp": "component",
    "taxpartsize": "component",
    "taxpartsizemod": "component",
    "taxceactcl": "component",
    "taxreaction": "component",
    "taxtempcl": "component",
    "taxmoistscl": "component",
    "taxtempregime": "component",
    "soiltaxedition": "component",
    "nirrcapcl": "component",
    "nirrcapscl": "component",
    "irrcapcl": "component",
    "irrcapscl": "component",
    "frostact": "component",
    "runoff": "component",
    "tfact": "component",
    "weg": "component",
    "erocl": "component",
    "hydricrating": "component",
    "localphase": "component",
    # chorizon
    "chkey": "chorizon",
    "hzname": "chorizon",
    "hzdept_r": "chorizon",
    "hzdepb_r": "chorizon",
    "sandtotal_r": "chorizon",
    "sandvf_r": "chorizon",
    "sandfine_r": "chorizon",
    "sandmed_r": "chorizon",
    "sandco_r": "chorizon",
    "silttotal_r": "chorizon",
    "siltco_r": "chorizon",
    "siltfine_r": "chorizon",
    "claytotal_r": "chorizon",
    "om_r": "chorizon",
    "oc_r": "chorizon",
    "soc_r": "chorizon",
    "ph1to1h2o_r": "chorizon",
    "ph01mcacl2_r": "chorizon",
    "ksat_r": "chorizon",
    "dbthirdbar_r": "chorizon",
    "dbovendry_r": "chorizon",
    "awc_r": "chorizon",
    "wthirdbar_r": "chorizon",
    "wfifteenbar_r": "chorizon",
    "lep_r": "chorizon",
    "sar_r": "chorizon",
    "ec_r": "chorizon",
    "cec7_r": "chorizon",
    "ecec_r": "chorizon",
    "caco3_r": "chorizon",
    "gypsum_r": "chorizon",
    "sieveno4_r": "chorizon",
    "sieveno10_r": "chorizon",
    "sieveno40_r": "chorizon",
    "sieveno200_r": "chorizon",
    "frag3to10_r": "chorizon",
    "fraggt10_r": "chorizon",
    "freeiron_r": "chorizon",
    "sulfur_r": "chorizon",
    "kwfact": "chorizon",
    "kffact": "chorizon",
    # corestrictions
    "reskind": "corestrictions",
    "reshard": "corestrictions",
    "resdept_r": "corestrictions",
    "resdept_l": "corestrictions",
    "resdept_h": "corestrictions",
    "resdepb_r": "corestrictions",
    "resdepb_l": "corestrictions",
    "resdepb_h": "corestrictions",
    # comonth
    "month": "comonth",
    "flodfreqcl": "comonth",
    "floddurcl": "comonth",
    "pondfreqcl": "comonth",
    "ponddurcl": "comonth",
    # cosoilmoist
    "soimoistdept_r": "cosoilmoist",
    "soimoistdept_l": "cosoilmoist",
    "soimoistdept_h": "cosoilmoist",
    "soimoistdepb_r": "cosoilmoist",
    "soimoiststat": "cosoilmoist",
    # cointerp
    "mrulename": "cointerp",
    "interplrc": "cointerp",
    "interphr": "cointerp",
    "interphrc": "cointerp",
    "interplr": "cointerp",
    # coecoclass
    "ecoclassid": "coecoclass",
    "ecoclassname": "coecoclass",
    "ecosubclcd": "coecoclass",
    "ecotype": "coecoclass",
    "ecoclasstypename": "coecoclass",
    # copmgrp
    "pmgroupname": "copmgrp",
    "rvindicator": "copmgrp",
    # copm
    "pmkind": "copm",
    "pmorigin": "copm",
    "pmmodified": "copm",
    # cosoiltemp
    "dept_r": "cosoiltemp",
    "dept_l": "cosoiltemp",
    "dept_h": "cosoiltemp",
    "soiltempmnth_r": "cosoiltemp",
    "soiltempmnth_l": "cosoiltemp",
    "soiltempmnth_h": "cosoiltemp",
}


@pytest.fixture(autouse=True)
def _reset_ssurgo_caches(request):
    """Reset both module-level caches before each test."""
    _VARIABLE_INFO_CACHE.clear()
    _COLUMN_TABLE_CACHE.clear()
    _COLUMN_TABLE_CACHE.update(_COLUMN_TABLE_MAP_TEST_DATA)
    # Pre-seed variable info cache with empty dicts so _get_variable_info()
    # returns immediately without making HTTP requests during unit tests.
    # Tests for available_variables functions are excluded: they register HTTP
    # mocks specifically to exercise the fetch path, so the cache must be cold.
    if "available_variables" not in request.node.name:
        for _avail_sql in (
            _SOIL_PROFILE_AVAIL_SQL,
            _AREA_SUMMARY_AVAIL_SQL,
            _SUBSURFACE_BARRIERS_AVAIL_SQL,
            _SEASONAL_HYDROLOGY_AVAIL_SQL,
            _ECOLOGICAL_SITE_AVAIL_SQL,
            _PARENT_MATERIAL_AVAIL_SQL,
            _SOIL_TEMPERATURE_AVAIL_SQL,
        ):
            _VARIABLE_INFO_CACHE[_avail_sql] = {}
    yield


# Yakima WA test coordinates
_LAT = 46.2531882
_LON = -119.4768203

# Yakima WA bounding box
_MIN_LAT = 46.251407
_MAX_LAT = 46.251790
_MIN_LON = -119.728785
_MAX_LON = -119.728369

# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

_YAKIMA_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <majcompflag>Yes</majcompflag>
        <comppct_r>75</comppct_r>
        <hzdept_r>0</hzdept_r>
        <hzdepb_r>18</hzdepb_r>
        <sandtotal_r>19</sandtotal_r>
        <silttotal_r>59</silttotal_r>
        <claytotal_r>22</claytotal_r>
        <ph1to1h2o_r>6.5</ph1to1h2o_r>
        <om_r>1.2</om_r>
        <ksat_r>14</ksat_r>
        <awc_r>0.18</awc_r>
        <dbthirdbar_r>1.42</dbthirdbar_r>
      </Table>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <majcompflag>Yes</majcompflag>
        <comppct_r>75</comppct_r>
        <hzdept_r>18</hzdept_r>
        <hzdepb_r>91</hzdepb_r>
        <sandtotal_r>16</sandtotal_r>
        <silttotal_r>57</silttotal_r>
        <claytotal_r>27</claytotal_r>
        <ph1to1h2o_r>7.1</ph1to1h2o_r>
        <om_r>0.6</om_r>
        <ksat_r>9</ksat_r>
        <awc_r>0.14</awc_r>
        <dbthirdbar_r>1.51</dbthirdbar_r>
      </Table>
    </NewDataSet>
""")

_EMPTY_XML = '<?xml version="1.0" encoding="utf-8"?><NewDataSet />'

# available_variables response (tabphyname/colphyname/collogname/coldesc/uomabbrev)
_AVAIL_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <tabphyname>chorizon</tabphyname>
        <colphyname>sandtotal_r</colphyname>
        <collogname>Total Sand - Rep Value</collogname>
        <coldesc>The total sand content of the less than 2 mm fraction.</coldesc>
        <uomabbrev>%</uomabbrev>
      </Table>
      <Table>
        <tabphyname>mapunit</tabphyname>
        <colphyname>muname</colphyname>
        <collogname>Map Unit Name</collogname>
        <coldesc>Name assigned to a map unit.</coldesc>
        <uomabbrev>NULL</uomabbrev>
      </Table>
      <Table>
        <tabphyname>component</tabphyname>
        <colphyname>drainagecl</colphyname>
        <collogname>Drainage Class</collogname>
        <coldesc>The natural drainage condition of the soil.</coldesc>
        <uomabbrev>NULL</uomabbrev>
      </Table>
    </NewDataSet>
""")

_AREA_SUMMARY_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <musym>RiC2</musym>
        <drclassdcd>Well drained</drclassdcd>
        <hydgrpdcd>C</hydgrpdcd>
        <aws0150wta>15.8</aws0150wta>
        <soc0_999wta>4.2</soc0_999wta>
        <nccpi3all>0.62</nccpi3all>
        <pctearthmc>100</pctearthmc>
        <flodfreqdcd>None</flodfreqdcd>
        <wtdepannmin>200</wtdepannmin>
      </Table>
    </NewDataSet>
""")

_BARRIERS_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <majcompflag>Yes</majcompflag>
        <reskind>Bedrock, paralithic</reskind>
        <reshard>Noncemented</reshard>
        <resdept_r>150</resdept_r>
        <resdepb_r>200</resdepb_r>
      </Table>
    </NewDataSet>
""")

_HYDROLOGY_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <month>January</month>
        <flodfreqcl>None</flodfreqcl>
        <floddurcl>None</floddurcl>
        <pondfreqcl>None</pondfreqcl>
        <soimoistdept_r>200</soimoistdept_r>
        <soimoiststat>Dry</soimoiststat>
      </Table>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <month>February</month>
        <flodfreqcl>None</flodfreqcl>
        <floddurcl>None</floddurcl>
        <pondfreqcl>None</pondfreqcl>
        <soimoistdept_r>180</soimoistdept_r>
        <soimoiststat>Moist</soimoiststat>
      </Table>
    </NewDataSet>
""")

_SUITABILITY_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <mrulename>ENG - Dwellings Without Basements</mrulename>
        <interplrc>Slightly limited</interplrc>
        <interphr>0.15</interphr>
      </Table>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <mrulename>ENG - Septic Tank Absorption Fields</mrulename>
        <interplrc>Not limited</interplrc>
        <interphr>0.02</interphr>
      </Table>
    </NewDataSet>
""")

_ECOCLASS_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <majcompflag>Yes</majcompflag>
        <ecoclassid>R009XY023WA</ecoclassid>
        <ecoclassname>Loamy 8-12 P.Z.</ecoclassname>
        <ecosubclcd>NULL</ecosubclcd>
        <ecotype>range site</ecotype>
      </Table>
    </NewDataSet>
""")

_PARENT_MAT_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <majcompflag>Yes</majcompflag>
        <pmgroupname>loess</pmgroupname>
        <pmkind>Loess</pmkind>
        <pmorigin>Eolian deposits</pmorigin>
      </Table>
    </NewDataSet>
""")

_RULES_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mrulename>ENG - Dwellings Without Basements</mrulename>
      </Table>
      <Table>
        <mrulename>ENG - Septic Tank Absorption Fields</mrulename>
      </Table>
      <Table>
        <mrulename>AGR - Land Capability Class (Non-Irrigated)</mrulename>
      </Table>
    </NewDataSet>
""")

_SOIL_TEMP_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <month>January</month>
        <dept_r>25</dept_r>
        <soiltempmnth_r>2.5</soiltempmnth_r>
        <soiltempmnth_l>1.8</soiltempmnth_l>
        <soiltempmnth_h>3.2</soiltempmnth_h>
      </Table>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <month>July</month>
        <dept_r>25</dept_r>
        <soiltempmnth_r>21.0</soiltempmnth_r>
        <soiltempmnth_l>19.5</soiltempmnth_l>
        <soiltempmnth_h>22.5</soiltempmnth_h>
      </Table>
    </NewDataSet>
""")

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
# _fetch_sda unit tests (httpx_mock)
# ---------------------------------------------------------------------------


def test_fetch_sda_returns_records(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    records, latency = _fetch_sda("SELECT mukey FROM mapunit WHERE 1=1")
    assert len(records) == 2
    assert isinstance(latency, float)
    assert latency >= 0.0


def test_fetch_sda_non_us_returns_empty(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    records, latency = _fetch_sda("SELECT mukey FROM mapunit WHERE 1=1")
    assert records == []


# ---------------------------------------------------------------------------
# Type 1: soil_profile
# ---------------------------------------------------------------------------


def test_soil_profile_available_variables_returns_variables_key(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_soil_profile_available_variables()
    assert "variables" in result
    assert "_meta" in result
    assert "chorizon" in result["variables"]
    assert "mapunit" in result["variables"]
    assert "component" in result["variables"]


def test_soil_profile_available_variables_entry_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_soil_profile_available_variables()
    entry = result["variables"]["chorizon"][0]
    # entries use 'variable' key (not 'column')
    assert entry["variable"] == "sandtotal_r"
    assert entry["label"] == "Total Sand - Rep Value"
    assert entry["units"] == "%"


def test_soil_profile_available_variables_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_soil_profile_available_variables()
    assert result["_meta"]["success"] is True
    assert result["_meta"]["rows_returned"] == 3


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_soil_profile_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_profile_available_variables()
    assert result["_meta"]["success"] is False
    assert result["variables"] == {}


def test_soil_profile_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 2


def test_soil_profile_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    meta = result["_meta"]
    assert meta["source"] == "ssurgo"
    assert meta["success"] is True
    assert meta["error"] is None
    assert meta["rows_returned"] == 2
    assert meta["auth_required"] is False


def test_soil_profile_query_license_fields(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["license"] == LICENSE_INFO["license"]
    assert result["_meta"]["license_url"] == LICENSE_INFO["license_url"]


def test_soil_profile_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert qp["longitude"] == pytest.approx(_LON)
    assert "variables" in qp


def test_soil_profile_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    result = ssurgo_soil_profile_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_soil_profile_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False
    assert result["_meta"]["error"] is not None


def test_soil_profile_query_variable_info_in_meta(httpx_mock):
    # Pre-warm the cache with _AVAIL_XML data so variable_info is populated
    _VARIABLE_INFO_CACHE[_SOIL_PROFILE_AVAIL_SQL] = {
        "sandtotal_r": {
            "table": "chorizon",
            "label": "Total Sand - Rep Value",
            "description": "The total sand content of the less than 2 mm fraction.",
            "units": "%",
        },
    }
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    info = result["_meta"]["variable_info"]
    assert "sandtotal_r" in info
    assert info["sandtotal_r"]["description"] != ""
    assert info["sandtotal_r"]["units"] == "%"


def test_soil_profile_query_sand_in_valid_range(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    for row in result["data"]:
        sand = float(row["sandtotal_r"])
        assert 0.0 <= sand <= 100.0, f"sandtotal_r={sand} outside 0-100%"


def test_soil_profile_query_ph_in_valid_range(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    for row in result["data"]:
        ph = float(row["ph1to1h2o_r"])
        assert 2.0 <= ph <= 11.0, f"ph1to1h2o_r={ph} outside 2-11"


def test_soil_profile_query_bulk_density_in_valid_range(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON)
    for row in result["data"]:
        bd = float(row["dbthirdbar_r"])
        assert 0.5 <= bd <= 2.0, f"dbthirdbar_r={bd} outside 0.5-2.0 g/cm3"


def test_soil_profile_query_custom_variables(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_query(latitude=_LAT, longitude=_LON, variables=["mukey", "awc_r"])
    assert result["_meta"]["success"] is True
    assert result["_meta"]["query_params"]["variables"] == ["mukey", "awc_r"]


def test_soil_profile_query_invalid_variable_returns_error():
    result = ssurgo_soil_profile_query(
        latitude=_LAT, longitude=_LON, variables=["mukey; DROP TABLE mapunit"]
    )
    assert result["_meta"]["success"] is False
    assert "Invalid variable name" in result["_meta"]["error"]


def test_soil_profile_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert "centroid_lon" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)
    assert qp["max_lon"] == pytest.approx(_MAX_LON)


def test_soil_profile_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_YAKIMA_XML)
    result = ssurgo_soil_profile_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 2


# ---------------------------------------------------------------------------
# Type 2: area_summary
# ---------------------------------------------------------------------------


def test_area_summary_available_variables_returns_variables_key(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_area_summary_available_variables()
    assert "variables" in result
    assert "_meta" in result


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_area_summary_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_area_summary_available_variables()
    assert result["_meta"]["success"] is False
    assert result["variables"] == {}


def test_area_summary_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1


def test_area_summary_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    meta = result["_meta"]
    assert meta["source"] == "ssurgo"
    assert meta["success"] is True
    assert meta["auth_required"] is False


def test_area_summary_query_license_fields(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["license"] == LICENSE_INFO["license"]
    assert result["_meta"]["license_url"] == LICENSE_INFO["license_url"]


def test_area_summary_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert qp["longitude"] == pytest.approx(_LON)
    assert "variables" in qp


def test_area_summary_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    result = ssurgo_area_summary_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_area_summary_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_area_summary_query_variable_info_in_meta(httpx_mock):
    # Cache returns empty when cold; this just confirms variable_info key is present
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AREA_SUMMARY_XML)
    result = ssurgo_area_summary_query(latitude=_LAT, longitude=_LON)
    assert "variable_info" in result["_meta"]


def test_area_summary_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AREA_SUMMARY_XML)
    result = ssurgo_area_summary_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)
    assert qp["max_lon"] == pytest.approx(_MAX_LON)


def test_area_summary_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AREA_SUMMARY_XML)
    result = ssurgo_area_summary_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1


# ---------------------------------------------------------------------------
# Type 3: subsurface_barriers
# ---------------------------------------------------------------------------


def test_subsurface_barriers_available_variables_returns_variables_key(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_subsurface_barriers_available_variables()
    assert "variables" in result
    assert "_meta" in result


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_subsurface_barriers_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_subsurface_barriers_available_variables()
    assert result["_meta"]["success"] is False
    assert result["variables"] == {}


def test_subsurface_barriers_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_BARRIERS_XML)
    result = ssurgo_subsurface_barriers_query(latitude=_LAT, longitude=_LON)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1


def test_subsurface_barriers_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_BARRIERS_XML)
    result = ssurgo_subsurface_barriers_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["source"] == "ssurgo"
    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is False


def test_subsurface_barriers_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_BARRIERS_XML)
    result = ssurgo_subsurface_barriers_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert qp["longitude"] == pytest.approx(_LON)
    assert "variables" in qp


def test_subsurface_barriers_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    result = ssurgo_subsurface_barriers_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_subsurface_barriers_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_subsurface_barriers_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_subsurface_barriers_query_variable_info_in_meta(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_BARRIERS_XML)
    result = ssurgo_subsurface_barriers_query(latitude=_LAT, longitude=_LON)
    assert "variable_info" in result["_meta"]


def test_subsurface_barriers_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_BARRIERS_XML)
    result = ssurgo_subsurface_barriers_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)


def test_subsurface_barriers_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_BARRIERS_XML)
    result = ssurgo_subsurface_barriers_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1


# ---------------------------------------------------------------------------
# Type 4: seasonal_hydrology
# ---------------------------------------------------------------------------


def test_seasonal_hydrology_available_variables_returns_variables_key(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_seasonal_hydrology_available_variables()
    assert "variables" in result
    assert "_meta" in result


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_seasonal_hydrology_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_seasonal_hydrology_available_variables()
    assert result["_meta"]["success"] is False
    assert result["variables"] == {}


def test_seasonal_hydrology_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_HYDROLOGY_XML)
    result = ssurgo_seasonal_hydrology_query(latitude=_LAT, longitude=_LON)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 2


def test_seasonal_hydrology_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_HYDROLOGY_XML)
    result = ssurgo_seasonal_hydrology_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["source"] == "ssurgo"
    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is False


def test_seasonal_hydrology_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_HYDROLOGY_XML)
    result = ssurgo_seasonal_hydrology_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert "variables" in qp


def test_seasonal_hydrology_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    result = ssurgo_seasonal_hydrology_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_seasonal_hydrology_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_seasonal_hydrology_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_seasonal_hydrology_query_variable_info_in_meta(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_HYDROLOGY_XML)
    result = ssurgo_seasonal_hydrology_query(latitude=_LAT, longitude=_LON)
    assert "variable_info" in result["_meta"]


def test_seasonal_hydrology_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_HYDROLOGY_XML)
    result = ssurgo_seasonal_hydrology_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)


def test_seasonal_hydrology_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_HYDROLOGY_XML)
    result = ssurgo_seasonal_hydrology_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 2


# ---------------------------------------------------------------------------
# Type 5: soil_suitability  (rule_names, not variables)
# ---------------------------------------------------------------------------


def test_soil_suitability_available_variables_returns_rule_names(httpx_mock):
    """available_variables for suitability returns flat 'rule_names' list, not 'variables'."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_RULES_XML)
    result = ssurgo_soil_suitability_available_variables()
    assert "rule_names" in result
    assert "variables" not in result
    assert "_meta" in result
    assert len(result["rule_names"]) == 3
    assert "ENG - Dwellings Without Basements" in result["rule_names"]


def test_soil_suitability_available_variables_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_RULES_XML)
    result = ssurgo_soil_suitability_available_variables()
    assert result["_meta"]["success"] is True
    assert result["_meta"]["rows_returned"] == 3


def test_soil_suitability_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_suitability_available_variables()
    assert result["_meta"]["success"] is False
    assert result["rule_names"] == []


def test_soil_suitability_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SUITABILITY_XML)
    result = ssurgo_soil_suitability_query(latitude=_LAT, longitude=_LON)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 2


def test_soil_suitability_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SUITABILITY_XML)
    result = ssurgo_soil_suitability_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["source"] == "ssurgo"
    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is False


def test_soil_suitability_query_uses_rule_names_param(httpx_mock):
    """rule_names must be echoed in query_params (not 'variables')."""
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SUITABILITY_XML)
    custom_rules = ["ENG - Dwellings Without Basements"]
    result = ssurgo_soil_suitability_query(latitude=_LAT, longitude=_LON, rule_names=custom_rules)
    qp = result["_meta"]["query_params"]
    assert "rule_names" in qp
    assert "variables" not in qp
    assert qp["rule_names"] == custom_rules


def test_soil_suitability_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    result = ssurgo_soil_suitability_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_soil_suitability_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_suitability_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_soil_suitability_query_invalid_rule_name_returns_error():
    """A rule name containing SQL-unsafe characters must be rejected."""
    result = ssurgo_soil_suitability_query(
        latitude=_LAT,
        longitude=_LON,
        rule_names=["ENG - Dwellings'; DROP TABLE component --"],
    )
    assert result["_meta"]["success"] is False
    assert "Invalid rule name" in result["_meta"]["error"]


def test_soil_suitability_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SUITABILITY_XML)
    result = ssurgo_soil_suitability_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)


def test_soil_suitability_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SUITABILITY_XML)
    result = ssurgo_soil_suitability_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 2


# ---------------------------------------------------------------------------
# Type 6: ecological_site
# ---------------------------------------------------------------------------


def test_ecological_site_available_variables_returns_variables_key(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_ecological_site_available_variables()
    assert "variables" in result
    assert "_meta" in result


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_ecological_site_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_ecological_site_available_variables()
    assert result["_meta"]["success"] is False
    assert result["variables"] == {}


def test_ecological_site_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_ECOCLASS_XML)
    result = ssurgo_ecological_site_query(latitude=_LAT, longitude=_LON)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1


def test_ecological_site_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_ECOCLASS_XML)
    result = ssurgo_ecological_site_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["source"] == "ssurgo"
    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is False


def test_ecological_site_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_ECOCLASS_XML)
    result = ssurgo_ecological_site_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert "variables" in qp


def test_ecological_site_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    result = ssurgo_ecological_site_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_ecological_site_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_ecological_site_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_ecological_site_query_variable_info_in_meta(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_ECOCLASS_XML)
    result = ssurgo_ecological_site_query(latitude=_LAT, longitude=_LON)
    assert "variable_info" in result["_meta"]


def test_ecological_site_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_ECOCLASS_XML)
    result = ssurgo_ecological_site_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)


def test_ecological_site_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_ECOCLASS_XML)
    result = ssurgo_ecological_site_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1


# ---------------------------------------------------------------------------
# Type 7: parent_material
# ---------------------------------------------------------------------------


def test_parent_material_available_variables_returns_variables_key(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_parent_material_available_variables()
    assert "variables" in result
    assert "_meta" in result


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_parent_material_available_variables_http_error(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_parent_material_available_variables()
    assert result["_meta"]["success"] is False
    assert result["variables"] == {}


def test_parent_material_query_success_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_PARENT_MAT_XML)
    result = ssurgo_parent_material_query(latitude=_LAT, longitude=_LON)
    assert "data" in result
    assert "_meta" in result
    assert len(result["data"]) == 1


def test_parent_material_query_meta_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_PARENT_MAT_XML)
    result = ssurgo_parent_material_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["source"] == "ssurgo"
    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is False


def test_parent_material_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_PARENT_MAT_XML)
    result = ssurgo_parent_material_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert "variables" in qp


def test_parent_material_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    result = ssurgo_parent_material_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_parent_material_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_parent_material_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_parent_material_query_variable_info_in_meta(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_PARENT_MAT_XML)
    result = ssurgo_parent_material_query(latitude=_LAT, longitude=_LON)
    assert "variable_info" in result["_meta"]


def test_parent_material_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_PARENT_MAT_XML)
    result = ssurgo_parent_material_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)


def test_parent_material_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_PARENT_MAT_XML)
    result = ssurgo_parent_material_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 1


# ---------------------------------------------------------------------------
# Type 8: soil_temperature
# ---------------------------------------------------------------------------


def test_soil_temperature_available_variables_structure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_soil_temperature_available_variables()
    assert "variables" in result
    assert "_meta" in result


def test_soil_temperature_available_variables_meta_query_type(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_AVAIL_XML)
    result = ssurgo_soil_temperature_available_variables()
    assert result["_meta"]["query_params"]["query_type"] == "soil_temperature"


def test_soil_temperature_query_default_variables_success(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 2


def test_soil_temperature_query_row_fields(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    row = result["data"][0]
    assert row["mukey"] == "2764208"
    assert row["compname"] == "Ritzville"
    assert row["month"] == "January"
    assert row["dept_r"] == "25"
    assert row["soiltempmnth_r"] == "2.5"


def test_soil_temperature_query_meta_query_type(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["query_params"]["query_type"] == "soil_temperature"


def test_soil_temperature_query_echoes_query_params(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == pytest.approx(_LAT)
    assert "variables" in qp


def test_soil_temperature_query_non_us_returns_no_coverage(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_EMPTY_XML)
    result = ssurgo_soil_temperature_query(latitude=48.8566, longitude=2.3522)
    assert result["_meta"]["success"] is True
    assert result["data"] == []
    assert result["_meta"]["error"] == _NO_COVERAGE_MSG


def test_soil_temperature_query_http_error_returns_failure(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, status_code=500)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    assert result["_meta"]["success"] is False


def test_soil_temperature_query_variable_info_in_meta(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_query(latitude=_LAT, longitude=_LON)
    assert "variable_info" in result["_meta"]


def test_soil_temperature_default_variables_contains_expected():
    assert "month" in DEFAULT_SOIL_TEMPERATURE_VARIABLES
    assert "dept_r" in DEFAULT_SOIL_TEMPERATURE_VARIABLES
    assert "soiltempmnth_r" in DEFAULT_SOIL_TEMPERATURE_VARIABLES


def test_soil_temperature_bbox_query_uses_polygon_not_centroid(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    qp = result["_meta"]["query_params"]
    assert "centroid_lat" not in qp
    assert qp["min_lat"] == pytest.approx(_MIN_LAT)


def test_soil_temperature_bbox_query_returns_data(httpx_mock):
    httpx_mock.add_response(method="POST", url=_SDA_URL, text=_SOIL_TEMP_XML)
    result = ssurgo_soil_temperature_bbox_query(
        min_lat=_MIN_LAT, max_lat=_MAX_LAT, min_lon=_MIN_LON, max_lon=_MAX_LON
    )
    assert result["_meta"]["success"] is True
    assert len(result["data"]) == 2


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
