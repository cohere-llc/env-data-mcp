"""SoilGrids data adapter.

Data source: SoilGrids map service (https://maps.isric.org/mapserv)
Coverage: Global 250-m resolution, present time
Auth required: No
License: CC BY 4.0

Future improvements:
 - Could optionally return GeoTIFF images
"""

from .tools import (
    soilgrids_available_variables,
    soilgrids_bbox_query,
    soilgrids_point_query,
)

__all__ = [
    "soilgrids_available_variables",
    "soilgrids_bbox_query",
    "soilgrids_point_query",
]
