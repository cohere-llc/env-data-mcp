"""Constants, enums, classes, and default variable lists for the OpenAQ adapeter."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "CC BY 4.0",
        "license_url": "https://openaq.org/about/",
        "citation": (
            "OpenAQ. Air quality data accessed via OpenAQ API v3 "
            "(https://api.openaq.org/v3/). "
            "https://doi.org/10.7910/DVN/GKA0UN"
        ),
    }
)

OPENAQ_BASE_URL = "https://api.openaq.org/v3"

DEFAULT_VARIABLES: frozenset[str] = frozenset(["pm25", "pm10", "o3", "no2", "co"])


@dataclass(frozen=True)
class Parameter:
    id: int
    name: str
    description: str
    units: str


@dataclass(frozen=True)
class Sensor:
    id: int
    parameter_id: int


@dataclass(frozen=True)
class Location:
    id: int
    lat: float
    lon: float
    sensors: list[Sensor]
    name: str | None = None
