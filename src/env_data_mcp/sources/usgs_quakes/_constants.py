"""Constants for the USGS earthquakes adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Public domain (USGS)",
        "license_url": "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
        "citation": (
            "U.S. Geological Survey, Earthquake Hazards Program, ANSS Comprehensive Earthquake "
            "Catalog (ComCat), https://earthquake.usgs.gov/fdsnws/event/1/"
        ),
        "description": (
            "Earthquakes from the ANSS Comprehensive Catalog via the FDSN event web service."
        ),
        "description_url": "https://earthquake.usgs.gov/fdsnws/event/1/",
    }
)

FDSN_BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1"
SOURCE = "usgs_quakes"
TTL_S = 5 * 60
