"""Constants, enums, classes, and default variable lists for the ESS-DIVE adapter."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "varies by dataset",
        "citation": "varies by dataset",
    }
)

ESSDIVE_BASE_URL = "https://api.ess-dive.lbl.gov/"


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


@dataclass(frozen=True)
class BBox:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


@dataclass(frozen=True)
class DataFile:
    url: str
    encoding: str
    name: str
    size_kb: float


@dataclass(frozen=True)
class Package:
    id: str
    url: str
    view_url: str
    citation: str
    license: str
    funder: str
    geos: list[BBox | Point]
    variables: list[str]
    techniques: list[str]
    files: list[DataFile]
