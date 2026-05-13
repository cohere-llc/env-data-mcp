"""
Shared test fixtures and constants.

GROW_SAMPLES: first 5 rows from external-data-gallery/examples/grow_locations.txt
  (columns: SampleName | Date | Time | Latitude | Longitude)
  Dates converted from M/D/YY to ISO 8601 YYYY-MM-DD.
  Time converted to ISO 8601 HH:MM:SS (24-hour); None when the source value is NULL.

PNNL_BBOX / PNNL_START / PNNL_END: 4-corner bounding box for the PNNL
  Richland WA field monitoring site, May–June 2023.
  Source: external-data-gallery/examples/pnnl_field_locations.txt
"""

import pytest

# ---------------------------------------------------------------------------
# GROW point-sample fixtures
# ---------------------------------------------------------------------------

GROW_SAMPLES = [
    {
        "sample_name": "Yukon_2004-3",
        "date": "2004-06-15",
        "time": None,
        "latitude": 61.93333333,
        "longitude": -162.8666667,
    },
    {
        "sample_name": "Yukon_2004-1",
        "date": "2004-04-07",
        "time": None,
        "latitude": 61.93333333,
        "longitude": -162.8666667,
    },
    {
        "sample_name": "yakimariver_2019_sw_WHONDRS-S19S_0060",
        "date": "2019-08-19",
        "time": "14:30:00",
        "latitude": 46.2531882,
        "longitude": -119.4768203,
    },
    {
        "sample_name": "whiteclaycreek2_2019_sw_WHONDRS-S19S_0038",
        "date": "2019-08-12",
        "time": "16:04:00",
        "latitude": 39.8594333,
        "longitude": -75.7839486,
    },
    {
        "sample_name": "whiteclaycreek1_2019_sw_WHONDRS-S19S_0037",
        "date": "2019-08-12",
        "time": "13:32:00",
        "latitude": 39.8577967,
        "longitude": -75.7830393,
    },
]

# ---------------------------------------------------------------------------
# PNNL bounding-box fixture
# ---------------------------------------------------------------------------

PNNL_BBOX = {
    "min_lat": 46.251407,
    "max_lat": 46.251790,
    "min_lon": -119.728785,
    "max_lon": -119.728369,
}
PNNL_START = "2023-05-01"
PNNL_END = "2023-06-01"

# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def yakimariver_sample() -> dict:
    """Single GROW sample at the Yakima River, WA (2019-08-19).

    Used as the canonical point-query fixture across all source module tests.
    This site is in the US (so SSURGO coverage is expected) and has NASA POWER
    data from 1981 onward.
    """
    return GROW_SAMPLES[2]  # yakimariver_2019


@pytest.fixture
def pnnl_bbox_fixture() -> dict:
    """PNNL bounding-box fixture with start/end dates."""
    return {
        "bbox": PNNL_BBOX,
        "start_date": PNNL_START,
        "end_date": PNNL_END,
    }
