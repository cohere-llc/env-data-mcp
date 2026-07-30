"""Constants, default variable lists, and SQL strings for the SSURGO adapter."""

from __future__ import annotations

from enum import StrEnum

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

SDA_URL = "https://sdmdataaccess.nrcs.usda.gov/Tabular/SDMTabularService/post.rest"

# ---------------------------------------------------------------------------
# Type 1: soil_profile  (mapunit → component → chorizon)
# ---------------------------------------------------------------------------

DEFAULT_SOIL_PROFILE_VARIABLES: list[str] = [
    # compname, comppct_r, hzname, hzdept_r, hzdepb_r are always present
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
    # mukey and muname are always present at the group level
    # --- Water regime (primary driver of redox → microbial community structure) ---
    "drclassdcd",  # Drainage class: controls aerobic/anaerobic niches and redox potential
    "hydgrpdcd",  # Hydrologic group: infiltration/runoff; sets water residence time in profile
    "wtdepannmin",  # Annual minimum water table depth: extent of permanently anaerobic zone
    # April–June minimum water table: growing-season saturation, peak bio activity
    "wtdepaprjunmin",
    # Flooding frequency: episodic anaerobic pulses that reshape microbial communities
    "flodfreqdcd",
    # Ponding presence: surface saturation events affect surface-horizon decomposition
    "pondfreqprs",
    # --- Plant-available water / primary productivity ---
    "aws0150wta",  # Available water storage 0–150 cm: limits plant productivity → organic C inputs
    # --- Physical constraints on rooting and C pool depth ---
    # Minimum bedrock depth: caps rooting depth and total soil volume for microbial activity
    "brockdepmin",
    "slopegradwta",  # Weighted-average slope: erosion risk; affects organic matter retention
    # --- Wetland / carbon sequestration indicators ---
    # Hydric soil presence: predicts methanogenic potential and anaerobic C transformation
    "hydclprs",
    # --- Land-use context ---
    "farmlndcl",  # Farmland classification: distinguishes prime farmland from marginal land
    "niccdcd",  # Non-irrigated capability class: overall productivity rating for site comparison
]

# ---------------------------------------------------------------------------
# Type 3: subsurface_barriers  (mapunit → component → corestrictions)
# ---------------------------------------------------------------------------

DEFAULT_SUBSURFACE_BARRIERS_VARIABLES: list[str] = [
    # compname, comppct_r, reskind, resdept_r, resdepb_r are always present
    # --- Restriction physical properties ---
    "reshard",  # Hardness: determines root/organism penetrability and water impedance strength
    # Thickness: thicker restrictions form more persistent barriers to water/gas movement
    "resthk_r",
    # --- Resulting soil conditions (component table) ---
    # Drainage class: whether the barrier creates a perched water table → anaerobic zone
    "drainagecl",
    # Hydric rating: anaerobic C transformation and methanogenic potential above the barrier
    "hydricrating",
    # --- Taxonomic / site context ---
    # Soil subgroup: taxonomic classification that encodes restriction type and moisture regime
    "taxsubgrp",
    "slope_r",  # Slope gradient: with a subsurface barrier, controls lateral flow of perched water
]

# ---------------------------------------------------------------------------
# Type 4: seasonal_hydrology  (mapunit → component → comonth → cosoilmoist)
# ---------------------------------------------------------------------------

DEFAULT_SEASONAL_HYDROLOGY_VARIABLES: list[str] = [
    # compname, comppct_r, monthseq, soimoistdept_r, soimoistdepb_r are always present
    # --- Temporal label ---
    "month",  # Month name: human-readable label for monthseq integer
    # --- Moisture status (cosoilmoist): core output per depth interval per month ---
    # Moisture status: wet/moist/saturated; indicates anaerobic conditions by depth/season
    "soimoiststat",
    # --- Flooding (comonth): episodic deep anaerobic pulses ---
    # Flooding frequency: how often flooding occurs → episodic community-resetting anaerobic events
    "flodfreqcl",
    # Flooding duration: how long flood events persist → magnitude and severity of anaerobic pulse
    "floddurcl",
    # --- Ponding (comonth): surface saturation and O2 depletion ---
    "pondfreqcl",  # Ponding frequency: recurrence of surface water accumulation
    # Ponding duration: how long surface water persists → extended surface O2 depletion
    "ponddurcl",
    # --- Water balance drivers (comonth) ---
    # Daily precipitation [mm]: monthly moisture input that drives saturation events
    "dlyavgprecip_r",
    # Daily potential ET [mm]: monthly moisture loss; net precip–ET balance sets saturation duration
    "dlyavgpotet_r",
]

# ---------------------------------------------------------------------------
# Type 5: soil_suitability  (mapunit → component → cointerp)
# Note: selectable parameter is rule_names, not variable names.
# Output columns are fixed: mukey, muname, compname, comppct_r,
#                           mrulename, interplrc, interphr
# ---------------------------------------------------------------------------

DEFAULT_SOIL_SUITABILITY_RULE_NAMES: list[str] = [
    # --- Soil carbon stocks (C cycling, bioenergy C budgets) ---
    # Quantified SOC to 2 m: primary C substrate driving microbial community composition
    "CLASS RULE - Soil Organic Carbon kg/m2 to 2m (NPS)",
    # Inorganic C stock: completes C budget; carbonate-cycling microbial pathways and pH buffering
    "CLASS RULE - Soil Inorganic Carbon kg/m2 to 2m (NPS)",
    # --- Soil health / biological habitat ---
    # USDA rating of aerobic-biota habitat: integrates drainage, aeration, and OM into one index
    "SOH - Limitations for Aerobic Soil Organisms",
    # Risk of OM loss under land use change: predicts vulnerability of microbial C substrate pool
    "SOH - Organic Matter Depletion",
    # Compaction reduces macroporosity and O2 diffusion: shifts aerobic → anaerobic communities
    "SOH - Soil Susceptibility to Compaction",
    # --- Bioenergy feedstock productivity ---
    # National standardized index: benchmarks bioenergy feedstock potential across CONUS
    "NCCPI - National Commodity Crop Productivity Index (Ver 3.0)",
    # --- Nutrient / organic compound mobility ---
    # Organic compound mobility to groundwater: proxy for DOC and nutrient leaching to subsurface
    "AGR - Pesticide Loss Potential-Leaching",
]

