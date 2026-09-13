"""USGS Water Data — the OGC API (instantaneous / latest continuous values by site or bbox).

Data source: ``https://api.waterdata.usgs.gov/ogcapi/v0/collections/latest-continuous/items``
Coverage: United States; the latest value per monitoring location and parameter
Auth required: No — 50 requests/hour keyless; with a free ``USGS_WATERDATA_API_KEY``
               (https://api.waterdata.usgs.gov/signup/) 1,000/hour.  The key travels in the
               ``X-Api-Key`` header, never in the URL.
License: Public domain (USGS)

Feed tool: ``usgs_water_latest`` → ``{data: [EventRecord, …], _meta}`` with ``_meta.ttl_s``
(15 min) and ``_meta.quota`` (the tier in force).
"""

from .tools import usgs_water_latest

__all__ = ["usgs_water_latest"]
