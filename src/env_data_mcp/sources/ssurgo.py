"""USDA SSURGO soil data adapter.

Data source: USDA Web Soil Survey Soil Data Access (SDA)
  ``https://sdmdataaccess.nrcs.usda.gov/``
Coverage: Continental US + territories; no auth required
Auth required: No

Query types provided
--------------------
+-------------------------------+----------------------------------------------------+
| Tool prefix                   | Tables / data returned                             |
+===============================+====================================================+
| ssurgo_soil_profile_*         | mapunit → component → chorizon                     |
|                               | Per-horizon physical/chemical properties:          |
|                               | texture, pH, organic matter, hydraulics.           |
+-------------------------------+----------------------------------------------------+
| ssurgo_area_summary_*         | mapunit → muaggatt                                 |
|                               | NRCS pre-aggregated map-unit summary: drainage,    |
|                               | hydrologic group, available water capacity, SOC    |
|                               | stock, crop productivity index, flood class.       |
+-------------------------------+----------------------------------------------------+
| ssurgo_subsurface_barriers_*  | mapunit → component → corestrictions               |
|                               | Depth to hard layers limiting rooting, drainage,   |
|                               | or excavation (bedrock, fragipan, duripan, etc.)   |
+-------------------------------+----------------------------------------------------+
| ssurgo_seasonal_hydrology_*   | mapunit → component → comonth → cosoilmoist        |
|                               | Monthly flooding/ponding and water table depth     |
|                               | (12 rows per component, Jan–Dec).                  |
+-------------------------------+----------------------------------------------------+
| ssurgo_soil_suitability_*     | mapunit → component → cointerp                     |
|                               | Pre-computed NRCS suitability ratings by rule.     |
|                               | Use ``rule_names`` to select interpretations.      |
+-------------------------------+----------------------------------------------------+
| ssurgo_ecological_site_*      | mapunit → component → coecoclass                   |
|                               | Ecological site IDs/names — links soil to          |
|                               | vegetation potential for range and forest land.    |
+-------------------------------+----------------------------------------------------+
| ssurgo_parent_material_*      | mapunit → component → copmgrp → copm               |
|                               | What the soil formed from (loess, alluvium,        |
|                               | glacial till, volcanic ash, etc.).                 |
+-------------------------------+----------------------------------------------------+
| ssurgo_soil_temperature_*     | mapunit → component → comonth → cosoiltemp         |
|                               | Monthly mean soil temperature by depth (°C),       |
|                               | with representative, low, and high values.         |
+-------------------------------+----------------------------------------------------+

Future query types (not yet implemented)
-----------------------------------------
+-------------------------------+----------------------------------------------------+
| ssurgo_crop_yields_*          | cocropyld / mucropyld — crop-specific yield        |
|                               | estimates, irrigated and non-irrigated.            |
+-------------------------------+----------------------------------------------------+
| ssurgo_landscape_position_*   | cogeomordesc — hillslope position and landform.    |
+-------------------------------+----------------------------------------------------+
| ssurgo_surface_cover_*        | cosurffrags + cofloorfrag — surface rock cover.    |
+-------------------------------+----------------------------------------------------+
| ssurgo_soil_narratives_*      | mutext + cotext + chtext — free-text descriptions. |
+-------------------------------+----------------------------------------------------+

More granular laboratory data: https://ncsslabdatamart.sc.egov.usda.gov/
"""

from __future__ import annotations

import math
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from env_data_mcp.helpers import bbox_to_wkt_polygon, build_meta, check_runtime
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# Licence and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "Public domain (USDA/US Government).",
    "license_url": (
        "https://www.nrcs.usda.gov/resources/data-and-reports/"
        "soil-survey-geographic-database-ssurgo"
    ),
    "citation": "USDA-NRCS (2024). Web Soil Survey. "
    "Soil Survey Geographic Database (SSURGO). "
    "https://websoilsurvey.nrcs.usda.gov",
}

_SDA_URL = "https://sdmdataaccess.nrcs.usda.gov/Tabular/SDMTabularService/post.rest"

_NO_COVERAGE_MSG = (
    "No SSURGO data were returned for this location. "
    "The point may be outside SSURGO coverage (non-US or unmapped area), "
    "or the SDA service may have failed to match the point for this request."
)

# ---------------------------------------------------------------------------
# Type 1: soil_profile  (mapunit → component → chorizon)
# ---------------------------------------------------------------------------

DEFAULT_SOIL_PROFILE_VARIABLES: list[str] = [
    "mukey",
    "muname",
    "compname",
    "majcompflag",
    "comppct_r",
    "hzdept_r",
    "hzdepb_r",
    "sandtotal_r",
    "silttotal_r",
    "claytotal_r",
    "ph1to1h2o_r",
    "om_r",
    "ksat_r",
    "awc_r",
    "dbthirdbar_r",
]

