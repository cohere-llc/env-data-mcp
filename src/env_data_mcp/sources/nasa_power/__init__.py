"""NASA POWER MERRA-2 and CERES SYN1deg data adapter.

Data source: Unsigned HTTPS Zarr at ``https://nasa-power.s3.amazonaws.com/``
Coverage: Global, 1980-present
Auth required: No

Future improvements:
- Could add datasets beyond MERRA-2 and SYN1deg:
| Prefix | Dataset | What it is |
|---|---|---|
|merra2|MERRA-2|NASA's flagship reanalysis, surface and upper-air variables, 1980-present.|
|flashflux|CERES FLASHFlux|Near-real-time solar radiation (~5-7 day latency)|
|geosit|GEOS-IT|Near-real-time meteorology; appended to MERRA-2's end (~2 day latency)|
|gwm|Global Water Model|Groundwater/hydrology|
|imerg|IMERG|High-res precipitation (0.1 deg, ~3.5 month latency for final run)|
|srb|SRB Release 4-IP|Legacy surface radiation budget (1984-2000 only)|
|syn1deg|CERES SYN1deg|Solar radiation at 1° grid (2001-present)|

"""

from .tools import (
    nasa_power_merra2_available_variables,
    nasa_power_merra2_bbox_query,
    nasa_power_merra2_point_query,
    nasa_power_syn1deg_available_variables,
    nasa_power_syn1deg_bbox_query,
    nasa_power_syn1deg_point_query,
)

__all__ = [
    "nasa_power_merra2_available_variables",
    "nasa_power_merra2_bbox_query",
    "nasa_power_merra2_point_query",
    "nasa_power_syn1deg_available_variables",
    "nasa_power_syn1deg_bbox_query",
    "nasa_power_syn1deg_point_query",
]
