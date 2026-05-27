"""Constants, enums, default variable lists, and Zarr store URLs for the NASA POWER adapter."""

from __future__ import annotations

from enum import Enum

DEFAULT_MERRA2_VARIABLES = [
    "T2M",  # 2-meter air temperature
    "T2M_MAX",  # Daily maximum 2-meter air temperature
    "T2M_MIN",  # Daily minimum 2-meter air temperature
    "PRECTOTCORR",  # Total gauge-corrected precipitation
    "GWETROOT",  # Root-zone soil moisture
    "TSOIL1",  # Near-surface soil temperature
    "RH2M",  # 2-meter relative humidity
    "WS10M",  # 10-meter wind speed
]

DEFAULT_SYN1DEG_VARIABLES = [
    "ALLSKY_SFC_PAR_TOT",  # All-sky surface photosynthetically active radiation
    "ALLSKY_SFC_PAR_DIFF",  # All-sky surface photosynthetically active radiation diffuse fraction
    "ALLSKY_SFC_SW_DWN",  # All-sky surface downward shortwave radiation
    "ALLSKY_SFC_LW_DWN",  # All-sky surface downward longwave radiation
    "CLRSKY_SFC_PAR_TOT",  # Clear-sky surface photosynthetically active radiation
]


class DatasetType(Enum):
    MERRA2 = "merra2"
    SYN1DEG = "syn1deg"


class TemporalResolution(Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"
    ANNUAL = "annual"
    CLIMATOLOGY = "climatology"


# ---------------------------------------------------------------------------
# Licence and metadata
# ---------------------------------------------------------------------------

SOURCE_INFO: dict[str, str | list[str]] = {
    "license": (
        "There are no restrictions on the use, access, and/or download of data "
        "from the NASA POWER Project. We request that you cite the NASA POWER "
        "Project when using the data provided from NASA POWER Project. Public "
        "domain (NASA/US Government). Citation requested."
    ),
    "citation": (
        "NASA Prediction of Worldwide Energy Resources (POWER) was accessed on "
        "DATE from https://registry.opendata.aws/nasa-power. "
    ),
    "citation_urls": [
        "https://nasa-power.s3.amazonaws.com/CITATION.cff",
        "https://power.larc.nasa.gov/docs/methodology/citations/",
    ],
    "acknowledgments": (
        "The Prediction Of Worldwide Energy Resources (POWER) Project is funded "
        "through the National Aeronautics and Space Administration (NASA) Applied "
        "Sciences Program within the Earth Science Division of the Science Mission "
        "Directorate. The POWER team could not have completed this task without "
        "both technical and scientific inputs from the following Earth Science "
        "Division teams: The Surface Radiation Budget (SRB) and the Clouds and the "
        "Earth's Radiant Energy System (CERES) projects at NASA LaRC and the Global "
        "Modeling and Assimilation Office at the NASA Goddard Space Flight Center. "
        "The data obtained through the POWER web services was made possible with "
        "collaboration from the NASA Langley Research Center (LaRC) Atmospheric "
        "Science Data Center (ASDC)."
    ),
    "description_url": "https://registry.opendata.aws/nasa-power/",
}

MERRA2_INFO: dict[str, str] = {
    "description": (
        "The Modern-Era Retrospective analysis for Research and Applications, "
        "Version 2 (MERRA-2) provides data beginning in 1980. It was introduced "
        "to replace the original MERRA dataset because of the advances made in "
        "the assimilation system that enable assimilation of modern hyperspectral "
        "radiance and microwave observations, along with GPS-Radio Occultation "
        "datasets. It also uses NASA's ozone profile observations that began in "
        "late 2004. Additional advances in both the GEOS model and the GSI "
        "assimilation system are included in MERRA-2. Spatial resolution remains "
        "about the same (about 50 km in the latitudinal direction) as in MERRA. "
        "Along with the enhancements in the meteorological assimilation, MERRA-2 "
        "takes some significant steps towards GMAO's target of an Earth System "
        "reanalysis. MERRA-2 is the first long-term global reanalysis to assimilate "
        "space-based observations of aerosols and represent their interactions "
        "with other physical processes in the climate system. MERRA-2 includes a "
        "representation of ice sheets over (say) Greenland and Antarctica."
    ),
}

SYN1DEG_INFO: dict[str, str] = {
    "description": (
        "The CERES SYN1deg product provides global gridded estimates of surface "
        "radiation budget components at 1° resolution, derived from the CERES "
        "instrument's measurements of reflected solar and emitted thermal radiation. "
        "It includes variables such as all-sky and clear-sky downward shortwave "
        "and longwave radiation, which are critical for understanding Earth's energy "
        "balance and climate. The dataset covers the period from 2001 to the present, "
        "with updates typically released within a few months of data acquisition."
    ),
}

# ---------------------------------------------------------------------------
# Zarr store URLs
# ---------------------------------------------------------------------------

# Use virtual-hosted HTTPS URLs rather than s3:// so that fsspec routes reads
# through its HTTPFileSystem / unsigned HTTPS access path instead of through
# aiobotocore. This means boto credential resolution is never invoked, which
# prevents "Access Denied" errors on environments (e.g. Lakehouse/EKS) where
# IRSA injects AWS credentials that the NASA POWER public-bucket policy rejects.
_ZARR_BASE = "https://nasa-power.s3.amazonaws.com"
_M2 = f"{_ZARR_BASE}/merra2/spatial"
_S1 = f"{_ZARR_BASE}/syn1deg/spatial"
_ZARR_URLS = {
    DatasetType.MERRA2: {
        TemporalResolution.HOURLY: f"{_M2}/power_merra2_hourly_spatial_utc.zarr",
        TemporalResolution.DAILY: f"{_M2}/power_merra2_daily_spatial_utc.zarr",
        TemporalResolution.MONTHLY: f"{_M2}/power_merra2_monthly_spatial_utc.zarr",
        TemporalResolution.ANNUAL: f"{_M2}/power_merra2_annual_spatial_utc.zarr",
        TemporalResolution.CLIMATOLOGY: f"{_M2}/power_merra2_climatology_spatial_utc.zarr",
    },
    DatasetType.SYN1DEG: {
        TemporalResolution.HOURLY: f"{_S1}/power_syn1deg_hourly_spatial_utc.zarr",
        TemporalResolution.DAILY: f"{_S1}/power_syn1deg_daily_spatial_utc.zarr",
        TemporalResolution.MONTHLY: f"{_S1}/power_syn1deg_monthly_spatial_utc.zarr",
        TemporalResolution.ANNUAL: f"{_S1}/power_syn1deg_annual_spatial_utc.zarr",
        TemporalResolution.CLIMATOLOGY: f"{_S1}/power_syn1deg_climatology_spatial_utc.zarr",
    },
}
