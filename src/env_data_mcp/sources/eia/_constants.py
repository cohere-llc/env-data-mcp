"""Constants for the EIA adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Public domain (US Government publication)",
        "license_url": "https://www.eia.gov/about/copyrights_reuse.php",
        "citation": (
            "U.S. Energy Information Administration, Form EIA-860M operating generator capacity "
            "via the EIA API v2, https://api.eia.gov/v2/electricity/operating-generator-capacity/"
        ),
        "description": "Operating power plants (generator capacity aggregated to the plant) "
        "within a radius of a point.",
        "description_url": "https://www.eia.gov/opendata/documentation.php",
    }
)

EIA_BASE_URL = "https://api.eia.gov/v2"
ROUTE = "electricity/operating-generator-capacity/data/"
SOURCE = "eia"
KEY_NAME = "EIA_API_KEY"
SIGNUP_URL = "https://www.eia.gov/opendata/register.php"
TTL_S = 24 * 3600
PAGE = 5000
QUOTA_LIMIT = (
    5000  # EIA's published limit is generous; the governor keeps a paging bug from looping
)
QUOTA_WINDOW_S = 3600
