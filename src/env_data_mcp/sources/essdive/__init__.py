"""ESS-DIVE adapter.

Data source: ``https://api.ess-dive.lbl.gov/``
Coverage: Global
Auth required: No (public datasets) / Yes (private datasets)
               Free API key from ``https://data.ess-dive.lbl.gov``
               Set ``ESSDIVE_TOKEN`` environment variable.
License: Varies by dataset
"""

from .tools import (
    essdive_bbox_query,
    essdive_point_query,
)

__all__ = [
    "essdive_bbox_query",
    "essdive_point_query",
]