# ---------------------------------------------------------------------------
# Type 2: area_summary  (mapunit → muaggatt)
# ---------------------------------------------------------------------------

DEFAULT_AREA_SUMMARY_VARIABLES: list[str] = [
    "mukey",
    "muname",
    "musym",
    "drclassdcd",
    "hydgrpdcd",
    "aws0150wta",
    "soc0_999wta",
    "nccpi3all",
    "pctearthmc",
    "flodfreqdcd",
    "wtdepannmin",
]

# ---------------------------------------------------------------------------
# Type 3: subsurface_barriers  (mapunit → component → corestrictions)
# ---------------------------------------------------------------------------

DEFAULT_SUBSURFACE_BARRIERS_VARIABLES: list[str] = [
    "mukey",
    "muname",
    "compname",
    "comppct_r",
    "majcompflag",
    "reskind",
    "reshard",
    "resdept_r",
    "resdepb_r",
]

# ---------------------------------------------------------------------------
# Type 4: seasonal_hydrology  (mapunit → component → comonth → cosoilmoist)
# ---------------------------------------------------------------------------

DEFAULT_SEASONAL_HYDROLOGY_VARIABLES: list[str] = [
    "mukey",
    "muname",
    "compname",
    "comppct_r",
    "month",
    "flodfreqcl",
    "floddurcl",
    "pondfreqcl",
    "soimoistdept_r",
    "soimoiststat",
]

# ---------------------------------------------------------------------------
# Type 5: soil_suitability  (mapunit → component → cointerp)
# Note: selectable parameter is rule_names, not variable names.
# Output columns are fixed: mukey, muname, compname, comppct_r,
#                           mrulename, interplrc, interphr
# ---------------------------------------------------------------------------

DEFAULT_SOIL_SUITABILITY_RULE_NAMES: list[str] = [
    "ENG - Dwellings Without Basements",
    "ENG - Septic Tank Absorption Fields",
    "AGR - Land Capability Class (Non-Irrigated)",
    "DHS - Potential for Hydric Soils",
]

# ---------------------------------------------------------------------------
# Type 6: ecological_site  (mapunit → component → coecoclass)
# ---------------------------------------------------------------------------

DEFAULT_ECOLOGICAL_SITE_VARIABLES: list[str] = [
    "mukey",
    "muname",
    "compname",
    "comppct_r",
    "majcompflag",
    "ecoclassid",
    "ecoclassname",
    "ecosubclcd",
    "ecotype",
]

# ---------------------------------------------------------------------------
# Type 7: parent_material  (mapunit → component → copmgrp → copm)
# ---------------------------------------------------------------------------

DEFAULT_PARENT_MATERIAL_VARIABLES: list[str] = [
    "mukey",
    "muname",
    "compname",
    "comppct_r",
    "majcompflag",
    "pmgroupname",
    "pmkind",
    "pmorigin",
]

# ---------------------------------------------------------------------------
# Type 8: soil_temperature  (mapunit → component → comonth → cosoiltemp)
# ---------------------------------------------------------------------------

DEFAULT_SOIL_TEMPERATURE_VARIABLES: list[str] = [
    "mukey",
    "muname",
    "compname",
    "comppct_r",
    "month",
    "dept_r",
    "soiltempmnth_r",
    "soiltempmnth_l",
    "soiltempmnth_h",
]

# Session cache: avail_sql → {colphyname: {"table", "label", "description", "units"}}
_VARIABLE_INFO_CACHE: dict[str, dict[str, dict[str, str]]] = {}

# XML namespace used when parsing XSD schemas embedded in SDA tabular responses.
_XS_NS = "http://www.w3.org/2001/XMLSchema"

# Tables in the order used to build the column → table mapping.  PK-owning
# tables must appear before FK tables so that shared column names (e.g.
# ``mukey`` appears in both mapunit and component) resolve to the
# primary-key table (first-wins insertion into ``_COLUMN_TABLE_CACHE``).
_COLUMN_TABLE_PRIORITY: tuple[str, ...] = (
    "mapunit",
    "muaggatt",
    "component",
    "chorizon",
    "corestrictions",
    "comonth",
    "cosoilmoist",
    "cointerp",
    "coecoclass",
    "copmgrp",
    "copm",
    "cosoiltemp",
)

# Session-level cache: physical column name → owning table.
# Populated lazily by _get_column_table_map() on the first SQL builder call.
_COLUMN_TABLE_CACHE: dict[str, str] = {}

