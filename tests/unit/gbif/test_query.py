"""Unit tests for the GBIF _query module.

All HTTP calls are mocked via a ``unittest.mock.patch``; no network access required.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from env_data_mcp.sources.gbif._query import (
    _estimate_query_runtime_s,
    _get_variable_info,
    _query_bbox,
    _query_point,
)
from env_data_mcp.sources.gbif.constants import _QUERY_ENDPOINTS, _QueryType

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_YAKIMA_LAT = 46.2531882
_YAKIMA_LON = -119.4768203

# Records using the camelCase field names returned by the GBIF REST API.
_SAMPLE_API_RECORDS: list[dict[str, Any]] = [
    {
        "key": 1111111111,
        "species": "Salix exigua",
        "decimalLatitude": 46.26,
        "decimalLongitude": -119.48,
        "eventDate": "2019-08-15",
        "taxonKey": 2881663,
        "license": "http://creativecommons.org/licenses/by/4.0/legalcode",
    },
    {
        "key": 2222222222,
        "species": "Populus trichocarpa",
        "decimalLatitude": 46.27,
        "decimalLongitude": -119.49,
        "eventDate": "2019-08-19",
        "taxonKey": 3040740,
        "license": "http://creativecommons.org/publicdomain/zero/1.0/legalcode",
    },
]

# Expected output from query functions for mock server response
_EXPECTED_QUERY_OUTPUT: list[dict[str, Any]] = [
    {
        "geometry": {
            "type": "Point",
            "coordinates": [-119.48, 46.26],
        },
        "latitude": 46.26,
        "longitude": -119.48,
        "records": [_SAMPLE_API_RECORDS[0]],
    },
    {
        "geometry": {
            "type": "Point",
            "coordinates": [-119.49, 46.27],
        },
        "latitude": 46.27,
        "longitude": -119.49,
        "records": [_SAMPLE_API_RECORDS[1]],
    },
]

_SCHEMA_ENDPOINT = "https://techdocs.gbif.org/openapi/occurrence.json"

_OCCURRENCE_RESPONSE = {
    "components": {
        "schemas": {
            "Occurrence": {
                "properties": {
                    "foo": {"description": "fooness"},
                    "bar": {"description": "baricity"},
                }
            }
        }
    }
}


def _make_mock_response(
    results: list[dict[str, Any]],
    count: int,
    end_of_records: bool = True,
) -> httpx.Response:
    """Return an httpx.Response with a GBIF-style JSON body."""
    return httpx.Response(
        200,
        json={"count": count, "endOfRecords": end_of_records, "results": results},
    )


def _make_mock_get(
    *,
    expected_taxon_key: int | None = None,
    number_of_results: int = 2,
) -> Callable[[httpx.Request], httpx.Response]:
    def callback(request: httpx.Request) -> httpx.Response:
        base_url = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        assert base_url == _QUERY_ENDPOINTS[_QueryType.OCCURRENCE]
        params = dict(request.url.params)
        lats = params["decimalLatitude"].split(",")
        assert len(lats) == 2
        assert float(lats[0]) == pytest.approx(46.2, rel=0.01)
        assert float(lats[1]) == pytest.approx(46.3, rel=0.01)
        lons = params["decimalLongitude"].split(",")
        assert len(lons) == 2
        assert float(lons[0]) == pytest.approx(-119.5, rel=0.01)
        assert float(lons[1]) == pytest.approx(-119.4, rel=0.01)
        assert params["eventDate"] == "2019-08-01,2019-08-31"
        if expected_taxon_key:
            assert params["taxonKey"] == str(expected_taxon_key)
        assert int(params["limit"]) > 0
        assert int(params["offset"]) == 0

        return _make_mock_response(
            results=_SAMPLE_API_RECORDS[:number_of_results],
            count=number_of_results,
            end_of_records=True,
        )

    return callback


# ---------------------------------------------------------------------------
# _get_variable_info
# ---------------------------------------------------------------------------


@patch("env_data_mcp.sources.gbif._query._VARIABLE_INFO_CACHE", {})
def test_get_variable_info(httpx_mock):
    httpx_mock.add_response(url=_SCHEMA_ENDPOINT, json=_OCCURRENCE_RESPONSE)

    var_info = _get_variable_info(_QueryType.OCCURRENCE)
    var_info_2 = _get_variable_info(_QueryType.OCCURRENCE)

    assert var_info == var_info_2
    assert len(var_info.items()) == 2
    assert "foo" in var_info
    assert "bar" in var_info
    assert var_info["foo"]["description"] == "fooness"
    assert var_info["foo"]["units"] == ""
    assert var_info["bar"]["description"] == "baricity"
    assert var_info["bar"]["units"] == ""


@patch("env_data_mcp.sources.gbif._query._VARIABLE_INFO_CACHE", {})
def test_get_variable_info_raises_for_status(httpx_mock):
    httpx_mock.add_response(url=_SCHEMA_ENDPOINT, status_code=404)

    with pytest.raises(httpx.HTTPStatusError):
        _ = _get_variable_info(_QueryType.OCCURRENCE)


# ---------------------------------------------------------------------------
# _query_point
# ---------------------------------------------------------------------------


class TestQueryPoint:
    """Tests of the GBIF _query_point() function"""

    def test_returns_records(self, httpx_mock):
        httpx_mock.add_callback(_make_mock_get())
        results, unique_licenses = _query_point(
            lat=_YAKIMA_LAT,
            lon=_YAKIMA_LON,
            start_date="2019-08-01",
            end_date="2019-08-31",
            query_type=_QueryType.OCCURRENCE,
            radius_km=5.0,
            taxon_key=None,
            variables=[
                "key",
                "species",
                "decimalLatitude",
                "decimalLongitude",
                "eventDate",
                "taxonKey",
                "license",
            ],
            limit=None,
        )
        assert results == _EXPECTED_QUERY_OUTPUT
        assert len(unique_licenses) == 2
        assert "http://creativecommons.org/licenses/by/4.0/legalcode" in unique_licenses
        assert "http://creativecommons.org/publicdomain/zero/1.0/legalcode" in unique_licenses

    def test_returns_results_with_taxon_key(self, httpx_mock):
        httpx_mock.add_callback(_make_mock_get(expected_taxon_key=2881663, number_of_results=1))
        results, unique_licenses = _query_point(
            lat=_YAKIMA_LAT,
            lon=_YAKIMA_LON,
            start_date="2019-08-01",
            end_date="2019-08-31",
            query_type=_QueryType.OCCURRENCE,
            radius_km=5.0,
            taxon_key=2881663,
            variables=[
                "key",
                "species",
                "decimalLatitude",
                "decimalLongitude",
                "eventDate",
                "taxonKey",
                "license",
            ],
            limit=2,
        )
        assert results == _EXPECTED_QUERY_OUTPUT[:1]
        assert len(unique_licenses) == 1
        assert "http://creativecommons.org/licenses/by/4.0/legalcode" in unique_licenses

    def test_paginates_until_limit(self, httpx_mock):
        extra_record = {**_SAMPLE_API_RECORDS[0], "key": 3333}
        extra_result = {**_EXPECTED_QUERY_OUTPUT[0], "records": [extra_record]}
        httpx_mock.add_response(
            method="GET",
            url=_QUERY_ENDPOINTS[_QueryType.OCCURRENCE],
            json={"count": 2, "endOfRecords": False, "results": _SAMPLE_API_RECORDS},
        )
        httpx_mock.add_response(
            method="GET",
            url=_QUERY_ENDPOINTS[_QueryType.OCCURRENCE],
            json={"count": 1, "endOfRecords": False, "results": [extra_record]},
        )
        results, unique_licenses = _query_point(
            lat=_YAKIMA_LAT,
            lon=_YAKIMA_LON,
            start_date="2019-08-01",
            end_date="2019-08-31",
            query_type=_QueryType.OCCURRENCE,
            radius_km=5.0,
            taxon_key=None,
            variables=[
                "key",
                "species",
                "decimalLatitude",
                "decimalLongitude",
                "eventDate",
                "taxonKey",
                "license",
            ],
            limit=3,
        )
        assert len(results) == 3
        assert results == [*_EXPECTED_QUERY_OUTPUT, extra_result]
        assert len(unique_licenses) == 2
        assert "http://creativecommons.org/licenses/by/4.0/legalcode" in unique_licenses
        assert "http://creativecommons.org/publicdomain/zero/1.0/legalcode" in unique_licenses

    def test_returns_limited_results(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=_QUERY_ENDPOINTS[_QueryType.OCCURRENCE],
            json={"count": 2, "endOfRecords": False, "results": _SAMPLE_API_RECORDS},
        )
        results, unique_licenses = _query_point(
            lat=_YAKIMA_LAT,
            lon=_YAKIMA_LON,
            start_date="2019-08-01",
            end_date="2019-08-31",
            query_type=_QueryType.OCCURRENCE,
            radius_km=5.0,
            taxon_key=None,
            variables=[
                "key",
                "species",
                "decimalLatitude",
                "decimalLongitude",
                "eventDate",
                "taxonKey",
                "license",
            ],
            limit=2,
        )
        assert len(results) == 2
        assert results == _EXPECTED_QUERY_OUTPUT
        assert len(unique_licenses) == 2
        assert "http://creativecommons.org/licenses/by/4.0/legalcode" in unique_licenses
        assert "http://creativecommons.org/publicdomain/zero/1.0/legalcode" in unique_licenses


# ---------------------------------------------------------------------------
# _query_bbox
# ---------------------------------------------------------------------------


class TestQueryBbox:
    """Tests of the GBIF _query_bbox() function"""

    def test_returns_records(self, httpx_mock):
        httpx_mock.add_callback(_make_mock_get())
        results, unique_licenses = _query_bbox(
            min_lat=46.2,
            max_lat=46.3,
            min_lon=-119.5,
            max_lon=-119.4,
            start_date="2019-08-01",
            end_date="2019-08-31",
            query_type=_QueryType.OCCURRENCE,
            taxon_key=None,
            variables=[
                "key",
                "species",
                "decimalLatitude",
                "decimalLongitude",
                "eventDate",
                "taxonKey",
                "license",
            ],
            limit=None,
        )
        assert results == _EXPECTED_QUERY_OUTPUT
        assert len(unique_licenses) == 2
        assert "http://creativecommons.org/licenses/by/4.0/legalcode" in unique_licenses
        assert "http://creativecommons.org/publicdomain/zero/1.0/legalcode" in unique_licenses

    def test_returns_results_with_taxon_key(self, httpx_mock):
        httpx_mock.add_callback(_make_mock_get(expected_taxon_key=2881663, number_of_results=1))
        results, unique_licenses = _query_bbox(
            min_lat=46.2,
            max_lat=46.3,
            min_lon=-119.5,
            max_lon=-119.4,
            start_date="2019-08-01",
            end_date="2019-08-31",
            query_type=_QueryType.OCCURRENCE,
            taxon_key=2881663,
            variables=[
                "key",
                "species",
                "decimalLatitude",
                "decimalLongitude",
                "eventDate",
                "taxonKey",
                "license",
            ],
            limit=2,
        )
        assert results == _EXPECTED_QUERY_OUTPUT[:1]
        assert len(unique_licenses) == 1
        assert "http://creativecommons.org/licenses/by/4.0/legalcode" in unique_licenses

    def test_paginates_until_limit(self, httpx_mock):
        extra_record = {**_SAMPLE_API_RECORDS[0], "key": 3333}
        extra_result = {**_EXPECTED_QUERY_OUTPUT[0], "records": [extra_record]}
        httpx_mock.add_response(
            method="GET",
            url=_QUERY_ENDPOINTS[_QueryType.OCCURRENCE],
            json={"count": 2, "endOfRecords": False, "results": _SAMPLE_API_RECORDS},
        )
        httpx_mock.add_response(
            method="GET",
            url=_QUERY_ENDPOINTS[_QueryType.OCCURRENCE],
            json={"count": 1, "endOfRecords": False, "results": [extra_record]},
        )
        results, unique_licenses = _query_bbox(
            min_lat=46.2,
            max_lat=46.3,
            min_lon=-119.5,
            max_lon=-119.4,
            start_date="2019-08-01",
            end_date="2019-08-31",
            query_type=_QueryType.OCCURRENCE,
            taxon_key=None,
            variables=[
                "key",
                "species",
                "decimalLatitude",
                "decimalLongitude",
                "eventDate",
                "taxonKey",
                "license",
            ],
            limit=3,
        )
        assert len(results) == 3
        assert results == [*_EXPECTED_QUERY_OUTPUT, extra_result]
        assert len(unique_licenses) == 2
        assert "http://creativecommons.org/licenses/by/4.0/legalcode" in unique_licenses
        assert "http://creativecommons.org/publicdomain/zero/1.0/legalcode" in unique_licenses

    def test_returns_limited_results(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=_QUERY_ENDPOINTS[_QueryType.OCCURRENCE],
            json={"count": 2, "endOfRecords": False, "results": _SAMPLE_API_RECORDS},
        )
        results, unique_licenses = _query_bbox(
            min_lat=46.2,
            max_lat=46.3,
            min_lon=-119.5,
            max_lon=-119.4,
            start_date="2019-08-01",
            end_date="2019-08-31",
            query_type=_QueryType.OCCURRENCE,
            taxon_key=None,
            variables=[
                "key",
                "species",
                "decimalLatitude",
                "decimalLongitude",
                "eventDate",
                "taxonKey",
                "license",
            ],
            limit=2,
        )
        assert len(results) == 2
        assert results == _EXPECTED_QUERY_OUTPUT
        assert len(unique_licenses) == 2
        assert "http://creativecommons.org/licenses/by/4.0/legalcode" in unique_licenses
        assert "http://creativecommons.org/publicdomain/zero/1.0/legalcode" in unique_licenses


# ---------------------------------------------------------------------------
# runtime estimation
# ---------------------------------------------------------------------------


def test_estimate_query_runtime_s():
    def mock_check_runtime(source: str, n_days: int, area_deg2: int, max_runtime_s: int):
        assert source == "gbif"
        assert n_days == 3
        assert area_deg2 == 14
        assert max_runtime_s == 200
        return {"success": True}

    with patch("env_data_mcp.sources.gbif._query.check_runtime", side_effect=mock_check_runtime):
        result = _estimate_query_runtime_s(3, 14, 200)
        assert result == {"success": True}
