"""Benchmark integration tests for env-data-mcp sources.

Runs a conservative Phase-1 matrix of (source × date-range) queries, checks
point/bbox spatial consistency for a small 0.5°×0.5° window, records
``_meta["latency_s"]`` from every call, fits a per-source linear timing model
    t_est(n_days) = α + β·n_days
and writes the fitted coefficients + raw timing data to
``src/env_data_mcp/timing_model.json``.

Run with:
    uv run pytest tests/integration/test_benchmarks.py -v -m integration

The JSON output is committed to the repo so that developers and the MCP server
can estimate query latency without running the benchmark themselves.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from env_data_mcp.sources.emit import emit_bbox_query, emit_query
from env_data_mcp.sources.essdive import essdive_bbox_query, essdive_query
from env_data_mcp.sources.gbif import gbif_bbox_occurrences, gbif_occurrences
from env_data_mcp.sources.nasa_power import nasa_power_bbox_query, nasa_power_query
from env_data_mcp.sources.oco2 import oco2_bbox_query, oco2_query
from env_data_mcp.sources.openaq import openaq_bbox_query, openaq_query
from env_data_mcp.sources.sentinel5p import sentinel5p_bbox_query, sentinel5p_query
from env_data_mcp.sources.soilgrids import soilgrids_bbox_query, soilgrids_query
from env_data_mcp.sources.ssurgo import ssurgo_bbox_query, ssurgo_query

# ---------------------------------------------------------------------------
# Reference location & time windows
# ---------------------------------------------------------------------------

_LAT = 46.2531882  # Yakima River Valley, WA — reliable multi-source coverage
_LON = -119.4768203

# Phase-1 date scenarios: 1-day, 1-week, 1-month
_SCENARIOS: list[dict[str, Any]] = [
    {"name": "1day", "start": "2019-08-19", "end": "2019-08-19", "n_days": 1},
    {"name": "1week", "start": "2019-08-15", "end": "2019-08-21", "n_days": 7},
    {"name": "1month", "start": "2019-08-01", "end": "2019-08-31", "n_days": 31},
]

# Sources that are skipped for the 1-month scenario to stay inside the 5-min budget
_SLOW_SOURCES = {"oco2", "emit"}

# Small consistency-check bbox — 0.5° × 0.5° centred on the reference point
_BBOX_HALF = 0.25
_BBOX = {
    "min_lat": _LAT - _BBOX_HALF,
    "max_lat": _LAT + _BBOX_HALF,
    "min_lon": _LON - _BBOX_HALF,
    "max_lon": _LON + _BBOX_HALF,
}

# Maximum acceptable latency per query (hard cap; test fails if exceeded)
_MAX_LATENCY_S = 60.0

# Geographic tolerance for the geo_overlap consistency check
_GEO_TOLERANCE_DEG = 0.3

# Output path for timing model (relative to repo root)
_TIMING_MODEL_PATH = Path(__file__).parents[2] / "src" / "env_data_mcp" / "timing_model.json"

# ---------------------------------------------------------------------------
# Session-level timing accumulator
# ---------------------------------------------------------------------------

# Populated by each timing test; consumed in the session teardown fixture.
_TIMING: dict[str, list[dict[str, Any]]] = {}


def _record(source: str, scenario_name: str, n_days: int, result: dict[str, Any]) -> None:
    """Append a timing observation to the in-memory accumulator."""
    _TIMING.setdefault(source, []).append(
        {
            "scenario": scenario_name,
            "n_days": n_days,
            "area_deg2": 0.0,
            "latency_s": result["_meta"].get("latency_s", 0.0),
            "success": result["_meta"].get("success", False),
            "n_records": len(result.get("data", [])),
        }
    )


# ---------------------------------------------------------------------------
# Model fitting & JSON writer (runs once, at session teardown)
# ---------------------------------------------------------------------------


def _fit_and_write_model() -> None:
    """Fit per-source linear timing models and write timing_model.json."""
    if not _TIMING:
        return  # Nothing to write if no benchmarks ran

    model: dict[str, Any] = {}
    for source, rows in sorted(_TIMING.items()):
        successful = [r for r in rows if r["success"]]
        point_rows = [r for r in successful if r["area_deg2"] == 0.0]

        if len(point_rows) >= 3:
            xs = np.array([r["n_days"] for r in point_rows], dtype=float)
            ys = np.array([r["latency_s"] for r in point_rows], dtype=float)
            beta, alpha = np.polyfit(xs, ys, 1)
            alpha, beta = float(alpha), float(beta)
            y_pred = alpha + beta * xs
            ss_res = float(np.sum((ys - y_pred) ** 2))
            ss_tot = float(np.sum((ys - float(np.mean(ys))) ** 2))
            r2 = round(1.0 - ss_res / ss_tot, 4) if ss_tot > 0 else None
            equation = f"t ≈ {alpha:.2f} + {beta:.3f}·n_days"
        elif len(point_rows) == 2:
            xs = np.array([r["n_days"] for r in point_rows], dtype=float)
            ys = np.array([r["latency_s"] for r in point_rows], dtype=float)
            beta, alpha = np.polyfit(xs, ys, 1)
            alpha, beta = float(alpha), float(beta)
            r2 = None  # not meaningful with only 2 points
            equation = f"t ≈ {alpha:.2f} + {beta:.3f}·n_days  (2-point fit)"
        elif len(point_rows) == 1:
            alpha = point_rows[0]["latency_s"]
            beta = 0.0
            r2 = None
            equation = f"t ≈ {alpha:.2f}  (single observation)"
        else:
            # No successful runs — emit a placeholder
            model[source] = {"alpha": None, "beta_n_days": None, "r2": None, "equation": "no data"}
            continue

        model[source] = {
            "alpha": round(alpha, 3),
            "beta_n_days": round(beta, 4),
            "r2": r2,
            "equation": equation,
        }

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Phase 1 — Yakima WA (46.25°, −119.47°), ≤ 1 month, point queries. "
            "Model: t_est(n_days) = alpha + beta_n_days · n_days  (seconds). "
            "Regenerate: uv run pytest tests/integration/test_benchmarks.py -m integration"
        ),
        "location": {"latitude": _LAT, "longitude": _LON},
        "model": model,
        "raw": _TIMING,
    }
    _TIMING_MODEL_PATH.write_text(json.dumps(output, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _write_model_on_teardown():
    """After all benchmark tests complete, fit the model and persist to JSON."""
    yield
    _fit_and_write_model()


# ---------------------------------------------------------------------------
# Auth-guard fixtures (skip entire source group if credentials missing)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _earthdata_token() -> str:
    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        pytest.skip("EARTHDATA_TOKEN not set — skipping OCO-2 / EMIT benchmarks")
    return token


@pytest.fixture(scope="session")
def _openaq_key() -> str:
    key = os.environ.get("OPENAQ_API_KEY", "")
    if not key:
        pytest.skip("OPENAQ_API_KEY not set — skipping OpenAQ benchmarks")
    return key


@pytest.fixture(scope="session")
def _essdive_token() -> str:
    token = os.environ.get("ESSDIVE_TOKEN", "")
    if not token:
        pytest.skip("ESSDIVE_TOKEN not set — skipping ESS-DIVE benchmarks")
    return token


# ---------------------------------------------------------------------------
# Helper: skip gracefully if a query result signals auth failure
# ---------------------------------------------------------------------------


def _assert_or_skip(result: dict[str, Any], source: str) -> None:
    """Fail the test for errors, skip for auth/service issues."""
    meta = result["_meta"]
    if not meta.get("auth_present", True):
        pytest.skip(f"{source}: auth token rejected or expired — {meta.get('error')}")
    assert meta["success"] is True, f"{source} query failed: {meta.get('error')}"


# ===========================================================================
# NASA POWER — no auth, very fast, Zarr-based
# ===========================================================================


@pytest.mark.integration
@pytest.mark.parametrize("sc", _SCENARIOS, ids=lambda s: s["name"])
def test_nasa_power_timing(sc):
    result = nasa_power_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=sc["start"],
        end_date=sc["end"],
        variables=["T2M"],
    )
    _assert_or_skip(result, "nasa_power")
    _record("nasa_power", sc["name"], sc["n_days"], result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_nasa_power_point_bbox_consistent():
    """Centroid-based source: point and small bbox must return identical records."""
    pt = nasa_power_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2019-08-19",
        end_date="2019-08-19",
        variables=["T2M"],
    )
    bx = nasa_power_bbox_query(
        **_BBOX,
        start_date="2019-08-19",
        end_date="2019-08-19",
        variables=["T2M"],
    )
    _assert_or_skip(pt, "nasa_power/point")
    _assert_or_skip(bx, "nasa_power/bbox")
    assert pt["data"] == bx["data"], (
        "nasa_power point and bbox results differ for a small bbox "
        "(both use centroid — should be identical)"
    )


# ===========================================================================
# SoilGrids — no auth, REST-based, date-range free
# ===========================================================================


@pytest.mark.integration
def test_soilgrids_timing():
    result = soilgrids_query(latitude=_LAT, longitude=_LON)
    _assert_or_skip(result, "soilgrids")
    _record("soilgrids", "point", 0, result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_soilgrids_point_bbox_consistent():
    """Centroid-based: small bbox must return identical records to point query."""
    pt = soilgrids_query(latitude=_LAT, longitude=_LON)
    bx = soilgrids_bbox_query(**_BBOX)
    _assert_or_skip(pt, "soilgrids/point")
    _assert_or_skip(bx, "soilgrids/bbox")
    assert pt["data"] == bx["data"], "soilgrids point/bbox results differ (centroid-based)"


# ===========================================================================
# SSURGO — no auth, USDA SDA, date-range free
# ===========================================================================


@pytest.mark.integration
def test_ssurgo_timing():
    result = ssurgo_query(latitude=_LAT, longitude=_LON)
    if not result["_meta"].get("success"):
        pytest.skip(f"SSURGO query failed: {result['_meta'].get('error')}")
    _record("ssurgo", "point", 0, result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_ssurgo_point_bbox_consistent():
    """Centroid-based: small bbox must return identical records to point query."""
    pt = ssurgo_query(latitude=_LAT, longitude=_LON)
    bx = ssurgo_bbox_query(**_BBOX)
    if not pt["_meta"].get("success") or not bx["_meta"].get("success"):
        pytest.skip("SSURGO returned no data for this location")
    assert pt["data"] == bx["data"], "ssurgo point/bbox results differ (centroid-based)"


# ===========================================================================
# GBIF — no auth, S3 Parquet
# ===========================================================================

_GBIF_SCENARIOS = _SCENARIOS  # fragment cap bounds latency regardless of date range


@pytest.mark.integration
@pytest.mark.parametrize("sc", _GBIF_SCENARIOS, ids=lambda s: s["name"])
def test_gbif_timing(sc):
    result = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=10.0,
        start_date=sc["start"],
        end_date=sc["end"],
        limit=200,
    )
    _assert_or_skip(result, "gbif")
    _record("gbif", sc["name"], sc["n_days"], result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_gbif_point_bbox_consistent():
    """Small bbox should contain records near the point and counts should agree ±20 %."""
    pt = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=10.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
        limit=200,
    )
    bx = gbif_bbox_occurrences(
        **_BBOX,
        start_date="2019-08-19",
        end_date="2019-08-19",
        limit=200,
    )
    _assert_or_skip(pt, "gbif/point")
    _assert_or_skip(bx, "gbif/bbox")
    _check_geo_overlap(pt["data"], bx["data"], "gbif")


# ===========================================================================
# Sentinel-5P — no auth, S3 HDF5, all scenarios
# ===========================================================================


@pytest.mark.integration
@pytest.mark.parametrize("sc", _SCENARIOS, ids=lambda s: s["name"])
def test_sentinel5p_timing(sc):
    result = sentinel5p_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=sc["start"],
        end_date=sc["end"],
        product="CO",
    )
    _assert_or_skip(result, "sentinel5p")
    _record("sentinel5p", sc["name"], sc["n_days"], result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_sentinel5p_point_bbox_consistent():
    pt = sentinel5p_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2019-08-19",
        end_date="2019-08-19",
        product="CO",
    )
    bx = sentinel5p_bbox_query(
        **_BBOX,
        start_date="2019-08-19",
        end_date="2019-08-19",
        product="CO",
    )
    _assert_or_skip(pt, "sentinel5p/point")
    _assert_or_skip(bx, "sentinel5p/bbox")
    _check_geo_overlap(pt["data"], bx["data"], "sentinel5p")


# ===========================================================================
# OpenAQ — requires OPENAQ_API_KEY
# ===========================================================================


@pytest.mark.integration
@pytest.mark.parametrize("sc", _SCENARIOS, ids=lambda s: s["name"])
def test_openaq_timing(sc, _openaq_key):
    result = openaq_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date=sc["start"],
        end_date=sc["end"],
        limit=200,
    )
    _assert_or_skip(result, "openaq")
    _record("openaq", sc["name"], sc["n_days"], result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_openaq_point_bbox_consistent(_openaq_key):
    pt = openaq_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
        limit=200,
    )
    bx = openaq_bbox_query(
        **_BBOX,
        start_date="2019-08-19",
        end_date="2019-08-19",
        limit=200,
    )
    _assert_or_skip(pt, "openaq/point")
    _assert_or_skip(bx, "openaq/bbox")
    _check_geo_overlap(pt["data"], bx["data"], "openaq")


# ===========================================================================
# ESS-DIVE — requires ESSDIVE_TOKEN
# ===========================================================================


@pytest.mark.integration
@pytest.mark.parametrize("sc", _SCENARIOS, ids=lambda s: s["name"])
def test_essdive_timing(sc, _essdive_token):
    result = essdive_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date=sc["start"],
        end_date=sc["end"],
        limit=10,
    )
    _assert_or_skip(result, "essdive")
    _record("essdive", sc["name"], sc["n_days"], result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_essdive_point_bbox_consistent(_essdive_token):
    """ESS-DIVE: count-only consistency (no per-record lat/lon in results)."""
    pt = essdive_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=10,
    )
    bx = essdive_bbox_query(
        **_BBOX,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=10,
    )
    _assert_or_skip(pt, "essdive/point")
    _assert_or_skip(bx, "essdive/bbox")
    _check_count_only(pt["data"], bx["data"], "essdive")


# ===========================================================================
# OCO-2 — requires EARTHDATA_TOKEN; skip 1-month to stay within time budget
# ===========================================================================

_OCO2_SCENARIOS = [s for s in _SCENARIOS if s["name"] != "1month"]


@pytest.mark.integration
@pytest.mark.parametrize("sc", _OCO2_SCENARIOS, ids=lambda s: s["name"])
def test_oco2_timing(sc, _earthdata_token):
    result = oco2_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=sc["start"],
        end_date=sc["end"],
    )
    _assert_or_skip(result, "oco2")
    _record("oco2", sc["name"], sc["n_days"], result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_oco2_point_bbox_consistent(_earthdata_token):
    pt = oco2_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    bx = oco2_bbox_query(
        **_BBOX,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    _assert_or_skip(pt, "oco2/point")
    _assert_or_skip(bx, "oco2/bbox")
    _check_geo_overlap(pt["data"], bx["data"], "oco2")


# ===========================================================================
# EMIT — requires EARTHDATA_TOKEN; skip 1-month to stay within time budget
# ===========================================================================

_EMIT_SCENARIOS = [s for s in _SCENARIOS if s["name"] != "1month"]


@pytest.mark.integration
@pytest.mark.parametrize("sc", _EMIT_SCENARIOS, ids=lambda s: s["name"])
def test_emit_timing(sc, _earthdata_token):
    result = emit_query(
        latitude=_LAT,
        longitude=_LON,
        start_date=sc["start"],
        end_date=sc["end"],
    )
    _assert_or_skip(result, "emit")
    _record("emit", sc["name"], sc["n_days"], result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_emit_point_bbox_consistent(_earthdata_token):
    pt = emit_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    bx = emit_bbox_query(
        **_BBOX,
        start_date="2019-08-19",
        end_date="2019-08-19",
    )
    _assert_or_skip(pt, "emit/point")
    _assert_or_skip(bx, "emit/bbox")
    _check_geo_overlap(pt["data"], bx["data"], "emit")


# ===========================================================================
# Consistency-check helpers
# ===========================================================================


def _extract_coords(records: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Return (lat, lon) pairs from records that carry coordinate fields."""
    coords = []
    for rec in records:
        lat = rec.get("latitude") or rec.get("lat")
        lon = rec.get("longitude") or rec.get("lon")
        if lat is not None and lon is not None:
            coords.append((float(lat), float(lon)))
    return coords


