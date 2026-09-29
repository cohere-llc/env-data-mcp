"""Constants and data classes for the NASA EMIT adapter."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

COLLECTION_SHORT_NAME: str = "EMITL2BMIN"
COLLECTION_CONCEPT_ID: str = "C2408034484-LPCLOUD"
VERSION: str = "001"
PAGE_SIZE: int = 200

CMR_GANULES_URL: str = "https://cmr.earthdata.nasa.gov/search/granules.json"

# Fetched once per granule: full-scene lat/lon grids + the mineral name lookup
# table. Hyrax's fileout-netcdf ("FONc") response flattens nested DAP4 groups
# into underscore-prefixed names (e.g. "/location/lat" -> "_location_lat"), so
# the request path and the name used to read the response differ.
QUERY_ARGS = "/location/lat,/location/lon,/mineral_metadata/name"
LON_PATHS = ["_location_lon", "/location/lon", "location/lon", "lon"]
LAT_PATHS = ["_location_lat", "/location/lat", "location/lat", "lat"]
MINERAL_NAME_PATHS = [
    "_mineral_metadata_name",
    "/mineral_metadata/name",
    "mineral_metadata/name",
    "mineral_name",
]

# The L2B MIN product reports the top-2 candidate mineral matches per pixel
# (no per-mineral abundance vector exists). These are root-level variables
# (not nested in a group), so the request name and response name are identical.
GROUP_1_MINERAL_ID_VAR = "group_1_mineral_id"
GROUP_1_BAND_DEPTH_VAR = "group_1_band_depth"
GROUP_2_MINERAL_ID_VAR = "group_2_mineral_id"
GROUP_2_BAND_DEPTH_VAR = "group_2_band_depth"
GROUP_VARS = (
    GROUP_1_MINERAL_ID_VAR,
    GROUP_1_BAND_DEPTH_VAR,
    GROUP_2_MINERAL_ID_VAR,
    GROUP_2_BAND_DEPTH_VAR,
)

# Sentinel used by the product for "no mineral match at this pixel".
FILL_MINERAL_ID = -9999

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "NASA data policy — free and open (attribution requested)",
        "license_url": (
            "https://www.earthdata.nasa.gov/engage/open-data-services-software/"
            "data-rights-related-issues"
        ),
        "citation": (
            "Green, R. (2023). <i>EMIT L2B Estimated Mineral Identification and Band Depth and "
            "Uncertainty 60 m V001</i> [Dataset]. NASA Land Processes Distributed Active Archive "
            "Center. https://doi.org/10.5067/EMIT/EMITL2BMIN.001"
        ),
    }
)

VARIABLE_INFO: MappingProxyType[str, dict[str, Any]] = MappingProxyType(
    {
        "group_1_mineral_name": {
            "description": (
                "Name of the best-matching mineral spectral library entry at this pixel "
                "(EMIT L2B MIN 'Group 1')."
            ),
            "units": "",
        },
        "group_1_band_depth": {
            "description": "Continuum-removed absorption band depth supporting the Group 1 match.",
            "units": "unitless",
        },
        "group_2_mineral_name": {
            "description": (
                "Name of the second-best-matching mineral spectral library entry at this pixel "
                "(EMIT L2B MIN 'Group 2')."
            ),
            "units": "",
        },
        "group_2_band_depth": {
            "description": "Continuum-removed absorption band depth supporting the Group 2 match.",
            "units": "unitless",
        },
    }
)


@dataclass(frozen=True)
class Granule:
    id: str
    date: str
    nc4_link: str
