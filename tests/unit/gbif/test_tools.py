"""Unit tests for the GBIF tools module.

All query functions are mocked via a ``unittest.mock.patch``; no network access required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx

from env_data_mcp.sources.gbif.constants import _QueryType
from env_data_mcp.sources.gbif.tools import (
    gbif_occurrence_available_variables,
    gbif_occurrence_bbox_query,
    gbif_occurrence_query,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_YAKIMA_LAT = 46.2531882
_YAKIMA_LON = -119.4768203
_MIN_LAT = 46.2
_MAX_LAT = 46.3
_MIN_LON = -119.5
_MAX_LON = -119.4
_START_DATE = "2019-08-01"
_END_DATE = "2019-08-31"

_EXPECTED_VARIABLES: dict[str, dict[str, str]] = {
    "key": {"description": "GBIF key", "units": ""},
    "species": {"description": "species name", "units": ""},
    "decimalLatitude": {"description": "latitude in decimal degrees", "units": "degrees"},
    "decimalLongitude": {"description": "longitude in decimal degrees", "units": "degrees"},
    "eventDate": {"description": "occurrence date", "units": ""},
    "taxonKey": {"description": "taxon ID", "units": ""},
    "license": {"description": "license information", "units": ""},
}

_EXPECTED_QUERY_OUTPUT: list[dict[str, Any]] = [
    {
        "geometry": {
            "type": "Point",
            "coordinates": [-119.48, 46.26],
        },
        "latitude": 46.26,
        "longitude": -119.48,
        "records": [
            {
                "key": 1111111111,
                "species": "Salix exigua",
                "decimalLatitude": 46.26,
                "decimalLongitude": -119.48,
                "eventDate": "2019-08-15",
                "taxonKey": 2881663,
                "license": "http://creativecommons.org/licenses/by/4.0/legalcode",
            }
        ],
    },
    {
        "geometry": {
            "type": "Point",
            "coordinates": [-119.49, 46.27],
        },
        "latitude": 46.27,
        "longitude": -119.49,
        "records": [
            {
                "key": 2222222222,
                "species": "Populus trichocarpa",
                "decimalLatitude": 46.27,
                "decimalLongitude": -119.49,
                "eventDate": "2019-08-19",
                "taxonKey": 3040740,
                "license": "http://creativecommons.org/publicdomain/zero/1.0/legalcode",
            }
        ],
    },
]

_EXPECTED_UNIQUE_LICENSES: list[str] = [
    "http://creativecommons.org/licenses/by/4.0/legalcode",
    "http://creativecommons.org/publicdomain/zero/1.0/legalcode",
]


def get_mock_http_error():
    request = httpx.Request("GET", "https://api.gbif.org/v1/occurrence/search")
    response = httpx.Response(503, request=request)
    return httpx.HTTPStatusError(
        "503 Service Unavailable",
        request=request,
        response=response,
    )


def _make_mock_query_point(*, expected_taxon_key: int | None = None, number_of_results: int = 2):
    def mock_query_point(
        lat: float,
        lon: float,
        start_date: str,
        end_date: str,
        query_type: _QueryType,
        radius_km: float,
        taxon_key: int | None,
        variables: list[str],
        limit: int | None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        assert lat == _YAKIMA_LAT
        assert lon == _YAKIMA_LON
        assert start_date == _START_DATE
        assert end_date == _END_DATE
        assert query_type == _QueryType.OCCURRENCE
        assert radius_km == 5.0
        if expected_taxon_key:
            assert taxon_key == expected_taxon_key
        else:
            assert taxon_key is None
        assert len(variables) > 0
        return _EXPECTED_QUERY_OUTPUT[:number_of_results], _EXPECTED_UNIQUE_LICENSES[
            :number_of_results
        ]

    return mock_query_point


def _make_mock_query_bbox(*, expected_taxon_key: int | None = None, number_of_results: int = 2):
    def mock_query_point(
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        start_date: str,
        end_date: str,
        query_type: _QueryType,
        taxon_key: int | None,
        variables: list[str],
        limit: int | None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        assert min_lat == _MIN_LAT
        assert max_lat == _MAX_LAT
        assert min_lon == _MIN_LON
        assert max_lon == _MAX_LON
        assert start_date == _START_DATE
        assert end_date == _END_DATE
        assert query_type == _QueryType.OCCURRENCE
        if expected_taxon_key:
            assert taxon_key == expected_taxon_key
        else:
            assert taxon_key is None
        assert len(variables) > 0
        return _EXPECTED_QUERY_OUTPUT[:number_of_results], _EXPECTED_UNIQUE_LICENSES[
            :number_of_results
        ]

    return mock_query_point


# ---------------------------------------------------------------------------
# Available variables
# ---------------------------------------------------------------------------


class TestAvailableVariables:
    """Tests of the gbif_*_available_variables mcp tool"""

    def test_returns_results(self):
        with patch(
            "env_data_mcp.sources.gbif.tools._get_variable_info", return_value=_EXPECTED_VARIABLES
        ):
            results = gbif_occurrence_available_variables()
        assert "data" in results
        assert len(results["data"]) == 7
        assert results["data"] == _EXPECTED_VARIABLES
        assert "_meta" in results
        assert "success" in results["_meta"]
        assert results["_meta"]["success"]
        assert results["_meta"]["geometries_returned"] == 0
        assert results["_meta"]["total_records_returned"] == 7

    def test_returns_error(self):
        with patch(
            "env_data_mcp.sources.gbif.tools._get_variable_info", side_effect=get_mock_http_error()
        ):
            results = gbif_occurrence_available_variables()
        assert "data" in results
        assert results["data"] == {}
        assert "_meta" in results
        assert "success" in results["_meta"]
        assert not results["_meta"]["success"]
        assert "error" in results["_meta"]
        assert "503" in results["_meta"]["error"]


# ---------------------------------------------------------------------------
# Point query
# ---------------------------------------------------------------------------


class TestQuery:
    """Tests gbif_*_query mcp tools."""

    def test_returns_results(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                return_value=_EXPECTED_VARIABLES,
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_point",
                side_effect=_make_mock_query_point(),
            ),
        ):
            results = gbif_occurrence_query(
                latitude=_YAKIMA_LAT,
                longitude=_YAKIMA_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
                radius_km=5.0,
            )

        assert "data" in results
        assert results["data"] == _EXPECTED_QUERY_OUTPUT
        assert "_meta" in results
        assert "success" in results["_meta"]
        assert results["_meta"]["geometries_returned"] == 2
        assert results["_meta"]["total_records_returned"] == 2
        assert "license" in results["_meta"]
        assert _EXPECTED_UNIQUE_LICENSES[0] in results["_meta"]["license"]
        assert _EXPECTED_UNIQUE_LICENSES[1] in results["_meta"]["license"]
        assert "unavailable_variables" in results["_meta"]
        # our mocked default response does not include all the actual available variables
        # the missing ones should show up in "unavailable_variables"
        assert "taxonRank" in results["_meta"]["unavailable_variables"]
        assert "issues" in results["_meta"]["unavailable_variables"]

    def test_handles_get_variable_info_error(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                side_effect=get_mock_http_error(),
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_point",
                side_effect=_make_mock_query_point(),
            ),
        ):
            results = gbif_occurrence_query(
                latitude=_YAKIMA_LAT,
                longitude=_YAKIMA_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
                radius_km=5.0,
            )

        assert "data" in results
        assert results["data"] == []
        assert "_meta" in results
        assert not results["_meta"]["success"]
        assert "error" in results["_meta"]
        assert "503" in results["_meta"]["error"]

    def test_handles_query_point_error(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                return_value=_EXPECTED_VARIABLES,
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_point",
                side_effect=get_mock_http_error(),
            ),
        ):
            results = gbif_occurrence_query(
                latitude=_YAKIMA_LAT,
                longitude=_YAKIMA_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
                radius_km=5.0,
            )

        assert "data" in results
        assert results["data"] == []
        assert "_meta" in results
        assert not results["_meta"]["success"]
        assert "error" in results["_meta"]
        assert "503" in results["_meta"]["error"]

    def test_returns_warning_for_long_query(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                return_value=_EXPECTED_VARIABLES,
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_point",
                side_effect=_make_mock_query_point(),
            ),
        ):
            results = gbif_occurrence_query(
                latitude=_YAKIMA_LAT,
                longitude=_YAKIMA_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
                radius_km=5.0,
                max_runtime_s=0.0001,
            )

        assert "data" in results
        assert results["data"] == []
        assert "_meta" in results
        assert "success" in results["_meta"]
        assert not results["_meta"]["success"]
        assert "message" in results["_meta"]
        assert "exceeds" in results["_meta"]["message"]

    def test_returns_results_for_taxon_id(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                return_value=_EXPECTED_VARIABLES,
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_point",
                side_effect=_make_mock_query_point(expected_taxon_key=2881663, number_of_results=1),
            ),
        ):
            results = gbif_occurrence_query(
                latitude=_YAKIMA_LAT,
                longitude=_YAKIMA_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
                radius_km=5.0,
                taxon_key=2881663,
            )

        assert "data" in results
        assert results["data"] == _EXPECTED_QUERY_OUTPUT[:1]
        assert "_meta" in results
        assert "success" in results["_meta"]
        assert results["_meta"]["geometries_returned"] == 1
        assert results["_meta"]["total_records_returned"] == 1
        assert "license" in results["_meta"]
        assert _EXPECTED_UNIQUE_LICENSES[0] in results["_meta"]["license"]
        assert "unavailable_variables" in results["_meta"]
        # our mocked default response does not include all the actual available variables
        # the missing ones should show up in "unavailable_variables"
        assert "taxonRank" in results["_meta"]["unavailable_variables"]
        assert "issues" in results["_meta"]["unavailable_variables"]

    def test_returns_empty_for_all_unknown_variables(self):
        with patch(
            "env_data_mcp.sources.gbif.tools._get_variable_info",
            return_value=_EXPECTED_VARIABLES,
        ):
            results = gbif_occurrence_query(
                latitude=_YAKIMA_LAT,
                longitude=_YAKIMA_LON,
                start_date=_START_DATE,
                end_date=_END_DATE,
                variables=["not_a_real_variable", "also_fake"],
            )

        assert results["data"] == []
        assert "_meta" in results
        assert results["_meta"]["success"] is True
        assert results["_meta"]["geometries_returned"] == 0
        assert results["_meta"]["total_records_returned"] == 0
        assert "unavailable_variables" in results["_meta"]
        assert "not_a_real_variable" in results["_meta"]["unavailable_variables"]
        assert "also_fake" in results["_meta"]["unavailable_variables"]


# ---------------------------------------------------------------------------
# Bbox query
# ---------------------------------------------------------------------------


class TestBboxQuery:
    """Tests gbif_*_bbox_query mcp tools."""

    def test_returns_results(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                return_value=_EXPECTED_VARIABLES,
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_bbox",
                side_effect=_make_mock_query_bbox(),
            ),
        ):
            results = gbif_occurrence_bbox_query(
                min_lat=_MIN_LAT,
                max_lat=_MAX_LAT,
                min_lon=_MIN_LON,
                max_lon=_MAX_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
            )

        assert "data" in results
        assert results["data"] == _EXPECTED_QUERY_OUTPUT
        assert "_meta" in results
        assert "success" in results["_meta"]
        assert results["_meta"]["geometries_returned"] == 2
        assert results["_meta"]["total_records_returned"] == 2
        assert "license" in results["_meta"]
        assert _EXPECTED_UNIQUE_LICENSES[0] in results["_meta"]["license"]
        assert _EXPECTED_UNIQUE_LICENSES[1] in results["_meta"]["license"]
        assert "unavailable_variables" in results["_meta"]
        # our mocked default response does not include all the actual available variables
        # the missing ones should show up in "unavailable_variables"
        assert "taxonRank" in results["_meta"]["unavailable_variables"]
        assert "issues" in results["_meta"]["unavailable_variables"]

    def test_handles_get_variable_info_error(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                side_effect=get_mock_http_error(),
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_bbox",
                side_effect=_make_mock_query_bbox(),
            ),
        ):
            results = gbif_occurrence_bbox_query(
                min_lat=_MIN_LAT,
                max_lat=_MAX_LAT,
                min_lon=_MIN_LON,
                max_lon=_MAX_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
            )

        assert "data" in results
        assert results["data"] == []
        assert "_meta" in results
        assert not results["_meta"]["success"]
        assert "error" in results["_meta"]
        assert "503" in results["_meta"]["error"]

    def test_handles_query_point_error(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                return_value=_EXPECTED_VARIABLES,
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_bbox",
                side_effect=get_mock_http_error(),
            ),
        ):
            results = gbif_occurrence_bbox_query(
                min_lat=_MIN_LAT,
                max_lat=_MAX_LAT,
                min_lon=_MIN_LON,
                max_lon=_MAX_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
            )

        assert "data" in results
        assert results["data"] == []
        assert "_meta" in results
        assert not results["_meta"]["success"]
        assert "error" in results["_meta"]
        assert "503" in results["_meta"]["error"]

    def test_returns_warning_for_long_query(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                return_value=_EXPECTED_VARIABLES,
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_bbox",
                side_effect=_make_mock_query_bbox(),
            ),
        ):
            results = gbif_occurrence_bbox_query(
                min_lat=_MIN_LAT,
                max_lat=_MAX_LAT,
                min_lon=_MIN_LON,
                max_lon=_MAX_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
                max_runtime_s=0.0001,
            )

        assert "data" in results
        assert results["data"] == []
        assert "_meta" in results
        assert "success" in results["_meta"]
        assert not results["_meta"]["success"]
        assert "message" in results["_meta"]
        assert "exceeds" in results["_meta"]["message"]

    def test_returns_results_for_taxon_id(self):
        with (
            patch(
                "env_data_mcp.sources.gbif.tools._get_variable_info",
                return_value=_EXPECTED_VARIABLES,
            ),
            patch(
                "env_data_mcp.sources.gbif.tools._query_bbox",
                side_effect=_make_mock_query_bbox(expected_taxon_key=2881663, number_of_results=1),
            ),
        ):
            results = gbif_occurrence_bbox_query(
                min_lat=_MIN_LAT,
                max_lat=_MAX_LAT,
                min_lon=_MIN_LON,
                max_lon=_MAX_LON,
                start_date="2019-08-01",
                end_date="2019-08-31",
                taxon_key=2881663,
            )

        assert "data" in results
        assert results["data"] == _EXPECTED_QUERY_OUTPUT[:1]
        assert "_meta" in results
        assert "success" in results["_meta"]
        assert results["_meta"]["geometries_returned"] == 1
        assert results["_meta"]["total_records_returned"] == 1
        assert "license" in results["_meta"]
        assert _EXPECTED_UNIQUE_LICENSES[0] in results["_meta"]["license"]
        assert "unavailable_variables" in results["_meta"]
        # our mocked default response does not include all the actual available variables
        # the missing ones should show up in "unavailable_variables"
        assert "taxonRank" in results["_meta"]["unavailable_variables"]
        assert "issues" in results["_meta"]["unavailable_variables"]

    def test_returns_empty_for_all_unknown_variables(self):
        with patch(
            "env_data_mcp.sources.gbif.tools._get_variable_info",
            return_value=_EXPECTED_VARIABLES,
        ):
            results = gbif_occurrence_bbox_query(
                min_lat=_MIN_LAT,
                max_lat=_MAX_LAT,
                min_lon=_MIN_LON,
                max_lon=_MAX_LON,
                start_date=_START_DATE,
                end_date=_END_DATE,
                variables=["not_a_real_variable", "also_fake"],
            )

        assert results["data"] == []
        assert "_meta" in results
        assert results["_meta"]["success"] is True
        assert results["_meta"]["geometries_returned"] == 0
        assert results["_meta"]["total_records_returned"] == 0
        assert "unavailable_variables" in results["_meta"]
        assert "not_a_real_variable" in results["_meta"]["unavailable_variables"]
        assert "also_fake" in results["_meta"]["unavailable_variables"]