# Per-type available-variables SQL (queries SDA built-in column catalogue).
_SOIL_PROFILE_AVAIL_SQL = """\
SELECT mc.tabphyname, mc.colphyname, mc.collogname, mc.coldesc, mc.uomabbrev
FROM mdstatcolmas mc
WHERE mc.tabphyname IN ('mapunit', 'component', 'chorizon')
ORDER BY mc.tabphyname, mc.colsequence"""

_AREA_SUMMARY_AVAIL_SQL = """\
SELECT mc.tabphyname, mc.colphyname, mc.collogname, mc.coldesc, mc.uomabbrev
FROM mdstatcolmas mc
WHERE mc.tabphyname IN ('mapunit', 'muaggatt')
ORDER BY mc.tabphyname, mc.colsequence"""

_SUBSURFACE_BARRIERS_AVAIL_SQL = """\
SELECT mc.tabphyname, mc.colphyname, mc.collogname, mc.coldesc, mc.uomabbrev
FROM mdstatcolmas mc
WHERE mc.tabphyname IN ('mapunit', 'component', 'corestrictions')
ORDER BY mc.tabphyname, mc.colsequence"""

_SEASONAL_HYDROLOGY_AVAIL_SQL = """\
SELECT mc.tabphyname, mc.colphyname, mc.collogname, mc.coldesc, mc.uomabbrev
FROM mdstatcolmas mc
WHERE mc.tabphyname IN ('mapunit', 'component', 'comonth', 'cosoilmoist')
ORDER BY mc.tabphyname, mc.colsequence"""

_SOIL_SUITABILITY_RULES_SQL = """\
SELECT DISTINCT mrulename
FROM cointerp
ORDER BY mrulename"""

_ECOLOGICAL_SITE_AVAIL_SQL = """\
SELECT mc.tabphyname, mc.colphyname, mc.collogname, mc.coldesc, mc.uomabbrev
FROM mdstatcolmas mc
WHERE mc.tabphyname IN ('mapunit', 'component', 'coecoclass')
ORDER BY mc.tabphyname, mc.colsequence"""

_PARENT_MATERIAL_AVAIL_SQL = """\
SELECT mc.tabphyname, mc.colphyname, mc.collogname, mc.coldesc, mc.uomabbrev
FROM mdstatcolmas mc
WHERE mc.tabphyname IN ('mapunit', 'component', 'copmgrp', 'copm')
ORDER BY mc.tabphyname, mc.colsequence"""

_SOIL_TEMPERATURE_AVAIL_SQL = """\
SELECT mc.tabphyname, mc.colphyname, mc.collogname, mc.coldesc, mc.uomabbrev
FROM mdstatcolmas mc
WHERE mc.tabphyname IN ('mapunit', 'component', 'comonth', 'cosoiltemp')
ORDER BY mc.tabphyname, mc.colsequence"""

# Mapping from avail-variables cache key → data tables to query as a fallback
# when the mdstatcolmas catalogue is unavailable in SDA.
_AVAIL_SQL_TABLES: dict[str, tuple[str, ...]] = {
    _SOIL_PROFILE_AVAIL_SQL: ("mapunit", "component", "chorizon"),
    _AREA_SUMMARY_AVAIL_SQL: ("mapunit", "muaggatt"),
    _SUBSURFACE_BARRIERS_AVAIL_SQL: ("mapunit", "component", "corestrictions"),
    _SEASONAL_HYDROLOGY_AVAIL_SQL: ("mapunit", "component", "comonth", "cosoilmoist"),
    _ECOLOGICAL_SITE_AVAIL_SQL: ("mapunit", "component", "coecoclass"),
    _PARENT_MATERIAL_AVAIL_SQL: ("mapunit", "component", "copmgrp", "copm"),
    _SOIL_TEMPERATURE_AVAIL_SQL: ("mapunit", "component", "comonth", "cosoiltemp"),
}


# ---------------------------------------------------------------------------
# Core query logic (sync, testable without MCP)
# ---------------------------------------------------------------------------


def _sanitize_variable(var: str) -> str:
    """Raise ValueError if *var* is not a safe SQL identifier."""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", var):
        raise ValueError(
            f"Invalid variable name {var!r}. "
            "Variable names must contain only letters, digits, and underscores."
        )
    return var


_RULE_NAME_RE = re.compile(r"^[A-Za-z0-9 \-\(\)\.,/&%]+$")


def _sanitize_rule_name(name: str) -> str:
    """Validate a cointerp rule name and escape single quotes for SQL."""
    if not _RULE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid rule name {name!r}. Rule names must contain only "
            "letters, digits, spaces, and common punctuation."
        )
    return name.replace("'", "''")


