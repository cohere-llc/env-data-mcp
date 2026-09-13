"""ARM — the DOE Atmospheric Radiation Measurement observatories nearest a point.

Data source: the ARM fixed-site table in ``_constants.py`` (coordinates cited per site from
arm.gov); ARM Live data itself needs a free account and a token
(``https://adc.arm.gov/armlive/``).
Coverage: The three fixed observatories (SGP, NSA, ENA); mobile facilities are not listed.
Auth required: No for this tool.  NOTE — ARM Live's query API takes ``user:token`` in the URL
query string, which this server never does (no credential in a URL); a data tool therefore waits
for a header- or body-based auth path and is surfaced in the PR, not built.
License: "ARM data are available to all participants on a free and open basis"

Point accessor: ``arm_nearest`` → ``{data: [record], _meta}`` — the nearest observatory with its
distance.
"""

from .tools import arm_nearest

__all__ = ["arm_nearest"]
