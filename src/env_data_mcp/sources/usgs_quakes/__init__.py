"""USGS earthquakes — the FDSN event service (ComCat), GeoJSON.

Data source: ``https://earthquake.usgs.gov/fdsnws/event/1/query``
Coverage: Global, minutes after origin; magnitudes, depth, ShakeMap/PAGER alert level when issued
Auth required: No
License: Public domain (USGS)

Feed tool: ``usgs_quakes_events`` → ``{data: [EventRecord, …], _meta}``; ``_meta.ttl_s`` = 5 min.
"""

from .tools import usgs_quakes_events

__all__ = ["usgs_quakes_events"]
