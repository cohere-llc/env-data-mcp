"""Constants for the Open-Meteo adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": (
            "CC BY 4.0 — free API for NON-COMMERCIAL use only (commercial use needs a paid plan)"
        ),
        "license_url": "https://open-meteo.com/en/terms",
        "citation": (
            "Zippenfenig, P. (2023). Open-Meteo.com Weather API. Zenodo. "
            "https://doi.org/10.5281/zenodo.7970649 — weather data by Open-Meteo.com."
        ),
        "description": "Current conditions + 7-day daily forecast at a point (model blend).",
        "description_url": "https://open-meteo.com/en/docs",
        "acknowledgements": "Weather data by Open-Meteo.com",
    }
)

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1"
SOURCE = "open_meteo"
TTL_S = 15 * 60
NC_ENV = "ENV_DATA_ALLOW_NC"

CURRENT_VARS = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
    "weather_code",
)
DAILY_VARS = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum", "weather_code")
