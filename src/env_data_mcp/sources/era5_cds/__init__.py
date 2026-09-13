"""ERA5 monthly means at a point, via the Copernicus Climate Data Store (CDS) API.

Data source: ``https://cds.climate.copernicus.eu/api/retrieve/v1/processes/
reanalysis-era5-single-levels-monthly-means/execution``
Coverage: Global, 0.25°, monthly, 1940 → present (≈ 5-day latency)
Auth required: Yes — a CDS account, its Personal Access Token as ``CDS_API_KEY`` (sent in the
               ``PRIVATE-TOKEN`` header, never in a URL) and a one-time acceptance of the dataset
               licence on the CDS website.
License: CC BY 4.0 (the ERA5 licence was replaced with CC-BY on 2 July 2025)

THE QUEUE.  A CDS request is a job: it is accepted, queued, run and only then downloadable —
seconds when the queue is empty, many minutes when it is not.  ``era5_monthly_at`` submits the
job, polls for up to ``max_wait_s`` and, if the job is not finished, answers ``success: False``
with ``_meta.job = {id, status}`` and ``error = "queued: …"``; call again with ``job_id=`` to
resume waiting on the same job (no second submission).  Results are cached 30 days.

Point accessor: ``era5_monthly_at`` → ``{data: [record, …], _meta}`` — one record per month.
"""

from .tools import era5_monthly_at

__all__ = ["era5_monthly_at"]
