"""Macrostrat — the mapped geologic unit (lithology, age) under a point.

Data source: ``https://macrostrat.org/api/v2/geologic_units/map``
Coverage: Global (best-available geologic map at each scale)
Auth required: No
License: CC BY 4.0 (the API answers ``license: "CC-BY 4.0"`` on every call)

Point accessor: ``macrostrat_at`` → ``{data: [record], _meta}`` — the finest-scale unit at the
point, with every unit returned in ``units``.
"""

from .tools import macrostrat_at

__all__ = ["macrostrat_at"]
