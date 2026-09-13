"""Constants for the ERA5 (CDS) adapter."""

from __future__ import annotations

from types import MappingProxyType

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "CC BY 4.0 (ECMWF / Copernicus Climate Change Service; CC-BY since 2025-07-02)",
        "license_url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels-monthly-means",
        "citation": (
            "Hersbach, H. et al. (2023): ERA5 monthly averaged data on single levels from 1940 to "
            "present. Copernicus Climate Change Service (C3S) Climate Data Store (CDS). "
            "https://doi.org/10.24381/cds.f17050d7 — generated using Copernicus Climate Change "
            "Service information."
        ),
        "description": "ERA5 monthly means (2 m temperature, total precipitation, …) at the "
        "nearest 0.25° grid point, 1940 → present.",
        "description_url": "https://cds.climate.copernicus.eu/how-to-api",
        "acknowledgements": "Contains modified Copernicus Climate Change Service information.",
    }
)

CDS_BASE_URL = "https://cds.climate.copernicus.eu/api/retrieve/v1"
DATASET = "reanalysis-era5-single-levels-monthly-means"
SOURCE = "era5_cds"
KEY_NAME = "CDS_API_KEY"
SIGNUP_URL = "https://cds.climate.copernicus.eu/how-to-api"
TTL_S = 30 * 24 * 3600
POLL_S = 3.0

# CDS variable name → (netCDF short name, units)
VARIABLES: MappingProxyType[str, tuple[str, str]] = MappingProxyType(
    {
        "2m_temperature": ("t2m", "K"),
        "total_precipitation": ("tp", "m"),
        "10m_u_component_of_wind": ("u10", "m s-1"),
        "10m_v_component_of_wind": ("v10", "m s-1"),
        "surface_pressure": ("sp", "Pa"),
        "2m_dewpoint_temperature": ("d2m", "K"),
        "volumetric_soil_water_layer_1": ("swvl1", "m3 m-3"),
        "snow_depth": ("sd", "m of water equivalent"),
    }
)
FIRST_YEAR = 1940
