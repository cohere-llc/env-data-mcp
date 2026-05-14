"""GBIF occurrence data adapter — anonymous S3 Parquet reader.

Data source: ``s3://gbif-open-data-us-east-1/occurrence/``
Coverage: Global, 1800s–present (monthly Parquet snapshots)
Auth required: No (anonymous S3 access)
License: Mixed — CC0 1.0, CC BY 4.0, CC BY-NC 4.0 per record
"""

from __future__ import annotations

import time
from typing import Any

import dask.dataframe as dd  # noqa: F401 – kept for backward compatibility; no longer used in _fetch_gbif
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as pads
import pyarrow.fs as pafs
import s3fs

from env_data_mcp.helpers import build_meta, clamp_bbox
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# License and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "Mixed: CC0 1.0, CC BY 4.0, CC BY-NC 4.0 (per occurrence record)",
    "license_url": "https://www.gbif.org/terms",
    "citation": (
        "GBIF.org occurrence snapshot. Accessed via AWS Open Data Registry: "
        "s3://gbif-open-data-us-east-1/occurrence/. "
        "Cite individual records using the GBIF data publisher DOI."
    ),
}

# Field-level descriptions for the occurrence record schema.
# GBIF records are taxonomic occurrences rather than numeric measurements, so
# units/valid_range entries use "dimensionless" / "N/A" where not applicable.
VARIABLE_INFO: dict[str, dict[str, str]] = {
    "species": {
        "description": "Accepted scientific species name (binomial nomenclature)",
        "units": "dimensionless",
        "valid_range": "N/A",
    },
    "decimalLatitude": {
        "description": "WGS84 decimal latitude of the observed occurrence",
        "units": "degrees",
        "valid_range": "-90 to 90",
    },
    "decimalLongitude": {
        "description": "WGS84 decimal longitude of the observed occurrence",
        "units": "degrees",
        "valid_range": "-180 to 180",
    },
    "eventDate": {
        "description": "Date (and optionally time) of the observation in ISO 8601 format",
        "units": "ISO 8601",
        "valid_range": "1800-01-01 to present",
    },
    "taxonKey": {
        "description": "GBIF backbone taxon identifier for the accepted species",
        "units": "dimensionless",
        "valid_range": "1 to ~10^9",
    },
}

_GBIF_BUCKET = "gbif-open-data-us-east-1"
_DEFAULT_LIMIT = 1000

# The GBIF Open Data S3 Parquet snapshot stores all column names in lowercase
# (e.g. ``decimallatitude`` rather than ``decimalLatitude``). We rename them to
# the DwC camelCase standard before returning records so the output schema is
# stable regardless of S3-side formatting changes.
_COLUMN_RENAME: dict[str, str] = {
    "decimallatitude": "decimalLatitude",
    "decimallongitude": "decimalLongitude",
    "eventdate": "eventDate",
    "taxonkey": "taxonKey",
    "gbifid": "gbifID",
}

# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

# Module-level cache for the most-recent partition date.
# S3 listing across the full bucket is a round-trip; caching avoids repeating it
# on every call within the same process lifetime.
_cached_latest_partition: str | None = None


def _discover_latest_partition(fs: s3fs.S3FileSystem) -> str:
    """Return the most recent partition date string (YYYY-MM-DD) from S3."""
    global _cached_latest_partition
    if _cached_latest_partition is not None:
        return _cached_latest_partition
    folders: list[str] = fs.ls(f"{_GBIF_BUCKET}/occurrence/", detail=False)
    # Each entry looks like "gbif-open-data-us-east-1/occurrence/2024-01-01"
    dates = [f.split("/")[-1] for f in folders if f.split("/")[-1].count("-") == 2]
    if not dates:
        raise RuntimeError("No GBIF partition folders found in S3 bucket")
    _cached_latest_partition = sorted(dates)[-1]
    return _cached_latest_partition


# ---------------------------------------------------------------------------
# Core query logic (testable without MCP)
# ---------------------------------------------------------------------------


def _fetch_gbif(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    taxon_key: int | None,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str, list[str]]:
    """Read and filter GBIF occurrence Parquet on S3.

    Returns ``(records, total_before_cap, partition_date, unique_licenses)``.

    The data are spatial + temporal filtered, optionally filtered by taxon,
    and capped at *limit* rows. Columns returned per record:
    ``species``, ``decimalLatitude``, ``decimalLongitude``, ``eventDate``,
    ``taxonKey``, ``license``, ``gbifID``.
    """
    fs = s3fs.S3FileSystem(anon=True)
    partition = _discover_latest_partition(fs)

    # PyArrow dataset API is used instead of Dask because the GBIF Parquet
    # snapshot contains ~8 000 partitions; Dask requires listing every file
    # before filtering, which takes >120 s. PyArrow's scanner applies row-group
    # statistics pushdown and stops as soon as `limit + 1` rows are found,
    # completing in ~10 s for typical point/bbox queries.
    s3 = pafs.S3FileSystem(anonymous=True, region="us-east-1")
    path = f"{_GBIF_BUCKET}/occurrence/{partition}/occurrence.parquet"
    dataset = pads.dataset(path, filesystem=s3, format="parquet")

    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date + " 23:59:59", tz="UTC")

    filt = (
        (pc.field("decimallatitude") >= min_lat)
        & (pc.field("decimallatitude") <= max_lat)
        & (pc.field("decimallongitude") >= min_lon)
        & (pc.field("decimallongitude") <= max_lon)
        & (pc.field("eventdate") >= pa.scalar(start_ts))
        & (pc.field("eventdate") <= pa.scalar(end_ts))
    )
    if taxon_key is not None:
        filt = filt & (pc.field("taxonkey") == taxon_key)

    cols = [
        "species",
        "decimallatitude",
        "decimallongitude",
        "eventdate",
        "taxonkey",
        "license",
        "gbifid",
    ]
    table = dataset.scanner(columns=cols, filter=filt).head(limit + 1)
    result_df = table.to_pandas()

    total_before_cap = len(result_df)
    capped = total_before_cap > limit
    result_df = result_df.iloc[:limit]

    # Aggregate licenses before renaming columns ("license" is the same in both schemas).
    unique_licenses: list[str] = (
        result_df["license"].dropna().unique().tolist() if "license" in result_df.columns else []
    )

    # Rename lowercase S3 column names to the DwC camelCase standard.
    result_df = result_df.rename(columns=_COLUMN_RENAME)

    records: list[dict[str, Any]] = result_df.to_dict(orient="records")  # type: ignore[assignment]
    return records, total_before_cap if not capped else total_before_cap, partition, unique_licenses


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------


