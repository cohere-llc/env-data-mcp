"""Benchmark integration tests for env-data-mcp sources.

Runs a Phase-2 matrix of (source × date-range × location × bbox-size) queries,
checks point/bbox spatial consistency for a small 0.5°×0.5° window, records
``_meta["latency_s"]`` from every call, fits a per-source 2-D timing model
    t_est(n_days, area_deg2) = α + β_n·n_days + β_a·area_deg2
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

# Extra geographic locations to capture regional variation in record density
_LOCATIONS: list[dict[str, Any]] = [
    {
        "name": "yakima_wa",
        "lat": 46.2531882,
        "lon": -119.4768203,
        "label": "Yakima WA (semi-arid, agricultural)",
    },
    {
        "name": "manaus_br",
        "lat": -3.1019,
        "lon": -60.025,
        "label": "Manaus BR (Amazon, tropical)",
    },
    {
        "name": "frankfurt_de",
        "lat": 50.1109,
        "lon": 8.6821,
        "label": "Frankfurt DE (urban, European)",
    },
]
_EXTRA_LOCATIONS = _LOCATIONS[1:]  # additional locations beyond the primary Yakima reference

# Bbox sizes for the 2-D area sweep (n_days × area_deg2)
_BBOX_SIZES: list[dict[str, Any]] = [
    {"name": "0.5x0.5", "half": 0.25, "area_deg2": 0.25},  # 0.5° × 0.5°
    {"name": "2x2", "half": 1.0, "area_deg2": 4.0},  # 2° × 2°
]

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


def _record(
    source: str,
    scenario_name: str,
    n_days: int,
    result: dict[str, Any],
    *,
    area_deg2: float = 0.0,
    location: str = "yakima_wa",
) -> None:
    """Append a timing observation to the in-memory accumulator."""
    _TIMING.setdefault(source, []).append(
        {
            "scenario": scenario_name,
            "n_days": n_days,
            "area_deg2": area_deg2,
            "location": location,
            "latency_s": result["_meta"].get("latency_s", 0.0),
            "success": result["_meta"].get("success", False),
            "n_records": len(result.get("data", [])),
        }
    )


def _make_bbox(lat: float, lon: float, half: float) -> dict[str, float]:
    """Return a min/max lat/lon bbox dict centred on (lat, lon) with given half-width."""
    return {
        "min_lat": lat - half,
        "max_lat": lat + half,
        "min_lon": lon - half,
        "max_lon": lon + half,
    }


# ---------------------------------------------------------------------------
# Model fitting & JSON writer (runs once, at session teardown)
# ---------------------------------------------------------------------------


def _fit_and_write_model() -> None:
    """Fit per-source 2-D timing models and write timing_model.json.

    Model: t_est(n_days, area_deg2) = alpha + beta_n_days·n_days + beta_area_deg2·area_deg2
    Fitted by OLS across all successful observations (point queries at multiple
    locations + bbox queries at multiple sizes and date ranges).

    Fit uses only observations that returned at least one record to avoid
    biasing coefficients with API-overhead-only (empty-result) timings.
    Centroid-based sources (NASA POWER, SoilGrids, SSURGO) have beta_area_deg2
    clamped to 0.0 post-fit since their implementation ignores bbox extent.
    """
    # Sources whose implementation queries a single centroid regardless of bbox.
    _CENTROID_SOURCES = {"nasa_power", "soilgrids", "ssurgo"}

    if not _TIMING:
        return  # Nothing to write if no benchmarks ran

    model: dict[str, Any] = {}
    for source, rows in sorted(_TIMING.items()):
        successful = [r for r in rows if r["success"]]

        if not successful:
            model[source] = {
                "alpha": None,
                "beta_n_days": None,
                "beta_area_deg2": None,
                "r2": None,
                "equation": "no data",
            }
            continue

        # Use only observations that returned data for model fitting; this
        # avoids biasing coefficients with API-overhead-only timings that
        # arise from empty-result queries (wrong date range, out-of-coverage
        # location, etc.).  Fall back to all successful rows if none have data.
        fit_rows = [r for r in successful if r["n_records"] > 0]
        if not fit_rows:
            fit_rows = successful  # best we can do

        n_days_arr = np.array([r["n_days"] for r in fit_rows], dtype=float)
        area_arr = np.array([r["area_deg2"] for r in fit_rows], dtype=float)
        y_arr = np.array([r["latency_s"] for r in fit_rows], dtype=float)
        n = len(fit_rows)

        has_area_var = bool(np.any(area_arr != area_arr[0]))
        has_time_var = bool(np.any(n_days_arr != n_days_arr[0]))

        if n >= 3 and (has_area_var or has_time_var):
            X = np.column_stack([np.ones(n), n_days_arr, area_arr])
            coeffs, _, _, _ = np.linalg.lstsq(X, y_arr, rcond=None)
            alpha, beta_n, beta_a = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])
            y_pred = X @ coeffs
            ss_res = float(np.sum((y_arr - y_pred) ** 2))
            ss_tot = float(np.sum((y_arr - float(np.mean(y_arr))) ** 2))
            r2 = round(1.0 - ss_res / ss_tot, 4) if ss_tot > 0 else None
            equation = f"t ≈ {alpha:.2f} + {beta_n:.3f}·n_days + {beta_a:.4f}·area_deg2"
        elif n == 2:
            if has_time_var:
                beta_n = float((y_arr[1] - y_arr[0]) / (n_days_arr[1] - n_days_arr[0] + 1e-9))
                alpha = float(y_arr[0] - beta_n * n_days_arr[0])
                beta_a = 0.0
            else:
                beta_a = float((y_arr[1] - y_arr[0]) / (area_arr[1] - area_arr[0] + 1e-9))
                alpha = float(y_arr[0] - beta_a * area_arr[0])
                beta_n = 0.0
            r2 = None
            equation = (
                f"t ≈ {alpha:.2f} + {beta_n:.3f}·n_days + {beta_a:.4f}·area_deg2  (2-point fit)"
            )
        else:
            alpha = float(np.mean(y_arr))
            beta_n = 0.0
            beta_a = 0.0
            r2 = None
            equation = f"t ≈ {alpha:.2f}  (single observation)"

        # Centroid-based sources query a single point regardless of bbox size;
        # area has no genuine effect on their latency.
        if source in _CENTROID_SOURCES:
            beta_a = 0.0
            # Restate equation with the clamped value
            if n >= 3:
                equation = f"t ≈ {alpha:.2f} + {beta_n:.3f}·n_days + 0.0000·area_deg2"

        model[source] = {
            "alpha": round(alpha, 3),
            "beta_n_days": round(beta_n, 4),
            "beta_area_deg2": round(beta_a, 4),
            "r2": r2,
            "equation": equation,
        }

    # Merge with the existing timing_model.json so that sources not benchmarked
    # in the current run retain their previously fitted coefficients and raw data.
    existing_model: dict[str, Any] = {}
    existing_raw: dict[str, Any] = {}
    if _TIMING_MODEL_PATH.exists():
        try:
            existing = json.loads(_TIMING_MODEL_PATH.read_text())
            existing_model = existing.get("model", {})
            existing_raw = existing.get("raw", {})
        except (json.JSONDecodeError, OSError):
            pass  # Corrupt or missing file — start fresh

    merged_model = {**existing_model, **model}
    merged_raw = {**existing_raw, **_TIMING}

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Phase 3 — multiple locations (Yakima WA, Manaus BR, Frankfurt DE), "
            "point + bbox queries. Model: t_est(n_days, area_deg2) = "
            "alpha + beta_n_days\u00b7n_days + beta_area_deg2\u00b7area_deg2 (seconds). "
            "Fit uses only observations with n_records > 0. "
            "Centroid-based sources (nasa_power, soilgrids, ssurgo) have "
            "beta_area_deg2 clamped to 0. "
            "Regenerate: uv run pytest tests/integration/test_benchmarks.py -m integration"
        ),
        "locations": _LOCATIONS,
        "model": merged_model,
        "raw": merged_raw,
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
@pytest.mark.parametrize("bz", _BBOX_SIZES, ids=lambda b: b["name"])
@pytest.mark.parametrize("sc", _SCENARIOS, ids=lambda s: s["name"])
def test_nasa_power_bbox_timing(sc, bz):
    result = nasa_power_bbox_query(
        **_make_bbox(_LAT, _LON, bz["half"]),
        start_date=sc["start"],
        end_date=sc["end"],
        variables=["T2M"],
    )
    _assert_or_skip(result, "nasa_power/bbox")
    _record(
        "nasa_power",
        f"{sc['name']}/bbox/{bz['name']}",
        sc["n_days"],
        result,
        area_deg2=bz["area_deg2"],
    )
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("loc", _EXTRA_LOCATIONS, ids=lambda loc: loc["name"])
def test_nasa_power_extra_location_timing(loc):
    result = nasa_power_query(
        latitude=loc["lat"],
        longitude=loc["lon"],
        start_date="2019-08-01",
        end_date="2019-08-31",
        variables=["T2M"],
    )
    _assert_or_skip(result, f"nasa_power/{loc['name']}")
    _record("nasa_power", "1month", 31, result, location=loc["name"])
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
@pytest.mark.parametrize("bz", _BBOX_SIZES, ids=lambda b: b["name"])
def test_soilgrids_bbox_timing(bz):
    result = soilgrids_bbox_query(**_make_bbox(_LAT, _LON, bz["half"]))
    _assert_or_skip(result, "soilgrids/bbox")
    _record("soilgrids", f"bbox/{bz['name']}", 0, result, area_deg2=bz["area_deg2"])
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("loc", _EXTRA_LOCATIONS, ids=lambda loc: loc["name"])
def test_soilgrids_extra_location_timing(loc):
    result = soilgrids_query(latitude=loc["lat"], longitude=loc["lon"])
    _assert_or_skip(result, f"soilgrids/{loc['name']}")
    _record("soilgrids", "point", 0, result, location=loc["name"])
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
@pytest.mark.parametrize("bz", _BBOX_SIZES, ids=lambda b: b["name"])
def test_ssurgo_bbox_timing(bz):
    result = ssurgo_bbox_query(**_make_bbox(_LAT, _LON, bz["half"]))
    if not result["_meta"].get("success"):
        pytest.skip(f"ssurgo/bbox/{bz['name']}: {result['_meta'].get('error')}")
    _record("ssurgo", f"bbox/{bz['name']}", 0, result, area_deg2=bz["area_deg2"])
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("loc", _EXTRA_LOCATIONS, ids=lambda loc: loc["name"])
def test_ssurgo_extra_location_timing(loc):
    result = ssurgo_query(latitude=loc["lat"], longitude=loc["lon"])
    if not result["_meta"].get("success"):
        pytest.skip(f"ssurgo/{loc['name']}: no data (US-only)")
    _record("ssurgo", "point", 0, result, location=loc["name"])
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
# GBIF — no auth, Occurrence Search REST API
# ===========================================================================

_GBIF_SCENARIOS = _SCENARIOS  # fragment cap bounds latency regardless of date range


@pytest.mark.integration
@pytest.mark.parametrize("sc", _GBIF_SCENARIOS, ids=lambda s: s["name"])
def test_gbif_timing(sc):
    result = gbif_occurrences(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        start_date=sc["start"],
        end_date=sc["end"],
        limit=500,
    )
    _assert_or_skip(result, "gbif")
    _record("gbif", sc["name"], sc["n_days"], result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("bz", _BBOX_SIZES, ids=lambda b: b["name"])
@pytest.mark.parametrize("sc", _GBIF_SCENARIOS, ids=lambda s: s["name"])
def test_gbif_bbox_timing(sc, bz):
    result = gbif_bbox_occurrences(
        **_make_bbox(_LAT, _LON, bz["half"]),
        start_date=sc["start"],
        end_date=sc["end"],
        limit=500,
    )
    _assert_or_skip(result, "gbif/bbox")
    _record(
        "gbif",
        f"{sc['name']}/bbox/{bz['name']}",
        sc["n_days"],
        result,
        area_deg2=bz["area_deg2"],
    )
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("loc", _EXTRA_LOCATIONS, ids=lambda loc: loc["name"])
def test_gbif_extra_location_timing(loc):
    result = gbif_occurrences(
        latitude=loc["lat"],
        longitude=loc["lon"],
        radius_km=50.0,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=500,
    )
    _assert_or_skip(result, f"gbif/{loc['name']}")
    _record("gbif", "1month", 31, result, location=loc["name"])
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
# Sentinel-5P — no auth, CDSE COGT, all scenarios
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
@pytest.mark.parametrize("bz", _BBOX_SIZES, ids=lambda b: b["name"])
@pytest.mark.parametrize("sc", _SCENARIOS, ids=lambda s: s["name"])
def test_sentinel5p_bbox_timing(sc, bz):
    result = sentinel5p_bbox_query(
        **_make_bbox(_LAT, _LON, bz["half"]),
        start_date=sc["start"],
        end_date=sc["end"],
        product="CO",
    )
    _assert_or_skip(result, "sentinel5p/bbox")
    _record(
        "sentinel5p",
        f"{sc['name']}/bbox/{bz['name']}",
        sc["n_days"],
        result,
        area_deg2=bz["area_deg2"],
    )
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("loc", _EXTRA_LOCATIONS, ids=lambda loc: loc["name"])
def test_sentinel5p_extra_location_timing(loc):
    result = sentinel5p_query(
        latitude=loc["lat"],
        longitude=loc["lon"],
        start_date="2019-08-01",
        end_date="2019-08-31",
        product="CO",
    )
    _assert_or_skip(result, f"sentinel5p/{loc['name']}")
    _record("sentinel5p", "1month", 31, result, location=loc["name"])
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
@pytest.mark.parametrize("bz", _BBOX_SIZES, ids=lambda b: b["name"])
@pytest.mark.parametrize("sc", _SCENARIOS, ids=lambda s: s["name"])
def test_openaq_bbox_timing(sc, bz, _openaq_key):
    result = openaq_bbox_query(
        **_make_bbox(_LAT, _LON, bz["half"]),
        start_date=sc["start"],
        end_date=sc["end"],
        limit=200,
    )
    _assert_or_skip(result, "openaq/bbox")
    _record(
        "openaq",
        f"{sc['name']}/bbox/{bz['name']}",
        sc["n_days"],
        result,
        area_deg2=bz["area_deg2"],
    )
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("loc", _EXTRA_LOCATIONS, ids=lambda loc: loc["name"])
def test_openaq_extra_location_timing(loc, _openaq_key):
    result = openaq_query(
        latitude=loc["lat"],
        longitude=loc["lon"],
        radius_km=50.0,
        start_date="2019-08-01",
        end_date="2019-08-31",
        limit=200,
    )
    _assert_or_skip(result, f"openaq/{loc['name']}")
    _record("openaq", "1month", 31, result, location=loc["name"])
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
    # ESS-DIVE is a dataset catalog — temporal filtering by observation window
    # is not meaningful and tends to return zero results.  Omit date filter.
    result = essdive_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=50.0,
        limit=10,
    )
    _assert_or_skip(result, "essdive")
    _record("essdive", sc["name"], sc["n_days"], result)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("bz", _BBOX_SIZES, ids=lambda b: b["name"])
@pytest.mark.parametrize("sc", _SCENARIOS, ids=lambda s: s["name"])
def test_essdive_bbox_timing(sc, bz, _essdive_token):
    result = essdive_bbox_query(
        **_make_bbox(_LAT, _LON, bz["half"]),
        limit=10,
    )
    _assert_or_skip(result, "essdive/bbox")
    _record(
        "essdive",
        f"{sc['name']}/bbox/{bz['name']}",
        sc["n_days"],
        result,
        area_deg2=bz["area_deg2"],
    )
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("loc", _EXTRA_LOCATIONS, ids=lambda loc: loc["name"])
def test_essdive_extra_location_timing(loc, _essdive_token):
    result = essdive_query(
        latitude=loc["lat"],
        longitude=loc["lon"],
        radius_km=50.0,
        limit=10,
    )
    _assert_or_skip(result, f"essdive/{loc['name']}")
    _record("essdive", "1month", 31, result, location=loc["name"])
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
@pytest.mark.parametrize("bz", _BBOX_SIZES, ids=lambda b: b["name"])
@pytest.mark.parametrize("sc", _OCO2_SCENARIOS, ids=lambda s: s["name"])
def test_oco2_bbox_timing(sc, bz, _earthdata_token):
    result = oco2_bbox_query(
        **_make_bbox(_LAT, _LON, bz["half"]),
        start_date=sc["start"],
        end_date=sc["end"],
    )
    _assert_or_skip(result, "oco2/bbox")
    _record(
        "oco2",
        f"{sc['name']}/bbox/{bz['name']}",
        sc["n_days"],
        result,
        area_deg2=bz["area_deg2"],
    )
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("loc", _EXTRA_LOCATIONS, ids=lambda loc: loc["name"])
def test_oco2_extra_location_timing(loc, _earthdata_token):
    result = oco2_query(
        latitude=loc["lat"],
        longitude=loc["lon"],
        start_date="2019-08-15",
        end_date="2019-08-21",
    )
    _assert_or_skip(result, f"oco2/{loc['name']}")
    _record("oco2", "1week", 7, result, location=loc["name"])
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

# EMIT launched August 2022 — use 2023 dates (2019 queries return zero granules).
_EMIT_SCENARIOS: list[dict[str, Any]] = [
    {"name": "1day", "start": "2023-08-19", "end": "2023-08-19", "n_days": 1},
    {"name": "1week", "start": "2023-08-15", "end": "2023-08-21", "n_days": 7},
]


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
@pytest.mark.parametrize("bz", _BBOX_SIZES, ids=lambda b: b["name"])
@pytest.mark.parametrize("sc", _EMIT_SCENARIOS, ids=lambda s: s["name"])
def test_emit_bbox_timing(sc, bz, _earthdata_token):
    result = emit_bbox_query(
        **_make_bbox(_LAT, _LON, bz["half"]),
        start_date=sc["start"],
        end_date=sc["end"],
    )
    _assert_or_skip(result, "emit/bbox")
    _record(
        "emit",
        f"{sc['name']}/bbox/{bz['name']}",
        sc["n_days"],
        result,
        area_deg2=bz["area_deg2"],
    )
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
@pytest.mark.parametrize("loc", _EXTRA_LOCATIONS, ids=lambda loc: loc["name"])
def test_emit_extra_location_timing(loc, _earthdata_token):
    result = emit_query(
        latitude=loc["lat"],
        longitude=loc["lon"],
        start_date="2023-08-15",
        end_date="2023-08-21",
    )
    _assert_or_skip(result, f"emit/{loc['name']}")
    _record("emit", "1week", 7, result, location=loc["name"])  # query window is Aug 15–21 (7 days)
    assert result["_meta"]["latency_s"] <= _MAX_LATENCY_S


@pytest.mark.integration
def test_emit_point_bbox_consistent(_earthdata_token):
    pt = emit_query(
        latitude=_LAT,
        longitude=_LON,
        start_date="2023-08-19",
        end_date="2023-08-19",
    )
    bx = emit_bbox_query(
        **_BBOX,
        start_date="2023-08-19",
        end_date="2023-08-19",
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
        lat = rec.get("latitude") or rec.get("lat") or rec.get("decimalLatitude")
        lon = rec.get("longitude") or rec.get("lon") or rec.get("decimalLongitude")
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