def _check_geo_overlap(
    point_data: list[dict[str, Any]],
    bbox_data: list[dict[str, Any]],
    source: str,
) -> None:
    """Assert count ±20 % and geographic overlap between point and bbox results.

    Skips gracefully when both queries return no data (sparse coverage).
    The count check compares the smaller to the larger result set: if the bbox
    covers the same area as the point radius it should return a comparable
    number of records.  The geo check verifies that at least one bbox record
    falls within _GEO_TOLERANCE_DEG of the reference point.
    """
    n_pt = len(point_data)
    n_bx = len(bbox_data)

    if n_pt == 0 and n_bx == 0:
        pytest.skip(f"{source}: both point and bbox returned no records — sparse coverage")

    if n_pt == 0:
        pytest.skip(
            f"{source}: point query returned no records — single-day/small-radius "
            "coverage too sparse for consistency check"
        )

    # Count consistency: smaller must be ≥ 80 % of larger
    n_lo, n_hi = min(n_pt, n_bx), max(n_pt, n_bx)
    if n_hi > 0:
        ratio = n_lo / n_hi
        assert ratio >= 0.8, (
            f"{source}: record counts differ by more than 20% "
            f"(point={n_pt}, bbox={n_bx}, ratio={ratio:.2f})"
        )

    # Geographic overlap: ≥1 bbox record within tolerance of the reference point
    bbox_coords = _extract_coords(bbox_data)
    if bbox_coords:
        dists = [sqrt((lat - _LAT) ** 2 + (lon - _LON) ** 2) for lat, lon in bbox_coords]
        assert min(dists) <= _GEO_TOLERANCE_DEG, (
            f"{source}: no bbox record found within {_GEO_TOLERANCE_DEG}° of "
            f"reference point ({_LAT}, {_LON}); closest is {min(dists):.3f}°"
        )


def _check_count_only(
    point_data: list[dict[str, Any]],
    bbox_data: list[dict[str, Any]],
    source: str,
) -> None:
    """Assert record counts are within 20 % of each other (no lat/lon check)."""
    n_pt = len(point_data)
    n_bx = len(bbox_data)

    if n_pt == 0 and n_bx == 0:
        pytest.skip(f"{source}: both point and bbox returned no records")

    n_lo, n_hi = min(n_pt, n_bx), max(n_pt, n_bx)
    if n_hi > 0:
        ratio = n_lo / n_hi
        assert ratio >= 0.8, (
            f"{source}: record counts differ by more than 20% "
            f"(point={n_pt}, bbox={n_bx}, ratio={ratio:.2f})"
        )
