"""
Shared utilities used by all source adapters.

Every source module imports from here. No source module re-implements these.
"""

from __future__ import annotations

import datetime
import re
import warnings
from typing import Any

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(date_str: str) -> datetime.date:
    """Parse a strict ISO 8601 date string (YYYY-MM-DD) to a date object.

    Raises ValueError with a clear message for any other format.
    """
    stripped = date_str.strip()
    if not _ISO_DATE_RE.fullmatch(stripped):
        raise ValueError(
            f"Invalid date: {date_str!r}. Expected ISO 8601 format YYYY-MM-DD, e.g. '2019-08-15'."
        )
    return datetime.date.fromisoformat(stripped)


# ---------------------------------------------------------------------------
# Bounding-box helpers
# ---------------------------------------------------------------------------


def bbox_centroid(bbox: dict[str, float]) -> tuple[float, float]:
    """Return the (lat, lon) centroid of a bounding-box dict.

    Keys: min_lat, max_lat, min_lon, max_lon.
    """
    lat = (bbox["min_lat"] + bbox["max_lat"]) / 2.0
    lon = (bbox["min_lon"] + bbox["max_lon"]) / 2.0
    return lat, lon


def bbox_to_wkt_polygon(bbox: dict[str, float]) -> str:
    """Return a WKT POLYGON string for the bounding box.

    Coordinates are in (longitude latitude) order per WKT convention.
    The ring is explicitly closed (first == last vertex).
    """
    min_lat = bbox["min_lat"]
    max_lat = bbox["max_lat"]
    min_lon = bbox["min_lon"]
    max_lon = bbox["max_lon"]
    return (
        f"POLYGON (("
        f"{min_lon} {min_lat}, "
        f"{max_lon} {min_lat}, "
        f"{max_lon} {max_lat}, "
        f"{min_lon} {max_lat}, "
        f"{min_lon} {min_lat}"
        f"))"
    )


def clamp_bbox(bbox: dict[str, float], *, max_degrees: float = 10.0) -> dict[str, float]:
    """Return the bbox unchanged if within limits; otherwise warn and clamp.

    Each dimension (lat span, lon span) is clamped independently to
    max_degrees, centred on the bbox centroid.
    """
    lat_span = bbox["max_lat"] - bbox["min_lat"]
    lon_span = bbox["max_lon"] - bbox["min_lon"]

    if lat_span <= max_degrees and lon_span <= max_degrees:
        return bbox

    warnings.warn(
        f"Bounding box ({lat_span:.2f}° lat × {lon_span:.2f}° lon) exceeds "
        f"max_degrees={max_degrees}. Clamping each oversized dimension to "
        f"{max_degrees}° centred on the bbox centroid.",
        UserWarning,
        stacklevel=2,
    )

    clat, clon = bbox_centroid(bbox)
    half = max_degrees / 2.0
    result = dict(bbox)

    if lat_span > max_degrees:
        result["min_lat"] = clat - half
        result["max_lat"] = clat + half
        # Shift window back into valid latitude range [-90, 90] while preserving span.
        if result["max_lat"] > 90.0:
            result["min_lat"] -= result["max_lat"] - 90.0
            result["max_lat"] = 90.0
        elif result["min_lat"] < -90.0:
            result["max_lat"] += -90.0 - result["min_lat"]
            result["min_lat"] = -90.0

    if lon_span > max_degrees:
        result["min_lon"] = clon - half
        result["max_lon"] = clon + half
        # Shift window back into valid longitude range [-180, 180] while preserving span.
        if result["max_lon"] > 180.0:
            result["min_lon"] -= result["max_lon"] - 180.0
            result["max_lon"] = 180.0
        elif result["min_lon"] < -180.0:
            result["max_lon"] += -180.0 - result["min_lon"]
            result["min_lon"] = -180.0

    return result


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def build_meta(
    source: str,
    query_params: dict[str, Any],
    rows_returned: int,
    latency_s: float,
    license_info: dict[str, str],
    *,
    auth_required: bool = False,
    auth_present: bool = True,
    success: bool = True,
    error: str | None = None,
    variables: list[str] | None = None,
) -> dict[str, Any]:
    """Construct the standard _meta dict returned by every tool.

    Args:
        source: Short identifier for the data source (e.g. "nasa_power").
        query_params: The exact resolved inputs used for the query, echoed
            back verbatim so any result can be reproduced from a log record.
        rows_returned: Number of data records in the response.
        latency_s: Wall-clock seconds for the data fetch.
        license_info: Dict with at least "license" and "license_url" keys,
            typically the LICENSE_INFO constant from the source module.
        auth_required: Whether this source requires credentials.
        auth_present: Whether credentials were found at call time.
        success: Whether the query succeeded.
        error: Human-readable error message, or None on success.
        variables: List of variable names returned (for multi-variable sources).
    """
    return {
        "source": source,
        "variables": variables if variables is not None else [],
        "rows_returned": rows_returned,
        "latency_s": round(latency_s, 3),
        "auth_required": auth_required,
        "auth_present": auth_present,
        "success": success,
        "error": error,
        "license": license_info.get("license", ""),
        "license_url": license_info.get("license_url", ""),
        "query_params": query_params,
    }


def auth_missing_response(
    source: str,
    license_info: dict[str, str],
    error_msg: str,
    query_params: dict[str, Any],
) -> dict[str, Any]:
    """Return the standard no-auth failure response without raising an exception.

    Callers can detect missing credentials via _meta.auth_present == False and
    log the friction without crashing or blocking other source queries.
    """
    return {
        "data": [],
        "_meta": build_meta(
            source=source,
            query_params=query_params,
            rows_returned=0,
            latency_s=0.0,
            license_info=license_info,
            auth_required=True,
            auth_present=False,
            success=False,
            error=error_msg,
        ),
    }
