"""Unit tests for src/env_data_mcp/timing_model.json.

The CI staleness check ensures the committed timing model does not become
silently outdated.  It is intentionally not marked @pytest.mark.integration
so it runs in every CI pipeline without network access.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pytest

_TIMING_MODEL_PATH = Path(__file__).parents[2] / "src" / "env_data_mcp" / "timing_model.json"

# Warn if the model is older than this many days; fail hard after twice as long.
_WARN_DAYS = 30
_FAIL_DAYS = 90


def _load_model() -> dict:
    assert _TIMING_MODEL_PATH.exists(), (
        f"timing_model.json not found at {_TIMING_MODEL_PATH}. "
        "Run: uv run pytest tests/integration/test_benchmarks.py -m integration"
    )
    return json.loads(_TIMING_MODEL_PATH.read_text())


def test_timing_model_exists_and_parseable():
    """timing_model.json must exist and be valid JSON with the expected keys."""
    data = _load_model()
    assert "generated_at" in data, "Missing 'generated_at' key"
    assert "model" in data, "Missing 'model' key"
    assert "raw" in data, "Missing 'raw' key"


def test_timing_model_not_too_old():
    """Emit a warning when the model is stale; fail hard if extremely stale.

    This is intentionally a *warning* for the first threshold so that the
    benchmark only needs to be re-run periodically, not on every PR.
    """
    data = _load_model()
    generated_at_str = data["generated_at"]

    # The seed file uses "2000-01-01T00:00:00+00:00" as a sentinel — skip the
    # staleness check for the placeholder until the benchmark has been run once.
    if generated_at_str.startswith("2000-01-01"):
        pytest.skip(
            "timing_model.json contains the seed placeholder. "
            "Run: uv run pytest tests/integration/test_benchmarks.py -m integration"
        )

    generated_at = datetime.fromisoformat(generated_at_str)
    age_days = (datetime.now(UTC) - generated_at).days

    if age_days > _FAIL_DAYS:
        pytest.fail(
            f"timing_model.json is {age_days} days old (threshold: {_FAIL_DAYS} days). "
            "Regenerate: uv run pytest tests/integration/test_benchmarks.py -m integration"
        )
    elif age_days > _WARN_DAYS:
        warnings.warn(
            f"timing_model.json is {age_days} days old (threshold: {_WARN_DAYS} days). "
            "Regenerate: uv run pytest tests/integration/test_benchmarks.py -m integration",
            UserWarning,
            stacklevel=1,
        )


def test_timing_model_schema():
    """Each entry in 'model' must have the expected numeric fields."""
    data = _load_model()
    # The seed file has an empty model dict — skip schema validation.
    if not data["model"]:
        pytest.skip("timing_model.json has no fitted model entries yet (seed placeholder)")

    for source, entry in data["model"].items():
        assert "alpha" in entry, f"{source}: missing 'alpha'"
        assert "beta_n_days" in entry, f"{source}: missing 'beta_n_days'"
        assert "equation" in entry, f"{source}: missing 'equation'"
        if entry["alpha"] is not None:
            assert entry["alpha"] >= 0, f"{source}: alpha should be non-negative"
