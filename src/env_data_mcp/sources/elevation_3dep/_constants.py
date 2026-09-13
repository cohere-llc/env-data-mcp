"""Constants for the USGS 3DEP elevation adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Public domain (USGS)",
        "license_url": "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
        "citation": (
            "U.S. Geological Survey, 3D Elevation Program (3DEP), Elevation Point Query Service, "
            "https://epqs.nationalmap.gov/"
        ),
        "description": "Ground elevation (metres) at a point from the best available 3DEP DEM.",
        "description_url": "https://www.usgs.gov/3d-elevation-program",
    }
)

EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
SOURCE = "elevation_3dep"
TTL_S = 30 * 24 * 3600
