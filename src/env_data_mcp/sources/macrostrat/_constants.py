"""Constants for the Macrostrat adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "CC BY 4.0",
        "license_url": "https://macrostrat.org/api/v2/meta",
        "citation": (
            "Peters, S.E., J.M. Husson, and J. Czaplewski. 2018. Macrostrat: a platform for "
            "geological data integration and deep-time Earth crust research. Geochemistry, "
            "Geophysics, Geosystems 19(4): 1393–1409. https://doi.org/10.1029/2018GC007467 — "
            "https://macrostrat.org"
        ),
        "description": "The geologic map unit at a point: stratigraphic name, lithology, age "
        "(Ma) and interval, from the finest-scale map available.",
        "description_url": "https://macrostrat.org/api/v2/geologic_units/map",
    }
)

MACROSTRAT_BASE_URL = "https://macrostrat.org/api/v2"
SOURCE = "macrostrat"
TTL_S = 7 * 24 * 3600
