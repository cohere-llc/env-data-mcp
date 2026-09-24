"""Live integration tests for the ESS-DIVE source adapter.

Marked ``@pytest.mark.integration`` - not run in CI unit-test jobs.
These tests call the real ESS-DIVE REST API at
https://api.ess-dive.lbl.gov/packages.

The tests run with or without the ``ESSDIVE_TOKEN`` environment variable set,
as the tests only query public datasets.
"""

from __future__ import annotations

from http import HTTPStatus

import httpx
import pytest

from env_data_mcp.sources.essdive import (
    essdive_bbox_query,
    essdive_point_query,
)
from env_data_mcp.sources.essdive._constants import ESSDIVE_BASE_URL

from .common import (
    AdapterSpec,
    DataExpectation,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

_ESSDIVE_HEALTH = f"{ESSDIVE_BASE_URL}packages"


@pytest.fixture(scope="module", autouse=True)
def _require_essdive_available():
    """Skip all tests if the API is unreachable."""
    try:
        r = httpx.get(
            _ESSDIVE_HEALTH,
            timeout=10,
        )
        if r.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
            pytest.skip(f"ESS-DIVE returned HTTP {r.status_code}")
    except Exception as exc:
        pytest.skip(f"ESS-DIVE not reachable: {exc}")


# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------


ESSDIVE_SPEC = AdapterSpec(
    name="essdive",
    available_variables=None,
    point_query=essdive_point_query,
    bbox_query=essdive_bbox_query,
    supports_date_range=True,
    primary_variable=None,
    default_variables=None,
    extra_point_kwargs={"radius_km": 5.0},
    longer_date_range=True,
    data_expectations={
        "sh_rural": DataExpectation(
            has_data=False,
            notes="No studies in this area.",
        ),
        "sh_midlat": DataExpectation(
            has_data=False,
            notes="No studies in this area.",
        ),
        "sh_urban": DataExpectation(
            has_data=False,
            notes="No studies in this area.",
        ),
        "sh_polar": DataExpectation(
            has_data=False,
            notes="No studies in this area.",
        ),
        "nh_urban": DataExpectation(
            has_data=False,
            notes="No studies in this area.",
        ),
        "nh_polar": DataExpectation(
            has_data=False,
            notes="No studies in this area.",
        ),
        "ocean": DataExpectation(
            has_data=False,
            notes="No studies in this area.",
        ),
        "equatorial": DataExpectation(
            has_data=False,
            notes="No studies in this area.",
        ),
    },
)
