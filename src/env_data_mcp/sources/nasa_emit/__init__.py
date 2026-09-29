"""NASA EMIT - Surface Mineral Dust, 2022 to present.

Data source: ``https://cmr.earthdata.nasa.gov``
Coverage: Global, 2022 to present.
Auth required: Yes - a free EARTHDATA token is required. See ``https://urs.earthdata.nasa.gov/documentation/for_users/user_token``
License: NASA data policy - free and open. ``https://www.earthdata.nasa.gov/engage/open-data-services-software/``
Citation: Green, R. (2023). <i>EMIT L2B Estimated Mineral Identification and Band Depth and
          Uncertainty 60 m V001</i> [Dataset]. NASA Land Processes Distributed Active Archive
          Center. https://doi.org/10.5067/EMIT/EMITL2BMIN.001
"""

from .tools import nasa_emit_bbox_query, nasa_emit_point_query

__all__ = [
    "nasa_emit_bbox_query",
    "nasa_emit_point_query",
]
