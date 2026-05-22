"""Constants, default variable lists, and SQL strings for the SSURGO adapter."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Licence and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "Public domain (USDA/US Government).",
    "license_url": (
        "https://www.nrcs.usda.gov/resources/data-and-reports/"
        "soil-survey-geographic-database-ssurgo"
    ),
    "citation": "Soil Survey Staff, Natural Resources Conservation Service, "
    "United States Department of Agriculture. Web Soil Survey. Available online "
    "at https://websoilsurvey.nrcs.usda.gov/. Accessed [month/day/year].",
    "description_url": "https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo",
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
    # --- Identity & provenance ---
    "mukey",  # Mapunit Key
    "muname",  # Mapunit Name
    "compname",  # Component Name
    "majcompflag",  # Major Component
    "comppct_r",  # Comp % [percent]
    # --- Depth profile ---
    "hzdept_r",  # Top Depth [cm]
    "hzdepb_r",  # Bottom Depth [cm]
    # --- Texture ---
    "sandtotal_r",  # Total Sand [percent]
    "silttotal_r",  # Total Silt [percent]
    "claytotal_r",  # Total Clay [percent]
    # --- Biogeochemistry ---
    "ph1to1h2o_r",  # pH H2O
    "om_r",  # OM [percent]
    "cec7_r",  # CEC-7 [cmol(+)/kg]
    # --- Physical / hydraulic ---
    "ksat_r",  # Ksat [um/s]
    "awc_r",  # AWC [cm/cm]
    "dbthirdbar_r",  # Db 0.33 bar H2O [g/cm3]
    # --- Ecological context ---
    "drainagecl",  # Drainage Class
    "taxorder",  # Order
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
    "soitempdept_r",
    "soitempdepb_r",
    "soitempmm",
]

# ---------------------------------------------------------------------------
# XSD schema discovery constants
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Per-type available-variables SQL (queries SDA built-in column catalogue)
# ---------------------------------------------------------------------------

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
