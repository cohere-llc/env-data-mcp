"""Constants for the NASA FIRMS adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "NASA data policy — free and open (attribution requested)",
        "license_url": "https://www.earthdata.nasa.gov/data/tools/firms/faq",
        "citation": (
            "NASA Fire Information for Resource Management System (FIRMS), "
            "https://firms.modaps.eosdis.nasa.gov/. We acknowledge the use of data and/or "
            "imagery from NASA's FIRMS, part of NASA's Earth Science Data and Information System."
        ),
        "description": "Active fire / thermal anomaly detections from VIIRS (SNPP, NOAA-20/21) "
        "and MODIS, near-real-time.",
        "description_url": "https://firms.modaps.eosdis.nasa.gov/api/area/",
        "acknowledgements": "We acknowledge the use of data from NASA's FIRMS.",
    }
)

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SOURCE = "nasa_firms"
KEY_NAME = "NASA_FIRMS_MAP_KEY"
SIGNUP_URL = "https://firms.modaps.eosdis.nasa.gov/api/map_key/"
TTL_S = 30 * 60
QUOTA_LIMIT = 5000
QUOTA_WINDOW_S = 10 * 60

PRODUCTS: tuple[str, ...] = (
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
    "LANDSAT_NRT",
)
DEFAULT_PRODUCT = "VIIRS_SNPP_NRT"
