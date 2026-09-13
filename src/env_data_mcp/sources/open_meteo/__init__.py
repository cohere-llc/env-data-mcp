"""Open-Meteo — current conditions and a 7-day forecast at a point.

Data source: ``https://api.open-meteo.com/v1/forecast``
Coverage: Global; ~1–11 km model blend; hourly updates
Auth required: No key — but the free API is licensed for **non-commercial use only** (CC BY 4.0
               data; commercial use needs a paid plan).  This adapter is therefore GATED: it answers
               ``gated: non-commercial terms`` (empty data, ``success: False``) unless the operator
               sets ``ENV_DATA_ALLOW_NC=1`` to attest non-commercial use of this deployment.
License: CC BY 4.0 (non-commercial free tier)

Feed tool: ``open_meteo_current`` → ``{data: [EventRecord], _meta}`` (one record: the current
conditions, with the 7-day daily forecast in ``properties``); ``_meta.ttl_s`` 15 min.
"""

from .tools import open_meteo_current

__all__ = ["open_meteo_current"]
