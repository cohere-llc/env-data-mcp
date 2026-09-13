"""Constants for the NASA EONET adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Public domain (NASA)",
        "license_url": "https://eonet.gsfc.nasa.gov/docs/v3",
        "citation": (
            "NASA Earth Observatory Natural Event Tracker (EONET) v3, "
            "https://eonet.gsfc.nasa.gov/api/v3/events. EONET is a curated feed and "
            '"not an official source" of event information.'
        ),
        "description": (
            "Curated natural events (13 categories) with source links and GIBS layer links."
        ),
        "description_url": "https://eonet.gsfc.nasa.gov/what-is-eonet",
    }
)

EONET_BASE_URL = "https://eonet.gsfc.nasa.gov/api/v3"
SOURCE = "eonet"
TTL_S = 30 * 60  # EONET updates a few times a day; 30 min is the brief's cache TTL

# EONET category id → EventRecord.kind
KIND_BY_CATEGORY: MappingProxyType[str, str] = MappingProxyType(
    {
        "wildfires": "fire",
        "severeStorms": "storm",
        "volcanoes": "volcano",
        "floods": "flood",
        "seaLakeIce": "ice",
        "drought": "drought",
        "dustHaze": "dust",
        "landslides": "landslide",
        "earthquakes": "quake",
        "snow": "storm",
        "tempExtremes": "other",
        "manmade": "other",
        "waterColor": "water",
    }
)
