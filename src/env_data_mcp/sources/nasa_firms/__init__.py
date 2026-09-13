"""NASA FIRMS — active fire detections (VIIRS / MODIS), near-real-time.

Data source: ``https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{product}/{area}/{days}``
Coverage: Global, ≤ 3 h latency (NRT), ultra-real-time for the US/Canada
Auth required: Yes — a free MAP_KEY from https://firms.modaps.eosdis.nasa.gov/api/map_key/
               Set ``NASA_FIRMS_MAP_KEY``.  Quota: 5,000 transactions per 10 minutes per key.
License: NASA data policy — free and open; acknowledge NASA FIRMS.

The key is part of the URL path by FIRMS design; that URL is never logged and never returned.

Feed tool: ``nasa_firms_fires`` → ``{data: [EventRecord, …], _meta}`` with ``_meta.ttl_s`` (30 min)
and ``_meta.quota``.
"""

from .tools import nasa_firms_fires

__all__ = ["nasa_firms_fires"]
