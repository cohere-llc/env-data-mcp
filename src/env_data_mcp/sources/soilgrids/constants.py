"""Constants, enums, default variable lists, and URLs for the SoilGrids adapter."""

from __future__ import annotations

DEFAULT_VARIABLES = [
    "soc_0-5cm_mean",  # Soil organic carbon
    "nitrogen_0-5cm_mean",  # Total nitrogen
    "phh2o_0-5cm_mean",  # pH
    "cec_0-5cm_mean",  # Cation exchange capacity
    "clay_0-5cm_mean",  # Clay content
    "sand_0-5cm_mean",  # Sand fraction
    "bdod_0-5cm_mean",  # Bulk density
    "wv1500_0-5cm_mean",  # Permanent wilting point water content
    "wv0010_0-5cm_mean",  # Field capacity water content
    "cfvo_0-5cm_mean",  # Coarse fragment volume
]

LICENSE_INFO: dict[str, str] = {
    "citation": (
        "Common soil chemical and physical properties: "
        "Poggio, L., de Sousa, L. M., Batjes, N. H., Heuvelink, G. B. M., Kempen, B., "
        "Ribeiro, E., and Rossiter, D.: SoilGrids 2.0: producing soil information for "
        "the globe with quantified spatial uncertainty, SOIL, 7, 217–240, 2021. DOI: "
        "https://doi.org/10.5194/soil-7-217-2021 ;"
        "Soil water content at different pressure heads: "
        "Turek, M.E.;Poggio, L., Batjes, N. H., Armindo, R. A.;de Jong van Lier, Q.;de "
        "Sousa, L.M.;Heuvelink, G.;B. M.:Global mapping of volumetric water retention "
        "at 100, 330 and 15 000 cm suction using the WoSIS database, International Soil "
        "and Water Conservation Research, 11-2, 225-239, 2023. DOI: "
        "https://doi.org/10.1016/j.iswcr.2022.08.001"
    ),
    "description": (
        "Soilgrids is a system for digital soil mapping based on a global compilation "
        "of soil profile data (WoSIS) and environmental layers. Read about the "
        "SoilGrids and WoSIS projects on isric.org"
    ),
    "description_url": "https://isric.org/",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
}

_WEB_MAP_SERVICE_URL = "https://maps.isric.org/mapserv"

_LAYERS_INFO_URL = "https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html"

_QUANTILES: dict[str, str] = {
    "Q0.05": "5% quantile",
    "Q0.5": "median",
    "Q0.95": "95% quantile",
    "mean": "mean",
    "uncertainty": "uncertainty",
}

# Coordinate systems

_REQUEST_CRS: str = "EPSG:54012"
_TRANSFORM_CRS: str = "ESRI:54012"
_RESPONSE_CRS: str = "EPSG:4326"

# Horizontal Resolution of SoilGrids data
_CELL_SIZE_METERS = 250.0