def _get_column_table_map() -> dict[str, str]:
    """Build and cache physical column → owning table for all SSURGO query tables.

    Queries each table in ``_COLUMN_TABLE_PRIORITY`` via ``SELECT TOP 1 *``
    and parses the XSD schema embedded in the SDA response.  Each column name
    is stored only once (first wins), so shared FK names such as ``mukey``
    and ``cokey`` resolve to their PK table.  Results are cached for the
    lifetime of the process.
    """
    if _COLUMN_TABLE_CACHE:
        return _COLUMN_TABLE_CACHE
    for table in _COLUMN_TABLE_PRIORITY:
        try:
            for col in _sda_table_columns(table):
                if col not in _COLUMN_TABLE_CACHE:
                    _COLUMN_TABLE_CACHE[col] = table
        except Exception:
            pass  # skip unavailable tables; unresolved columns stay unqualified
    return _COLUMN_TABLE_CACHE


def _qualify(col: str) -> str:
    """Return the table-qualified form of *col* if its table is known."""
    table = _get_column_table_map().get(col)
    return f"{table}.{col}" if table else col


def _resolve_variables(variables: list[str]) -> list[str]:
    """Validate *variables* and return them."""
    for v in variables:
        _sanitize_variable(v)
    return variables


def _resolve_rule_names(rule_names: list[str]) -> list[str]:
    """Validate *rule_names* and return them."""
    for n in rule_names:
        _sanitize_rule_name(n)
    return rule_names


def _build_soil_profile_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → chorizon."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN chorizon ON chorizon.cokey = component.cokey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey, chorizon.hzdepb_r"""


def _build_area_summary_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → muaggatt (one aggregated row per map unit)."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN muaggatt ON muaggatt.mukey = mapunit.mukey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        ORDER BY mapunit.mukey"""


def _build_subsurface_barriers_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → corestrictions."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN corestrictions ON corestrictions.cokey = component.cokey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey, corestrictions.resdept_r"""


def _build_seasonal_hydrology_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → comonth → cosoilmoist."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN comonth ON comonth.cokey = component.cokey
        LEFT JOIN cosoilmoist ON cosoilmoist.comonthkey = comonth.comonthkey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey,
                 comonth.comonthkey, cosoilmoist.soimoistdept_r"""


def _build_soil_suitability_sql(wkt: str, rule_names: list[str]) -> str:
    """SQL for mapunit → component → cointerp filtered by rule names."""
    safe_names = [_sanitize_rule_name(n) for n in rule_names]
    names_sql = ", ".join(f"'{n}'" for n in safe_names)
    return f"""\
        SELECT
            mapunit.mukey,
            mapunit.muname,
            component.compname,
            component.comppct_r,
            cointerp.mrulename,
            cointerp.interplrc,
            cointerp.interphr
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        JOIN cointerp ON cointerp.cokey = component.cokey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        AND cointerp.mrulename IN ({names_sql})
        ORDER BY mapunit.mukey, component.cokey, cointerp.mrulename"""


def _build_ecological_site_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → coecoclass."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN coecoclass ON coecoclass.cokey = component.cokey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey, coecoclass.ecoclassid"""


