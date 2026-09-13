"""NASA EONET v3 — curated natural events (wildfires, storms, volcanoes, floods, ice, …).

Data source: ``https://eonet.gsfc.nasa.gov/api/v3/events``
Coverage: Global, 13 categories, open and recently closed events (curated; "not an official source")
Auth required: No
License: Public domain (NASA)

Feed tool: ``eonet_events`` → ``{data: [EventRecord, …], _meta}`` with ``_meta.ttl_s`` (30 min).
"""

from .tools import eonet_events

__all__ = ["eonet_events"]
