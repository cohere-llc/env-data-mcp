"""GBIF data adapter.

Data source: ``https://api.gbif.org/v1/
Coverage: Global, 1800s-present
Auth required: No
License: Mixed - CC0 1.0, CC BY 4.0, CC BY-NC 4.0 per record

Future improvements:
- Could provide access to:
    * tiled web maps of occurrence data (https://techdocs.gbif.org/en/openapi/v2/maps)
    * registered datasets (https://techdocs.gbif.org/en/openapi/v1/registry-principal-methods)
    * literature (https://techdocs.gbif.org/en/openapi/v1/literature)
"""

from .tools import (
    gbif_occurrence_available_variables,
    gbif_occurrence_bbox_query,
    gbif_occurrence_query,
)

__all__ = [
    "gbif_occurrence_available_variables",
    "gbif_occurrence_bbox_query",
    "gbif_occurrence_query",
]