def _build_parent_material_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → copmgrp → copm."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN copmgrp ON copmgrp.cokey = component.cokey
        LEFT JOIN copm ON copm.copmgrpkey = copmgrp.copmgrpkey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey,
                 copmgrp.pmgroupname, copm.pmkind"""


def _build_soil_temperature_sql(wkt: str, variables: list[str]) -> str:
    """SQL for mapunit → component → comonth → cosoiltemp."""
    select_vars = ",\n            ".join(_qualify(v) for v in variables)
    return f"""\
        SELECT
            {select_vars}
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN comonth ON comonth.cokey = component.cokey
        LEFT JOIN cosoiltemp ON cosoiltemp.comonthkey = comonth.comonthkey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey,
                 comonth.comonthkey, cosoiltemp.dept_r"""


def _parse_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parse SDA XML response into a list of column-keyed dicts.

    The SDA tabular service returns XML where the root is ``<NewDataSet>`` and
    each row is a ``<Table>`` element whose children are named after the
    SELECT columns.  Returns an empty list when the dataset is empty.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    records: list[dict[str, Any]] = []
    for table_el in root.findall(".//Table"):
        row: dict[str, Any] = {}
        for child in table_el:
            row[child.tag] = child.text  # None for SQL NULL values
        if row:
            records.append(row)
    return records


def _fetch_sda(sql: str) -> tuple[list[dict[str, Any]], float]:
    """Post *sql* to SDA and return ``(records, latency_s)``.

    Returns an empty records list when the response contains no rows (e.g.
    the geometry falls outside SSURGO coverage).
    """
    t0 = time.perf_counter()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(_SDA_URL, data={"query": sql})
        resp.raise_for_status()
    latency = time.perf_counter() - t0
    return _parse_xml(resp.text), latency


def _sda_table_columns(table: str) -> list[str]:
    """Return column names for *table* by parsing the XSD schema in a TOP-1 SDA response.

    The SDA tabular service embeds an ``xs:element`` schema in each response.
    Requesting a single row is enough to trigger schema generation; the
    returned column names are then used to build the column→table cache
    without relying on the ``mdstatcolmas`` metadata catalogue.
    """
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(_SDA_URL, data={"query": f"SELECT TOP 1 * FROM {table}"})
        resp.raise_for_status()
    root = ET.fromstring(resp.text)
    return [
        el.get("name")
        for el in root.findall(f".//{{{_XS_NS}}}element")
        if el.get("name") not in (None, "NewDataSet", "Table")
    ]


def _get_variable_info(avail_sql: str) -> dict[str, dict[str, str]]:
    """Fetch and cache variable metadata for the tables associated with *avail_sql*.

    Tries the ``mdstatcolmas`` catalogue query first.  If that table is
    unavailable (the SDA returns HTTP 400), falls back to discovering column
    names from the actual data tables via ``SELECT TOP 1 *`` and the XSD
    schema embedded in the response.  Metadata fields (label, description,
    units) are left blank in the fallback case.

    Returns a flat dict keyed by physical column name.  Each value contains
    ``"table"``, ``"label"``, ``"description"``, and ``"units"`` entries.
    Results are cached for the lifetime of the process.
    """
    if avail_sql in _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE[avail_sql]
    info: dict[str, dict[str, str]] = {}
    try:
        records, _ = _fetch_sda(avail_sql)
        for row in records:
            col = row.get("colphyname") or ""
            if col:
                info[col] = {
                    "table": row.get("tabphyname") or "",
                    "label": row.get("collogname") or "",
                    "description": row.get("coldesc") or "",
                    "units": row.get("uomabbrev") or "",
                }
    except Exception:
        # mdstatcolmas catalogue unavailable — fall back to schema discovery.
        for table in _AVAIL_SQL_TABLES.get(avail_sql, ()):
            try:
                for col in _sda_table_columns(table):
                    if col not in info:
                        info[col] = {
                            "table": table,
                            "label": "",
                            "description": "",
                            "units": "",
                        }
            except Exception:
                pass
        if not info:
            raise  # Both the catalogue query and all schema discovery failed
    _VARIABLE_INFO_CACHE[avail_sql] = info
    return info


def _available_vars_response(avail_sql: str, query_type: str) -> dict[str, Any]:
    """Query SDA column metadata and return variables grouped by table."""
    t0 = time.perf_counter()
    try:
        info = _get_variable_info(avail_sql)
        latency = time.perf_counter() - t0
        by_table: dict[str, list[dict[str, Any]]] = {}
        for col, meta in info.items():
            table = meta["table"] or "unknown"
            by_table.setdefault(table, []).append(
                {
                    "variable": col,
                    "label": meta["label"],
                    "description": meta["description"],
                    "units": meta["units"],
                }
            )
        return {
            "variables": by_table,
            "_meta": build_meta(
                source="ssurgo",
                query_params={"query_type": query_type},
                rows_returned=len(info),
                latency_s=latency,
                license_info=LICENSE_INFO,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "variables": {},
            "_meta": build_meta(
                source="ssurgo",
                query_params={"query_type": query_type},
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }


def _point_query(
    latitude: float,
    longitude: float,
    variables: list[str],
    avail_sql: str,
    sql_builder: Any,
    max_runtime_s: float | None,
    query_type: str,
) -> dict[str, Any]:
    """Shared implementation for all point-query MCP tools."""
    if warn := check_runtime("ssurgo", 0, 0.0, max_runtime_s):
        return warn
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError(f"latitude and longitude must be finite; got {latitude!r}, {longitude!r}")
    try:
        vars_ = _resolve_variables(variables)
    except ValueError as exc:
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params={"latitude": latitude, "longitude": longitude},
                rows_returned=0,
                latency_s=0.0,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }
    wkt = f"POINT({float(longitude)} {float(latitude)})"
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "variables": vars_,
        "max_runtime_s": max_runtime_s,
        "query_type": query_type,
    }
    t0 = time.perf_counter()
    try:
        full_info = _get_variable_info(avail_sql)
        sql = sql_builder(wkt, vars_)
        records, latency = _fetch_sda(sql)
        vinfo = {v: full_info[v] for v in vars_ if v in full_info}
        return {
            "data": records,
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                variable_info=vinfo,
                error=_NO_COVERAGE_MSG if not records else None,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }


def _bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str],
    avail_sql: str,
    sql_builder: Any,
    max_runtime_s: float | None,
    query_type: str,
) -> dict[str, Any]:
    """Shared implementation for all bbox-query MCP tools."""
    bbox = {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
    area_deg2 = (max_lat - min_lat) * (max_lon - min_lon)
    if warn := check_runtime("ssurgo", 0, area_deg2, max_runtime_s):
        return warn
    base_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }
    try:
        vars_ = _resolve_variables(variables)
    except ValueError as exc:
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params=base_params,
                rows_returned=0,
                latency_s=0.0,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }
    wkt = bbox_to_wkt_polygon(bbox)
    query_params: dict[str, Any] = {
        **base_params,
        "variables": vars_,
        "max_runtime_s": max_runtime_s,
        "query_type": query_type,
    }
    t0 = time.perf_counter()
    try:
        full_info = _get_variable_info(avail_sql)
        sql = sql_builder(wkt, vars_)
        records, latency = _fetch_sda(sql)
        vinfo = {v: full_info[v] for v in vars_ if v in full_info}
        return {
            "data": records,
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                variable_info=vinfo,
                error=_NO_COVERAGE_MSG if not records else None,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }


# ---------------------------------------------------------------------------
# MCP tools — Type 1: soil_profile
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_soil_profile_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO soil profile queries.

    Queries the SDA column catalogue for the tables joined in soil profile
    queries: ``mapunit``, ``component``, and ``chorizon``.  Use the
    ``variable`` values as the ``variables`` argument to
    ``ssurgo_soil_profile_query`` or ``ssurgo_soil_profile_bbox_query``.
    """
    return _available_vars_response(_SOIL_PROFILE_AVAIL_SQL, "soil_profile")


