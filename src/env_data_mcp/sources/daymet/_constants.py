"""Constants for the Daymet single-pixel adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Open (ORNL DAAC / NASA Earth Science data policy — no restriction)",
        "license_url": "https://daac.ornl.gov/about/",
        "citation": (
            "Thornton, M.M., R. Shrestha, Y. Wei, P.E. Thornton, S-C. Kao, and B.E. Wilson. 2022. "
            "Daymet: Daily Surface Weather Data on a 1-km Grid for North America, Version 4 R1. "
            "ORNL DAAC, Oak Ridge, Tennessee, USA. https://doi.org/10.3334/ORNLDAAC/2129"
        ),
        "description": "Daily tmax, tmin, precipitation, radiation, vapour pressure, snow water "
        "equivalent and day length at a 1 km pixel.",
        "description_url": "https://daymet.ornl.gov/single-pixel/",
    }
)

DAYMET_BASE_URL = "https://daymet.ornl.gov/single-pixel/api/data"
SOURCE = "daymet"
TTL_S = 24 * 3600
VARIABLES: MappingProxyType[str, tuple[str, str]] = MappingProxyType(
    {
        "tmax": ("tmax (deg c)", "degC"),
        "tmin": ("tmin (deg c)", "degC"),
        "prcp": ("prcp (mm/day)", "mm/day"),
        "srad": ("srad (W/m^2)", "W/m^2"),
        "vp": ("vp (Pa)", "Pa"),
        "swe": ("swe (kg/m^2)", "kg/m^2"),
        "dayl": ("dayl (s)", "s"),
    }
)
DEFAULT_VARIABLES = ("tmax", "tmin", "prcp")
FIRST_YEAR = 1980
