"""EIA — power plants near a point, from the EIA API v2 operating-generator capacity data.

Data source: ``https://api.eia.gov/v2/electricity/operating-generator-capacity/data/``
Coverage: United States; generator-level monthly (EIA-860M), aggregated here to plants
Auth required: Yes — a free ``EIA_API_KEY`` (https://www.eia.gov/opendata/register.php), sent in
               the ``X-Api-Key`` header (never in the URL).
License: Public domain (US Government publication)

Point accessor: ``eia_plants_near`` → ``{data: [record, …], _meta}`` — plants within ``radius_km``
with total nameplate capacity (MW) and their fuel/technology mix.  The generator list for a state
(or the nation) is fetched once and cached 24 h.

Field names follow the EIA API v2 route documentation; they are exercised by the integration test
with a real key — flagged [unverified live] in the PR until that test has run.
"""

from .tools import eia_plants_near

__all__ = ["eia_plants_near"]
