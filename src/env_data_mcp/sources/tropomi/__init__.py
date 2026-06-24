"""Sentinel 5-TROPOMI data adapter.

Data source: ``https://meeo-s5p.s3.amazonaws.com/``
Coverage: Global, July 2018-present
Auth required: No
License: https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice
"""

from .tools import tropomi_available_variables

__all__ = [
    "tropomi_available_variables",
]
