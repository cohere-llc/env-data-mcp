"""USGS 3DEP elevation at a point (the Elevation Point Query Service).

Data source: ``https://epqs.nationalmap.gov/v1/json``
Coverage: United States (3DEP: 1/3 arc-second nationally, 1 m where lidar exists)
Auth required: No
License: Public domain (USGS)

Point accessor: ``elevation_3dep`` → ``{data: [record], _meta}`` — ``elevation_m`` at the point.
The service can take 10–15 s; the client waits up to 60 s.
"""

from .tools import elevation_3dep

__all__ = ["elevation_3dep"]