@mcp.tool()
def ssurgo_soil_profile_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_SOIL_PROFILE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil profile data for a point location.

    Returns per-horizon physical and chemical properties for the major soil
    components at the given location.  Default variables include texture
    (sand/silt/clay), pH, organic matter, saturated hydraulic conductivity,
    available water capacity, and bulk density.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include in the response.  Defaults to a
            curated horizon-property set.  Call
            ``ssurgo_soil_profile_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _SOIL_PROFILE_AVAIL_SQL,
        _build_soil_profile_sql,
        max_runtime_s,
        "soil_profile",
    )


@mcp.tool()
def ssurgo_soil_profile_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_SOIL_PROFILE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil profile data for all map units in a bounding box.

    Returns per-horizon data for every soil map unit whose boundary intersects
    the requested bounding box.  Large regions can return many records; use
    ``max_runtime_s`` to add a runtime guard.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.  Defaults to the same curated
            set as ``ssurgo_soil_profile_query``.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _SOIL_PROFILE_AVAIL_SQL,
        _build_soil_profile_sql,
        max_runtime_s,
        "soil_profile",
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 2: area_summary
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_area_summary_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO area summary queries.

    Queries the SDA column catalogue for ``mapunit`` and ``muaggatt``.  Use
    the ``variable`` values as the ``variables`` argument to
    ``ssurgo_area_summary_query`` or ``ssurgo_area_summary_bbox_query``.
    """
    return _available_vars_response(_AREA_SUMMARY_AVAIL_SQL, "area_summary")


@mcp.tool()
def ssurgo_area_summary_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_AREA_SUMMARY_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO pre-aggregated area summary data for a point location.

    Returns one row per map unit with NRCS-precomputed weighted averages:
    drainage class, hydrologic group, available water storage, soil organic
    carbon stock, crop productivity index, flooding frequency, and water table
    depth.  No per-horizon aggregation is needed.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_area_summary_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _AREA_SUMMARY_AVAIL_SQL,
        _build_area_summary_sql,
        max_runtime_s,
        "area_summary",
    )


@mcp.tool()
def ssurgo_area_summary_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_AREA_SUMMARY_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO area summary data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.  Defaults to the same curated
            set as ``ssurgo_area_summary_query``.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _AREA_SUMMARY_AVAIL_SQL,
        _build_area_summary_sql,
        max_runtime_s,
        "area_summary",
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 3: subsurface_barriers
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_subsurface_barriers_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO subsurface barrier queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``, and
    ``corestrictions``.
    """
    return _available_vars_response(_SUBSURFACE_BARRIERS_AVAIL_SQL, "subsurface_barriers")