@mcp.tool()
def gbif_occurrences(
    latitude: float,
    longitude: float,
    radius_km: float,
    start_date: str,
    end_date: str,
    taxon_key: int | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return GBIF species occurrence records within *radius_km* of a point.

    Data are read from the most recent monthly GBIF Parquet snapshot on the
    AWS Open Data Registry (``s3://gbif-open-data-us-east-1``).

    Args:
        latitude: WGS84 decimal latitude of the query centre.
        longitude: WGS84 decimal longitude of the query centre.
        radius_km: Search radius in kilometres (converted to a bbox internally).
        start_date: Inclusive start date, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end date, ISO 8601 ``YYYY-MM-DD``.
        taxon_key: Optional GBIF taxon key to restrict results to a single taxon.
        limit: Maximum number of occurrence records to return (default 1 000).

    Returns:
        ``{"data": list[dict], "_meta": dict}`` — each data record contains
        ``species``, ``decimalLatitude``, ``decimalLongitude``, ``eventDate``,
        ``taxonKey``, ``license``, and ``gbifID``.
    """
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": radius_km,
        "start_date": start_date,
        "end_date": end_date,
        "taxon_key": taxon_key,
        "limit": limit,
    }
    # Convert radius_km to a rough bbox (1° ≈ 111 km).
    deg = radius_km / 111.0
    bbox = clamp_bbox(
        {
            "min_lat": latitude - deg,
            "max_lat": latitude + deg,
            "min_lon": longitude - deg,
            "max_lon": longitude + deg,
        }
    )
    try:
        records, total, partition, unique_licenses = _fetch_gbif(
            min_lat=bbox["min_lat"],
            max_lat=bbox["max_lat"],
            min_lon=bbox["min_lon"],
            max_lon=bbox["max_lon"],
            start_date=start_date,
            end_date=end_date,
            taxon_key=taxon_key,
            limit=limit,
        )
        latency = time.perf_counter() - t0
        capped = total > limit
        license_str = (
            " | ".join(sorted(set(unique_licenses))) if unique_licenses else LICENSE_INFO["license"]
        )
        meta = build_meta(
            source="gbif",
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info={**LICENSE_INFO, "license": license_str},
            variable_info=VARIABLE_INFO,
            success=True,
        )
        meta["capped"] = capped
        meta["partition_date"] = partition
        return {"data": records, "_meta": meta}
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="gbif",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }


@mcp.tool()
def gbif_bbox_occurrences(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    taxon_key: int | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return GBIF occurrence records within a bounding box.

    Identical to ``gbif_occurrences`` but accepts an explicit bounding box
    instead of a centre point + radius.

    Args:
        min_lat: Southern boundary (WGS84 decimal degrees).
        max_lat: Northern boundary.
        min_lon: Western boundary.
        max_lon: Eastern boundary.
        start_date: Inclusive start date, ISO 8601 ``YYYY-MM-DD``.
        end_date: Inclusive end date, ISO 8601 ``YYYY-MM-DD``.
        taxon_key: Optional GBIF taxon key to restrict results.
        limit: Maximum records to return (default 1 000).
    """
    t0 = time.perf_counter()
    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "start_date": start_date,
        "end_date": end_date,
        "taxon_key": taxon_key,
        "limit": limit,
    }
    bbox = clamp_bbox(
        {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
    )
    try:
        records, total, partition, unique_licenses = _fetch_gbif(
            min_lat=bbox["min_lat"],
            max_lat=bbox["max_lat"],
            min_lon=bbox["min_lon"],
            max_lon=bbox["max_lon"],
            start_date=start_date,
            end_date=end_date,
            taxon_key=taxon_key,
            limit=limit,
        )
        latency = time.perf_counter() - t0
        capped = total > limit
        license_str = (
            " | ".join(sorted(set(unique_licenses))) if unique_licenses else LICENSE_INFO["license"]
        )
        meta = build_meta(
            source="gbif",
            query_params=query_params,
            rows_returned=len(records),
            latency_s=latency,
            license_info={**LICENSE_INFO, "license": license_str},
            variable_info=VARIABLE_INFO,
            success=True,
        )
        meta["capped"] = capped
        meta["partition_date"] = partition
        return {"data": records, "_meta": meta}
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="gbif",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                success=False,
                error=str(exc),
            ),
        }
