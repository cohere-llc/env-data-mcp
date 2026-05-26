"""Shared fixtures and test constants for the SSURGO unit test suite."""

from __future__ import annotations

import textwrap

import pytest

import env_data_mcp.sources.ssurgo._client as _ssurgo_client
from env_data_mcp.sources.ssurgo._client import (
    _COLUMN_TABLE_CACHE,
    _PDF_COL_METADATA_CACHE,
    _VARIABLE_INFO_CACHE,
)
from env_data_mcp.sources.ssurgo.constants import (
    _AVAIL_SQL_TABLES,
    _QueryType,
)

# ---------------------------------------------------------------------------
# URL constant (mirrors _SDA_URL but kept local to avoid network imports)
# ---------------------------------------------------------------------------

_SDA_URL = "https://sdmdataaccess.nrcs.usda.gov/Tabular/SDMTabularService/post.rest"


# ---------------------------------------------------------------------------
# Cache management: clear all SSURGO module-level caches before each test.
# _PDF_COL_METADATA_LOADED is set to True so that _load_column_metadata()
# returns the (empty) cache immediately without attempting a network call.
# ---------------------------------------------------------------------------


_MOCK_GEOMETRY: dict = {
    "type": "Polygon",
    "coordinates": [
        [[-119.5, 46.2], [-119.4, 46.2], [-119.4, 46.3], [-119.5, 46.3], [-119.5, 46.2]]
    ],
}


@pytest.fixture(autouse=True)
def _mock_mukey_geometries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch _fetch_mukey_geometries in tools to avoid real network calls in unit tests."""
    import env_data_mcp.sources.ssurgo.tools as _tools_mod

    monkeypatch.setattr(
        _tools_mod,
        "_fetch_mukey_geometries",
        lambda mukeys, bbox: {mk: _MOCK_GEOMETRY for mk in mukeys},
    )


@pytest.fixture(autouse=True)
def _clear_ssurgo_caches() -> object:
    """Reset all SSURGO module-level caches around each unit test."""
    _VARIABLE_INFO_CACHE.clear()
    _COLUMN_TABLE_CACHE.clear()
    _PDF_COL_METADATA_CACHE.clear()
    _ssurgo_client._PDF_COL_METADATA_LOADED = True  # suppress PDF download
    yield
    _VARIABLE_INFO_CACHE.clear()
    _COLUMN_TABLE_CACHE.clear()
    _PDF_COL_METADATA_CACHE.clear()
    _ssurgo_client._PDF_COL_METADATA_LOADED = False


# ---------------------------------------------------------------------------
# Test-time column → table seed data (mirrors the schema queried by
# _get_column_table_map in production; kept here so tests never make a real
# network call just to qualify SELECT columns).
# ---------------------------------------------------------------------------

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
    "soitempdept_l": "cosoiltemp",
    "soitempdept_r": "cosoiltemp",
    "soitempdept_h": "cosoiltemp",
    "soitempdepb_l": "cosoiltemp",
    "soitempdepb_r": "cosoiltemp",
    "soitempdepb_h": "cosoiltemp",
    "soitempmm": "cosoiltemp",
}

# ---------------------------------------------------------------------------
# Test coordinates
# ---------------------------------------------------------------------------

_LAT = 46.2531882
_LON = -119.4768203

_MIN_LAT = 46.251407
_MAX_LAT = 46.251790
_MIN_LON = -119.728785
_MAX_LON = -119.728369

# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

EMPTY_XML = '<?xml version="1.0" encoding="utf-8"?><NewDataSet />'


def _schema_xml(*cols: str) -> str:
    """Build a minimal XSD-embedded SDA response for the given column names.

    Mirrors the format returned by ``SELECT TOP 1 * FROM <table>`` so that
    ``_sda_table_columns`` can parse column names from it in unit tests without
    making real network calls.
    """
    elements = "\n                ".join(
        f'<xs:element name="{c}" type="xs:string" minOccurs="0" />' for c in cols
    )
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <NewDataSet>
          <xs:schema id="NewDataSet" xmlns="" xmlns:xs="http://www.w3.org/2001/XMLSchema"
            xmlns:msdata="urn:schemas-microsoft-com:xml-msdata">
            <xs:element name="NewDataSet" msdata:IsDataSet="true">
              <xs:complexType>
                <xs:choice minOccurs="0" maxOccurs="unbounded">
                  <xs:element name="Table">
                    <xs:complexType>
                      <xs:sequence>
                        {elements}
                      </xs:sequence>
                    </xs:complexType>
                  </xs:element>
                </xs:choice>
              </xs:complexType>
            </xs:element>
          </xs:schema>
        </NewDataSet>
    """)


# Minimal per-table XSD schema responses (column names only; no metadata).
TABLE_SCHEMA_XMLS: dict[str, str] = {
    "mapunit": _schema_xml("mukey", "muname"),
    "component": _schema_xml("cokey", "compname", "comppct_r"),
    "chorizon": _schema_xml("hzdept_r", "sandtotal_r", "claytotal_r"),
    "muaggatt": _schema_xml("drclassdcd", "hydgrpdcd", "aws025wta"),
    "corestrictions": _schema_xml("reskind", "resdept_r"),
    "comonth": _schema_xml("month", "flodfreqcl"),
    "cosoilmoist": _schema_xml("soimoistdept_r", "soimoiststat"),
    "cosoiltemp": _schema_xml("soitempdept_r", "soitempdepb_r"),
    "coecoclass": _schema_xml("ecoclassid", "ecoclassname"),
    "copmgrp": _schema_xml("pmgroupname", "rvindicator"),
    "copm": _schema_xml("pmkind", "pmorigin"),
}


def add_schema_responses(httpx_mock: object, avail_sql: _QueryType) -> None:
    """Register one mock schema response per table for the given avail_sql key."""
    for table in _AVAIL_SQL_TABLES[avail_sql]:
        httpx_mock.add_response(  # type: ignore[attr-defined]
            method="POST", url=_SDA_URL, text=TABLE_SCHEMA_XMLS[table]
        )


YAKIMA_XML = textwrap.dedent("""\
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

AREA_SUMMARY_XML = textwrap.dedent("""\
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

BARRIERS_XML = textwrap.dedent("""\
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

HYDROLOGY_XML = textwrap.dedent("""\
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

SUITABILITY_XML = textwrap.dedent("""\
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

ECOCLASS_XML = textwrap.dedent("""\
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

PARENT_MAT_XML = textwrap.dedent("""\
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

RULES_XML = textwrap.dedent("""\
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

SOIL_TEMP_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <NewDataSet>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <month>January</month>
        <soitempdept_r>25</soitempdept_r>
        <soitempdepb_r>50</soitempdepb_r>
        <soitempmm>2.5</soitempmm>
      </Table>
      <Table>
        <mukey>2764208</mukey>
        <muname>Ritzville silt loam, 2 to 8 percent slopes</muname>
        <compname>Ritzville</compname>
        <comppct_r>75</comppct_r>
        <month>July</month>
        <soitempdept_r>25</soitempdept_r>
        <soitempdepb_r>50</soitempdepb_r>
        <soitempmm>21.0</soitempmm>
      </Table>
    </NewDataSet>
""")

# ---------------------------------------------------------------------------
# Shared autouse fixture
# ---------------------------------------------------------------------------


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
        for _qt in _QueryType:
            _VARIABLE_INFO_CACHE[_qt] = {}
    yield