@mcp.tool()
def ssurgo_subsurface_barriers_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO subsurface barrier (restrictive layer) data for a point.

    Returns depth and hardness of layers that limit rooting, drainage, or
    excavation, such as bedrock, fragipan, duripan, and cemented horizons.
    Rows with no restrictive layers will have NULL values for restriction
    columns.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_subsurface_barriers_available_variables()`` for the full
            list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _SUBSURFACE_BARRIERS_AVAIL_SQL,
        _build_subsurface_barriers_sql,
        max_runtime_s,
        "subsurface_barriers",
    )


@mcp.tool()
def ssurgo_subsurface_barriers_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_SUBSURFACE_BARRIERS_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO subsurface barrier data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _SUBSURFACE_BARRIERS_AVAIL_SQL,
        _build_subsurface_barriers_sql,
        max_runtime_s,
        "subsurface_barriers",
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 4: seasonal_hydrology
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_seasonal_hydrology_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO seasonal hydrology queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``,
    ``comonth``, and ``cosoilmoist``.
    """
    return _available_vars_response(_SEASONAL_HYDROLOGY_AVAIL_SQL, "seasonal_hydrology")


@mcp.tool()
def ssurgo_seasonal_hydrology_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO seasonal hydrology data for a point location.

    Returns monthly flooding frequency, ponding, and water table depth for
    the major soil components.  Typically 12 rows per component (one per
    calendar month).  Months with no wet-layer data will have NULL values for
    ``soimoistdept_r`` and ``soimoiststat``.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_seasonal_hydrology_available_variables()`` for the full
            list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _SEASONAL_HYDROLOGY_AVAIL_SQL,
        _build_seasonal_hydrology_sql,
        max_runtime_s,
        "seasonal_hydrology",
    )


@mcp.tool()
def ssurgo_seasonal_hydrology_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_SEASONAL_HYDROLOGY_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO seasonal hydrology data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _SEASONAL_HYDROLOGY_AVAIL_SQL,
        _build_seasonal_hydrology_sql,
        max_runtime_s,
        "seasonal_hydrology",
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 5: soil_suitability
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_soil_suitability_available_variables() -> dict[str, Any]:
    """Return all available interpretation rule names for SSURGO soil suitability queries.

    Queries ``cointerp`` for distinct ``mrulename`` values.  Use these names
    as the ``rule_names`` argument to ``ssurgo_soil_suitability_query`` or
    ``ssurgo_soil_suitability_bbox_query``.
    """
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(_SDA_URL, data={"query": _SOIL_SUITABILITY_RULES_SQL})
            resp.raise_for_status()
        latency = time.perf_counter() - t0
        records = _parse_xml(resp.text)
        rule_names = [r["mrulename"] for r in records if r.get("mrulename")]
        return {
            "rule_names": rule_names,
            "_meta": build_meta(
                source="ssurgo",
                query_params={"query_type": "soil_suitability"},
                rows_returned=len(rule_names),
                latency_s=latency,
                license_info=LICENSE_INFO,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "rule_names": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params={"query_type": "soil_suitability"},
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }


@mcp.tool()
def ssurgo_soil_suitability_query(
    latitude: float,
    longitude: float,
    rule_names: list[str] = DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil suitability (interpretation) data for a point location.

    Returns pre-computed NRCS suitability ratings for the requested
    interpretation rules.  Each row contains the rule name, a class label
    (e.g. 'Not limited', 'Very limited'), and a numeric rating (0–1).

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        rule_names: Interpretation rule names to query.  Defaults to a set
            covering construction suitability, septic systems, agricultural
            capability, and hydric soil status.  Call
            ``ssurgo_soil_suitability_available_variables()`` for all rules.
        max_runtime_s: Optional request timeout in seconds.
    """
    if warn := check_runtime("ssurgo", 0, 0.0, max_runtime_s):
        return warn
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError(f"latitude and longitude must be finite; got {latitude!r}, {longitude!r}")
    try:
        names = _resolve_rule_names(rule_names)
    except ValueError as exc:
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params={"latitude": latitude, "longitude": longitude},
                rows_returned=0,
                latency_s=0.0,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }
    wkt = f"POINT({float(longitude)} {float(latitude)})"
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "rule_names": names,
        "max_runtime_s": max_runtime_s,
        "query_type": "soil_suitability",
    }
    t0 = time.perf_counter()
    try:
        sql = _build_soil_suitability_sql(wkt, names)
        records, latency = _fetch_sda(sql)
        return {
            "data": records,
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                error=_NO_COVERAGE_MSG if not records else None,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }


