"""Daymet — daily surface weather on a 1 km grid, North America, 1980 → the last full year.

Data source: ``https://daymet.ornl.gov/single-pixel/api/data`` (ORNL DAAC)
Coverage: North America (incl. Hawaii, Puerto Rico), 1980 – last complete calendar year
Auth required: No
License: Open — "Data hosted by the ORNL DAAC is openly shared, without restriction"

Point accessor: ``daymet_at`` → ``{data: [record], _meta}`` — one record for the requested date.
"""

from .tools import daymet_at

__all__ = ["daymet_at"]
