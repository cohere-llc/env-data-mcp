"""
Shared utilities used by all source adapters.

Every source module imports from here. No source module re-implements these.
"""

from __future__ import annotations

import datetime
import json
import math
import pathlib
import re
from collections.abc import Mapping
from typing import Any

# ---------------------------------------------------------------------------
# Runtime estimation
# ---------------------------------------------------------------------------

_DEFAULT_RUNTIME_THRESHOLD_S: float = 30.0

# Lazy-loaded timing model (populated on first call to _get_timing_model).
_TIMING_MODEL: dict[str, Any] = {}

_TIMING_MODEL_PATH = pathlib.Path(__file__).parent / "timing_model.json"


def _get_timing_model() -> dict[str, Any]:
    """Return the per-source timing model coefficients, loading once on first call."""
    global _TIMING_MODEL
    if _TIMING_MODEL:
        return _TIMING_MODEL
    with _TIMING_MODEL_PATH.open() as fh:
        data = json.load(fh)
    _TIMING_MODEL = data.get("model", {})
    return _TIMING_MODEL


def estimate_runtime(source: str, n_days: int, area_deg2: float) -> float:
    """Estimate query wall-clock time in seconds using the fitted timing model.

    Uses the linear equation ``t ≈ α + β_n·n_days + β_a·area_deg2`` from
    ``timing_model.json``, then takes the maximum with a physics-based override
    formula for sources where the 2D model is unreliable at scale.  Five sources
    have overrides: OCO-2, EMIT, Sentinel-5P, OpenAQ, and GBIF.

    Args:
        source: Short source identifier, e.g. ``"gbif"``.
        n_days: Number of calendar days in the query window.
        area_deg2: Bounding-box area in square degrees (0 for point queries).

    Returns:
        Estimated seconds (clamped to ``>= 0``).
    """
    model = _get_timing_model()
    if source not in model:
        return 0.0
    m = model[source]
    alpha: float = float(m.get("alpha") or 0.0)
    beta_n: float = float(m.get("beta_n_days") or 0.0)
    # Clamp negative area slopes — larger bounding boxes must never reduce the
    # estimate used by the runtime gate (prevents gate bypass for wide bboxes).
    beta_a: float = max(0.0, float(m.get("beta_area_deg2") or 0.0))
    t_model = alpha + beta_n * n_days + beta_a * area_deg2

    # Physics-based overrides for sources where the fitted 2D model is
    # unreliable (low R², capped benchmark observations, or area effect
    # zeroed by clamping).  Each formula models the dominant cost driver.
    if source == "oco2":
        # Temporal-only CMR search; 10 parallel workers, each batch ≈ 3 s.
        t_override = 2.84 + math.ceil(n_days / 10) * 3.0
        t_model = max(t_model, t_override)
    elif source == "emit":
        # ~1 granule per 3 days at any point location; spatially-filtered CMR
        # returns proportionally more granules for larger bboxes (ISS orbit,
        # ~2.5× more at max 10°×10°).  Each granule: 2 sequential OPeNDAP
        # round-trips ≈ 3.5 s total.  Divisor=40 is a middle-ground between
        # aggressive (25) and conservative (50) orbital track density estimates.
        granules_per_3days = max(1.0, area_deg2 / 40.0)
        t_override = 0.2 + (n_days // 3) * granules_per_3days * 3.5
        t_model = max(t_model, t_override)
    elif source == "sentinel5p":
        # 16 GDAL COGT workers in parallel; each batch ≈ 4.5 s (calibrated
        # against all benchmark observations).  S5P swaths are ~2600 km wide,
        # so the granule-per-day rate saturates at ~4 deg² (any larger bbox is
        # covered by the same orbital passes): 1.0 granule/day for point queries,
        # 1.5 granules/day for bbox ≥ 4 deg².
        n_granules = n_days * (1.0 + 0.5 * min(1.0, area_deg2 / 4.0))
        t_override = 2.0 + math.ceil(n_granules / 16) * 4.5
        t_model = max(t_model, t_override)
    elif source == "openaq":
        # Fitted R²=0.07 — model is nearly useless (density varies by location).
        # Assumes a moderately busy urban station: ~1 page of measurements per
        # day at 0.4 s/page → 0.15 s/day.  Extreme dense-city outliers remain
        # a known limitation of location-agnostic estimation.
        t_override = 1.5 + 0.15 * n_days
        t_model = max(t_model, t_override)
    elif source == "gbif":
        # Benchmark coefficients were fit on 500-record-capped observations.
        # High-density biodiversity hotspots (Amazonia, SE Asia) can have
        # 10–50× more records → coefficients ~58% higher than the fitted model.
        t_override = 2.0 + n_days * 0.13 + area_deg2 * 0.18
        t_model = max(t_model, t_override)

    return max(0.0, t_model)


def check_runtime(
    source: str,
    n_days: int,
    area_deg2: float,
    max_runtime_s: float | None = None,
    scale_factor: float = 1.0,
) -> dict[str, Any] | None:
    """Return a slow-query warning dict if the estimated runtime exceeds the threshold.

    If the estimate is below the threshold, returns ``None`` (caller should proceed).

    Threshold logic:
    * No ``max_runtime_s`` supplied → threshold is ``_DEFAULT_RUNTIME_THRESHOLD_S`` (30 s).
    * ``max_runtime_s`` supplied → threshold is ``max_runtime_s * 1.2`` (20 % grace margin).

    Args:
        source: Short source identifier, e.g. ``"gbif"``.
        n_days: Number of calendar days in the query window.
        area_deg2: Bounding-box area in square degrees (0 for point queries).
        max_runtime_s: User-supplied acceptable runtime in seconds, or ``None``.
        scale_factor: Optional multiplier to apply to the estimate.

    Returns:
        ``None`` if the estimate is under the threshold, otherwise a response
        dict with ``data=[]`` and a ``_meta`` block describing the estimate.
    """
    t_est = estimate_runtime(source, n_days, area_deg2) * scale_factor
    threshold = max_runtime_s * 1.2 if max_runtime_s is not None else _DEFAULT_RUNTIME_THRESHOLD_S
    if t_est < threshold:
        return None
    headroom = int(t_est * 1.25) + 1
    return {
        "data": [],
        "_meta": {
            "source": source,
            "success": False,
            "slow_query_warning": True,
            "estimated_runtime_s": round(t_est, 1),
            "threshold_s": round(threshold, 1),
            "message": (
                f"Estimated runtime {t_est:.1f}s exceeds the {threshold:.1f}s threshold. "
                f"Pass max_runtime_s={headroom} to allow this query to proceed."
            ),
            # Standard _meta fields (with safe defaults) so callers get a
            # uniform schema whether the gate fires or the query completes.
            "rows_returned": 0,
            "latency_s": 0.0,
            "query_params": {},
            "auth_required": False,
            "auth_present": True,
            "license": "",
            "license_url": "",
            "error": None,
        },
    }


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


def bbox_area_deg2(bbox: dict[str, float]) -> float:
    """Return the approximate area of a bounding box in square degrees.

    Note: This is a simple approximation and does not account for the Earth's curvature.
    """
    max_lon = bbox["max_lon"] if bbox["max_lon"] >= bbox["min_lon"] else bbox["max_lon"] + 360.0
    lat_diff = bbox["max_lat"] - bbox["min_lat"]
    lon_diff = max_lon - bbox["min_lon"]
    return lat_diff * lon_diff


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def build_meta(
    source: str,
    query_params: dict[str, Any],
    rows_returned: int,
    latency_s: float,
    license_info: Mapping[str, str | list[str]],
    *,
    auth_required: bool = False,
    auth_present: bool = True,
    success: bool = True,
    error: str | None = None,
    variables: list[str] | None = None,
    variable_info: dict[str, Any] | None = None,
    unavailable_variables: list[str] | None = None,
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
        variable_info: Dict mapping each variable name to its metadata
            (description, units, valid_range). Populated from the source
            module's VARIABLE_INFO constant, filtered to requested variables.
    """
    return {
        "source": source,
        "variables": variables if variables is not None else [],
        "variable_info": variable_info if variable_info is not None else {},
        "unavailable_variables": unavailable_variables if unavailable_variables is not None else [],
        "rows_returned": rows_returned,
        "latency_s": round(latency_s, 3),
        "auth_required": auth_required,
        "auth_present": auth_present,
        "success": success,
        "error": error,
        "license": license_info.get("license", ""),
        "license_url": license_info.get("license_url", ""),
        "citation": license_info.get("citation", ""),
        "citation_urls": license_info.get("citation_urls", []),
        "description": license_info.get("description", ""),
        "description_url": license_info.get("description_url", ""),
        "acknowledgements": license_info.get("acknowledgements", ""),
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
