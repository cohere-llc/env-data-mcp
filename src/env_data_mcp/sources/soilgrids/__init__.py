"""SoilGrids data adapter.

Data source:
Coverage:
Auth requried: No
License:

Future improvements:
"""

from .tools import (
    soilgrids_available_variables,
    soilgrids_bbox_query,
    soilgrids_query,
)

__all__ = [
    "soilgrids_available_variables",
    "soilgrids_bbox_query",
    "soilgrids_query",
]
