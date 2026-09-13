"""Constants for the ARM adapter."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Free and open (ARM data use guidelines; a free ARM account is needed for data)",
        "license_url": "https://www.arm.gov/guidance/datause/generalguidelines",
        "citation": (
            "Atmospheric Radiation Measurement (ARM) user facility, U.S. Department of Energy, "
            "Office of Science. https://www.arm.gov/ — site coordinates from the ARM site pages."
        ),
        "description": "The nearest ARM fixed observatory (Southern Great Plains, North Slope of "
        "Alaska, Eastern North Atlantic) and its distance.",
        "description_url": "https://www.arm.gov/capabilities/observatories",
        "acknowledgements": "Data were obtained from the ARM user facility, a DOE Office of "
        "Science user facility managed by the Biological and Environmental Research program.",
    }
)

SOURCE = "arm"
TTL_S = 0.0  # a static table; nothing to cache

# Fixed observatories — central facility coordinates as published on the ARM site pages
SITES: tuple[dict[str, Any], ...] = (
    {
        "code": "SGP",
        "name": "Southern Great Plains, Central Facility (Lamont, Oklahoma)",
        "lat": 36.607,
        "lon": -97.488,
        "url": "https://www.arm.gov/capabilities/observatories/sgp",
        "since": 1992,
    },
    {
        "code": "NSA",
        "name": "North Slope of Alaska (Utqiaġvik)",
        "lat": 71.323,
        "lon": -156.615,
        "url": "https://www.arm.gov/capabilities/observatories/nsa",
        "since": 1997,
    },
    {
        "code": "ENA",
        "name": "Eastern North Atlantic (Graciosa Island, Azores)",
        "lat": 39.091,
        "lon": -28.026,
        "url": "https://www.arm.gov/capabilities/observatories/ena",
        "since": 2013,
    },
)
