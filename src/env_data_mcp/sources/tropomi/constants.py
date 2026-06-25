"""Constants, enums, default variables lists, and URLs for the Sentinel 5-TROPOMI adapter."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# License and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "description": (
        "This data set consists of observations from the Sentinel-5 Precursor "
        "(Sentinel-5P) satellite of the European Commission's Copernicus Earth "
        "Observation Programme. Sentinel-5P is a polar orbiting satellite that "
        "completes 14 orbits of the Earth a day. It carries the TROPOspheric "
        "Monitoring Instrument (TROPOMI) which is a spectrometer that senses "
        "ultraviolet (UV), visible (VIS), near (NIR) and short wave infrared "
        "(SWIR) to monitor ozone, methane, formaldehyde, aerosol, carbon monoxide, "
        "nitrogen dioxide and sulphur dioxide in the atmosphere. The satellite was "
        "launched in October 2017 and entered routine operational phase in March "
        "2019. Data is available from July 2018 onwards."
    ),
    "description_url": "https://registry.opendata.aws/sentinel5p/",
    "citation": "Sentinel-5P Level 2 was accessed on DATE from https://registry.opendata.aws/sentinel5p.",
    "license_url": "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice",
}

# ---------------------------------------------------------------------------
# Query endpoints
# ---------------------------------------------------------------------------

# AWS URL for Sentinel-5
#  add "COGT/{PRODUCT_TYPE}/catalog.json" to get full path to catalog
_AWS_URL: str = "https://meeo-s5p.s3.amazonaws.com/"

# API for figuring out set of S3 keys to query for a given date/location
_CDSE_ODATA_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"

# ---------------------------------------------------------------------------
# Variable info
# ---------------------------------------------------------------------------

DEFAULT_VARIABLES: list[str] = [
    "OFFL-L2_CH4",  # methane total-column mixing ratio
    "OFFL-L2_NO2",  # nitrogen dioxide total-column concentration
    "OFFL-L2_CO",  # carbon monoxide total-column concentration
    "OFFL-L2_O3_TCL",  # tropospheric ozone concentration
    "OFFL-L2_SO2",  # sulfur dioxide total-column concetration
    "OFFL-L2_HCHO",  # formaldehyde total-column concentration
]

_PRODUCT_TYPES: dict[str, str] = {
    "NRTI": "Near real-time",
    "OFFL": "Offline processed",
    "RPRO": "Reprocessed",
}

# Units were extracted from the PDFs describing each products. There does not
# appear to be a feasible way of accessing these programmatically, so we'll
# hard-code them here and let any mismatches just result in "unknown" units.
# source: https://sentiwiki.copernicus.eu/web/s5p-products
_UNITS_MAP: dict[str, str] = {
    "L2_CH4": "ppb",
    "L2_SO2": "mol m-2",
    "L2_AER_AI": "unitless",
    "L2_CO": "mol m-2",
    "L2_HCHO": "mol m-2",
    "L2_NO2": "mol m-2",
    "L2_CLOUD": "unitless",
    "L2_O3": "DU",
    "L2_AER_LH": "m",
    "L2_O3_TCL": "DU",
}
