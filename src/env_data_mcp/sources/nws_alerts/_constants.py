"""Constants for the NWS alerts adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Public domain (NOAA / US Government work)",
        "license_url": "https://www.weather.gov/disclaimer",
        "citation": (
            "NOAA National Weather Service, active alerts via api.weather.gov "
            "(https://api.weather.gov/alerts/active)."
        ),
        "description": "Active NWS watches, warnings, advisories and statements (CAP) at a point "
        "or for a state/zone.",
        "description_url": "https://www.weather.gov/documentation/services-web-api",
    }
)

NWS_BASE_URL = "https://api.weather.gov"
USER_AGENT = "env-data-mcp (https://github.com/kbaseincubator/env-data-mcp)"
SOURCE = "nws_alerts"
TTL_S = 10 * 60