@mcp.tool()
def ssurgo_soil_suitability_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    rule_names: list[str] = DEFAULT_SOIL_SUITABILITY_RULE_NAMES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil suitability data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        rule_names: Interpretation rule names to query.  Defaults to the same
            set as ``ssurgo_soil_suitability_query``.
        max_runtime_s: Optional request timeout in seconds.
    """
    bbox = {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
    area_deg2 = (max_lat - min_lat) * (max_lon - min_lon)
    if warn := check_runtime("ssurgo", 0, area_deg2, max_runtime_s):
        return warn
    base_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }
    try:
        names = _resolve_rule_names(rule_names)
    except ValueError as exc:
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params=base_params,
                rows_returned=0,
                latency_s=0.0,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }
    wkt = bbox_to_wkt_polygon(bbox)
    query_params: dict[str, Any] = {
        **base_params,
        "rule_names": names,
        "max_runtime_s": max_runtime_s,
        "query_type": "soil_suitability",
    }
    t0 = time.perf_counter()
    try:
        sql = _build_soil_suitability_sql(wkt, names)
        records, latency = _fetch_sda(sql)
        return {
            "data": records,
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                error=_NO_COVERAGE_MSG if not records else None,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }


# ---------------------------------------------------------------------------
# MCP tools — Type 6: ecological_site
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_ecological_site_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO ecological site queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``, and
    ``coecoclass``.
    """
    return _available_vars_response(_ECOLOGICAL_SITE_AVAIL_SQL, "ecological_site")


@mcp.tool()
def ssurgo_ecological_site_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO ecological site classification data for a point location.

    Returns ecological site IDs and names that link soil to its vegetation
    potential (rangeland and forest ecological sites).  Rows with no
    ecological site classification will have NULL values for ``ecoclassid``
    and related columns.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_ecological_site_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _ECOLOGICAL_SITE_AVAIL_SQL,
        _build_ecological_site_sql,
        max_runtime_s,
        "ecological_site",
    )


@mcp.tool()
def ssurgo_ecological_site_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_ECOLOGICAL_SITE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO ecological site data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _ECOLOGICAL_SITE_AVAIL_SQL,
        _build_ecological_site_sql,
        max_runtime_s,
        "ecological_site",
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 7: parent_material
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_parent_material_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO parent material queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``,
    ``copmgrp``, and ``copm``.
    """
    return _available_vars_response(_PARENT_MATERIAL_AVAIL_SQL, "parent_material")


@mcp.tool()
def ssurgo_parent_material_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_PARENT_MATERIAL_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO parent material data for a point location.

    Returns geological information about what the soil formed from (loess,
    alluvium, glacial till, volcanic ash, residuum, etc.) and its origin
    (igneous, sedimentary, metamorphic).  Rows with no parent material data
    will have NULL values for parent material columns.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_parent_material_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _PARENT_MATERIAL_AVAIL_SQL,
        _build_parent_material_sql,
        max_runtime_s,
        "parent_material",
    )


@mcp.tool()
def ssurgo_parent_material_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_PARENT_MATERIAL_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO parent material data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _PARENT_MATERIAL_AVAIL_SQL,
        _build_parent_material_sql,
        max_runtime_s,
        "parent_material",
    )


# ---------------------------------------------------------------------------
# MCP tools — Type 8: soil_temperature
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_soil_temperature_available_variables() -> dict[str, Any]:
    """Return all available variable names for SSURGO soil temperature queries.

    Queries the SDA column catalogue for ``mapunit``, ``component``,
    ``comonth``, and ``cosoiltemp``.
    """
    return _available_vars_response(_SOIL_TEMPERATURE_AVAIL_SQL, "soil_temperature")


@mcp.tool()
def ssurgo_soil_temperature_query(
    latitude: float,
    longitude: float,
    variables: list[str] = DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil temperature data for a point location.

    Returns mean monthly soil temperature by depth for the dominant soil
    component.  Each row represents one month at one depth increment, giving
    a full seasonal and depth profile of soil thermal conditions.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to include.  Call
            ``ssurgo_soil_temperature_available_variables()`` for the full list.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _point_query(
        latitude,
        longitude,
        variables,
        _SOIL_TEMPERATURE_AVAIL_SQL,
        _build_soil_temperature_sql,
        max_runtime_s,
        "soil_temperature",
    )


@mcp.tool()
def ssurgo_soil_temperature_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str] = DEFAULT_SOIL_TEMPERATURE_VARIABLES,
    max_runtime_s: float | None = None,
) -> dict[str, Any]:
    """Query USDA SSURGO soil temperature data for all map units in a bounding box.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
        variables: Variable names to return.
        max_runtime_s: Optional request timeout in seconds.
    """
    return _bbox_query(
        min_lat,
        max_lat,
        min_lon,
        max_lon,
        variables,
        _SOIL_TEMPERATURE_AVAIL_SQL,
        _build_soil_temperature_sql,
        max_runtime_s,
        "soil_temperature",
    )
