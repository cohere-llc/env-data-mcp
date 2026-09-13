"""NWS alerts — active watches, warnings and advisories (CAP) from api.weather.gov.

Data source: ``https://api.weather.gov/alerts/active``
Coverage: United States and territories; live
Auth required: No (a descriptive ``User-Agent`` is required by the NWS API policy)
License: Public domain (NOAA / US Government work)

Feed tool: ``nws_alerts_at`` → ``{data: [EventRecord, …], _meta}`` with ``_meta.ttl_s`` (10 min).
"""

from .tools import nws_alerts_at

__all__ = ["nws_alerts_at"]
