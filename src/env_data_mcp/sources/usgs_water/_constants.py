"""Constants for the USGS Water Data adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Public domain (USGS)",
        "license_url": "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
        "citation": (
            "U.S. Geological Survey, National Water Information System via the USGS Water Data "
            "OGC API, https://api.waterdata.usgs.gov/ogcapi/v0/ (accessed on the date in _meta)."
        ),
        "description": "Latest continuous (instantaneous) values per USGS monitoring location: "
        "discharge, gage height, temperature, … by parameter code.",
        "description_url": "https://api.waterdata.usgs.gov/docs/ogcapi/",
    }
)

WATER_BASE_URL = "https://api.waterdata.usgs.gov/ogcapi/v0"
SOURCE = "usgs_water"
KEY_NAME = "USGS_WATERDATA_API_KEY"
SIGNUP_URL = "https://api.waterdata.usgs.gov/signup/"
TTL_S = 15 * 60
QUOTA_KEYLESS = (50, 3600)
QUOTA_KEYED = (1000, 3600)

# common NWIS parameter codes → a label
PARAMETERS: MappingProxyType[str, str] = MappingProxyType(
    {
        "00060": "discharge, ft^3/s",
        "00065": "gage height, ft",
        "00010": "water temperature, degC",
        "00300": "dissolved oxygen, mg/L",
        "00400": "pH",
        "00095": "specific conductance, uS/cm",
        "63680": "turbidity, FNU",
        "72019": "depth to water level, ft below land surface",
    }
)
