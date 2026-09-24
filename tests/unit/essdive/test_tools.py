"""Unit tests for the ESS-DIVE _query module.

All HTTP calls are mocked via ``pytest-httpx``; no network access required.
"""

from __future__ import annotations

import pytest

from env_data_mcp.sources.essdive.tools import (
    _get_api_key,
    essdive_bbox_query,
    essdive_point_query,
)

from .conftest import (
    _API_KEY,
    _LAT,
    _LON,
)

# ---------------------------------------------------------------------------
# _get_api_key
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_set_api_key")
def test_get_api_key_available():
    key = _get_api_key()
    assert key is not None
    assert key == _API_KEY


@pytest.mark.usefixtures("_unset_api_key")
def test_get_api_key_unavailable():
    key = _get_api_key()
    assert key is None


# ---------------------------------------------------------------------------
# essdive_point_query
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_packages_mock", "_set_api_key")
def test_essdive_point_query():
    result = essdive_point_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=5.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
        keywords=["peatland"],
    )
    # 4 geometry groups: 1 bbox (dataset.spatialCoverage); 2 bboxes (top-level
    # spatialCoverage); 1 default point (dataset with no spatial coverage).
    assert len(result["data"]) == 4
    assert result["_meta"]["geometries_returned"] == 4
    # One record per geometry
    assert result["_meta"]["total_records_returned"] == 4

    bbox_group = result["data"][0]
    assert bbox_group["geometry"]["type"] == "Polygon"
    record = bbox_group["records"][0]
    assert record["id"] == "ess-dive-b4ce9be3ed3df82-20260825T125458917"
    assert record["citation"] == (
        "McPartland M Y; Falkowski M J; Reinhardt J R; Kane E S; Kolka R K"
    )
    assert record["license"] == "http://creativecommons.org/licenses/by/4.0/"
    assert record["variables"] == ["reflectance"]
    assert len(record["techniques"]) == 2
    assert len(record["files"]) == 2
    assert record["files"][0]["name"] == "unispec_dataframe.csv"

    # The last package has no spatial coverage listed, so it uses
    # the requested point geometry.
    default_group = result["data"][-1]
    assert default_group["geometry"]["type"] == "Point"
    assert default_group["geometry"]["coordinates"] == [_LON, _LAT]
    assert default_group["records"][0]["files"] == []

    assert result["_meta"]["source"] == "ess-dive"
    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is False
    assert result["_meta"]["auth_present"] is True


@pytest.mark.usefixtures("_packages_mock", "_unset_api_key")
def test_essdive_point_query_no_api_key():
    # ESS-DIVE API keys are optional; omitting one should still succeed and
    # simply restrict results to public datasets.
    result = essdive_point_query(
        latitude=_LAT,
        longitude=_LON,
        radius_km=5.0,
    )
    assert len(result["data"]) == 4
    assert result["_meta"]["success"] is True
    assert result["_meta"]["error"] is None
    assert result["_meta"]["auth_required"] is False
    assert result["_meta"]["auth_present"] is True


@pytest.mark.usefixtures("_set_api_key")
def test_essdive_point_query_invalid_coordinates():
    # Validation fails before any HTTP call is made.
    result = essdive_point_query(
        latitude=200.0,
        longitude=_LON,
        radius_km=5.0,
    )
    assert result["data"] == []
    assert result["_meta"]["success"] is False
    assert result["_meta"]["geometries_returned"] == 0
    assert result["_meta"]["total_records_returned"] == 0
    assert result["_meta"]["error"] is not None
    assert result["_meta"]["query_params"]["latitude"] == 200.0


# ---------------------------------------------------------------------------
# essdive_point_query
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_packages_mock", "_set_api_key")
def test_essdive_bbox_query():
    result = essdive_bbox_query(
        min_lat=_LAT,
        max_lat=_LAT + 1.0,
        min_lon=_LON,
        max_lon=_LON + 1.0,
        start_date="2019-08-19",
        end_date="2019-08-19",
        keywords=["peatland"],
    )
    # 4 geometry groups: 1 bbox (dataset.spatialCoverage); 2 bboxes (top-level
    # spatialCoverage); 1 default bbox (dataset with no spatial coverage).
    assert len(result["data"]) == 4
    assert result["_meta"]["geometries_returned"] == 4
    # One record per geometry
    assert result["_meta"]["total_records_returned"] == 4

    bbox_group = result["data"][0]
    assert bbox_group["geometry"]["type"] == "Polygon"
    record = bbox_group["records"][0]
    assert record["id"] == "ess-dive-b4ce9be3ed3df82-20260825T125458917"
    assert record["citation"] == (
        "McPartland M Y; Falkowski M J; Reinhardt J R; Kane E S; Kolka R K"
    )
    assert record["license"] == "http://creativecommons.org/licenses/by/4.0/"
    assert record["variables"] == ["reflectance"]
    assert len(record["techniques"]) == 2
    assert len(record["files"]) == 2
    assert record["files"][0]["name"] == "unispec_dataframe.csv"

    # The last package has no spatial coverage listed, so it uses
    # the requested bbox geometry.
    default_group = result["data"][-1]
    assert default_group["geometry"]["type"] == "Polygon"
    assert default_group["geometry"]["coordinates"] == [
        [_LON, _LAT],
        [_LON + 1.0, _LAT],
        [_LON + 1.0, _LAT + 1.0],
        [_LON, _LAT + 1.0],
        [_LON, _LAT],
    ]
    assert default_group["records"][0]["files"] == []

    assert result["_meta"]["source"] == "ess-dive"
    assert result["_meta"]["success"] is True
    assert result["_meta"]["auth_required"] is False
    assert result["_meta"]["auth_present"] is True


@pytest.mark.usefixtures("_packages_mock", "_unset_api_key")
def test_essdive_bbox_query_no_api_key():
    # ESS-DIVE API keys are optional; omitting one should still succeed and
    # simply restrict results to public datasets.
    result = essdive_bbox_query(
        min_lat=_LAT,
        max_lat=_LAT + 1.0,
        min_lon=_LON,
        max_lon=_LON + 1.0,
    )
    assert len(result["data"]) == 4
    assert result["_meta"]["success"] is True
    assert result["_meta"]["error"] is None
    assert result["_meta"]["auth_required"] is False
    assert result["_meta"]["auth_present"] is True


@pytest.mark.usefixtures("_set_api_key")
def test_essdive_bbox_query_invalid_coordinates():
    # Validation fails before any HTTP call is made.
    result = essdive_bbox_query(
        min_lat=_LAT,
        max_lat=_LAT + 1.0,
        min_lon=200.0,
        max_lon=_LON + 1.0,
    )
    assert result["data"] == []
    assert result["_meta"]["success"] is False
    assert result["_meta"]["geometries_returned"] == 0
    assert result["_meta"]["total_records_returned"] == 0
    assert result["_meta"]["error"] is not None
    assert result["_meta"]["query_params"]["min_lon"] == 200.0
