"""NASA POWER MERRA-2 and CERES SYN1deg data adapter.

Data source: Unsigned HTTPS Zarr at ``https://nasa-power.s3.amazonaws.com/``
Coverage: Global, 1980–present
Auth required: No

Future improvements:
- Could add datasets beyond MERRA-2 and SYN1deg:
| Prefix | Dataset | What it is |
|---|---|---|
|merra2|MERRA-2|NASA's flagship reanalysis, surface and upper-air variables, 1980–present.|
|flashflux|CERES FLASHFlux|Near-real-time solar radiation (~5–7 day latency)|
|geosit|GEOS-IT|Near-real-time meteorology; appended to MERRA-2's end (~2 day latency)|
|gwm|Global Water Model|Groundwater/hydrology|
|imerg|IMERG|High-res precipitation (0.1°, ~3.5 month latency for final run)|
|srb|SRB Release 4-IP|Legacy surface radiation budget (1984–2000 only)|
|syn1deg|CERES SYN1deg|Solar radiation at 1° grid (2001–present)|

"""

from ._client import (
    ZarrStoreCache,
    _clear_store_cache,
    _get_coordinates,
    _get_variable_info,
    _open_store,
)
from ._query import (
    _CLIM_EPOCH,
    _clim_date_label,
    _clim_time_mask,
    _estimate_query_runtime_s,
    _query_bbox,
    _query_point,
)
from .constants import (
    DEFAULT_MERRA2_VARIABLES,
    DEFAULT_SYN1DEG_VARIABLES,
    MERRA2_INFO,
    SOURCE_INFO,
    SYN1DEG_INFO,
    DatasetType,
    TemporalResolution,
)
from .tools import (
    nasa_power_merra2_available_variables,
    nasa_power_merra2_bbox_query,
    nasa_power_merra2_query,
    nasa_power_syn1deg_available_variables,
    nasa_power_syn1deg_bbox_query,
    nasa_power_syn1deg_query,
)

__all__ = [
    "DatasetType",
    "DEFAULT_MERRA2_VARIABLES",
    "DEFAULT_SYN1DEG_VARIABLES",
    "MERRA2_INFO",
    "SOURCE_INFO",
    "SYN1DEG_INFO",
    "TemporalResolution",
    "ZarrStoreCache",
    "_CLIM_EPOCH",
    "_clear_store_cache",
    "_clim_date_label",
    "_clim_time_mask",
    "_estimate_query_runtime_s",
    "_get_coordinates",
    "_get_variable_info",
    "_open_store",
    "_query_bbox",
    "_query_point",
    "nasa_power_merra2_available_variables",
    "nasa_power_merra2_bbox_query",
    "nasa_power_merra2_query",
    "nasa_power_syn1deg_available_variables",
    "nasa_power_syn1deg_bbox_query",
    "nasa_power_syn1deg_query",
]