# ---------------------------------------------------------------------------
# Type 6: ecological_site  (mapunit → component → coecoclass)
# ---------------------------------------------------------------------------

DEFAULT_ECOLOGICAL_SITE_VARIABLES: list[str] = [
    # compname, comppct_r, ecoclassid, ecoclassname are always present
    # --- Ecological classification metadata ---
    # Classification type (rangeland/forest/non-site): sets vegetation community context for C input
    "ecoclasstypename",
    # Reference to ESIS description: look-up of plant community, production, and disturbance data
    "ecoclassref",
    # Status (approved/draft): indicates reliability of the ecological site description
    "ecositestatus",
    # --- Component-level context ---
    # Major component flag: identifies dominant soil in the map unit (most representative)
    "majcompflag",
    # Drainage class: aerobic/anaerobic status; links ecological site to microbial redox regime
    "drainagecl",
]

# ---------------------------------------------------------------------------
# Type 7: parent_material  (mapunit → component → copmgrp → copm)
# ---------------------------------------------------------------------------

DEFAULT_PARENT_MATERIAL_VARIABLES: list[str] = [
    # compname, comppct_r, pmgroupname, pmkind, pmorigin are always present
    # --- Layer geometry ---
    # Vertical stacking order: distinguishes topmost from deeper PM layers in multi-PM profiles
    "pmorder",
    # Top depth [cm]: upper bound of this PM layer's mineral weathering and nutrient-release zone
    "pmdept_r",
    # Bottom depth [cm]: lower bound; full thickness of PM influence on rooting, microbial habitat
    "pmdepb_r",
    # --- Textural/compositional refinement ---
    # Textural modifier (gravelly/silty/etc.): pore size, water retention, and habitat heterogeneity
    "pmmodifier",
    # General modifier: broader compositional descriptor (e.g. organic vs mineral character of PM)
    "pmgenmod",
]

# ---------------------------------------------------------------------------
# Type 8: soil_temperature  (mapunit → component → comonth → cosoiltemp)
# ---------------------------------------------------------------------------

DEFAULT_SOIL_TEMPERATURE_VARIABLES: list[str] = [
    # compname, comppct_r, monthseq, soitempdept_r, soitempdepb_r are always present
    "month",  # Month name: human-readable label for monthseq integer
    # Monthly soil temperature [°C]: primary driver of microbial activity rates (Q10/Arrhenius)
    "soitempmm",
    # MAST [°C]: Mean Annual Soil Temperature; temperature regime boundary (cryic/mesic/thermic)
    "soiltempa_r",
    # Temperature regime: predicts microbial community composition and C decomposition rates
    "taxtempregime",
    # MAAT [°C]: air-soil coupling; MAST offset indicates organic/snow insulation of soil profile
    "airtempa_r",
    # Frost-free days: proxy for freeze-thaw cycle intensity, a major driver of labile C release
    "ffd_r",
]

# ---------------------------------------------------------------------------
# XSD schema discovery constants
# ---------------------------------------------------------------------------

# XML namespace used when parsing XSD schemas embedded in SDA tabular responses.
XS_NS = "http://www.w3.org/2001/XMLSchema"

# Tables in the order used to build the column → table mapping.  PK-owning
# tables must appear before FK tables so that shared column names (e.g.
# ``mukey`` appears in both mapunit and component) resolve to the
# primary-key table (first-wins insertion into ``_COLUMN_TABLE_CACHE``).
COLUMN_TABLE_PRIORITY: tuple[str, ...] = (
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
# Per-type query identifier (used as a cache key in _VARIABLE_INFO_CACHE)
# ---------------------------------------------------------------------------


class QueryType(StrEnum):
    """Identifier for each SSURGO data query type; doubles as a cache key."""

    SOIL_PROFILE = "soil_profile"
    AREA_SUMMARY = "area_summary"
    SUBSURFACE_BARRIERS = "subsurface_barriers"
    SEASONAL_HYDROLOGY = "seasonal_hydrology"
    ECOLOGICAL_SITE = "ecological_site"
    PARENT_MATERIAL = "parent_material"
    SOIL_TEMPERATURE = "soil_temperature"


SOIL_SUITABILITY_RULES_SQL = """\
SELECT DISTINCT mrulename
FROM cointerp
ORDER BY mrulename"""

# Mapping from query type -> SDA tables whose XSD schemas are introspected to
# discover available column names.
AVAIL_SQL_TABLES: dict[QueryType, tuple[str, ...]] = {
    QueryType.SOIL_PROFILE: ("mapunit", "component", "chorizon"),
    QueryType.AREA_SUMMARY: ("mapunit", "muaggatt"),
    QueryType.SUBSURFACE_BARRIERS: ("mapunit", "component", "corestrictions"),
    QueryType.SEASONAL_HYDROLOGY: ("mapunit", "component", "comonth", "cosoilmoist"),
    QueryType.ECOLOGICAL_SITE: ("mapunit", "component", "coecoclass"),
    QueryType.PARENT_MATERIAL: ("mapunit", "component", "copmgrp", "copm"),
    QueryType.SOIL_TEMPERATURE: ("mapunit", "component", "comonth", "cosoiltemp"),
}
