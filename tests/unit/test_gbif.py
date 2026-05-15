"""Unit tests for the GBIF source adapter.

All HTTP calls are mocked via ``unittest.mock.patch``; no network access required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from env_data_mcp.sources.gbif import (
    LICENSE_INFO,
    VARIABLE_INFO,
    _fetch_gbif,
    gbif_bbox_occurrences,
    gbif_occurrences,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_YAKIMA_LAT = 46.2531882
_YAKIMA_LON = -119.4768203

# Records using the camelCase field names returned by the GBIF REST API.
_SAMPLE_API_RECORDS: list[dict[str, Any]] = [
    {
        "key": 1111111111,
        "gbifID": "1111111111",
        "species": "Salix exigua",
        "decimalLatitude": 46.26,
        "decimalLongitude": -119.48,
        "eventDate": "2019-08-15",
        "taxonKey": 2881663,
        "license": "http://creativecommons.org/licenses/by/4.0/legalcode",
    },
    {
        "key": 2222222222,
        "gbifID": "2222222222",
        "species": "Populus trichocarpa",
        "decimalLatitude": 46.27,
        "decimalLongitude": -119.49,
        "eventDate": "2019-08-19",
        "taxonKey": 3040740,
        "license": "http://creativecommons.org/publicdomain/zero/1.0/legalcode",
    },
]


def _make_mock_response(
    results: list[dict[str, Any]],
    count: int,
    end_of_records: bool = True,
) -> MagicMock:
    """Return a MagicMock that looks like an httpx.Response."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "count": count,
        "endOfRecords": end_of_records,
        "results": results,
    }
    return mock_resp


# ---------------------------------------------------------------------------
# _fetch_gbif
# ---------------------------------------------------------------------------


def test_fetch_gbif_returns_records():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response(_SAMPLE_API_RECORDS, count=2)

        records, total_count, licenses = _fetch_gbif(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=None,
            limit=1000,
        )

    assert len(records) == 2
    assert total_count == 2
    assert records[0]["species"] == "Salix exigua"
    assert records[0]["decimalLatitude"] == 46.26
    assert records[0]["gbifID"] == "1111111111"
    assert "http://creativecommons.org/licenses/by/4.0/legalcode" in licenses


def test_fetch_gbif_row_cap():
    """total_count > limit indicates results were capped at the API level."""
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response(
            _SAMPLE_API_RECORDS, count=2000, end_of_records=True
        )

        records, total_count, _ = _fetch_gbif(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=None,
            limit=1000,
        )

    assert total_count > 1000  # caller uses this to set capped=True


def test_fetch_gbif_paginates_until_limit():
    """When endOfRecords=False and we need more records, a second page is fetched."""
    extra_record = {**_SAMPLE_API_RECORDS[0], "key": 3333, "gbifID": "3333"}
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.side_effect = [
            _make_mock_response(_SAMPLE_API_RECORDS, count=3, end_of_records=False),
            _make_mock_response([extra_record], count=3, end_of_records=True),
        ]

        records, total_count, _ = _fetch_gbif(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=None,
            limit=1000,
        )

    assert mock_get.call_count == 2
    assert len(records) == 3
    assert total_count == 3


def test_fetch_gbif_license_aggregation():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response(_SAMPLE_API_RECORDS, count=2)

        _records, _total, licenses = _fetch_gbif(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=None,
            limit=1000,
        )

    assert len(licenses) == 2


def test_fetch_gbif_taxon_key_passed():
    """taxon_key is forwarded to the API as the taxonKey parameter."""
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response([], count=0)

        _fetch_gbif(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=2881663,
            limit=1000,
        )

    call_params = mock_get.call_args.kwargs["params"]
    assert call_params["taxonKey"] == 2881663


def test_fetch_gbif_falls_back_to_key_for_gbifid():
    """When gbifID is absent in the record, 'key' is used instead."""
    record_no_gbifid = {k: v for k, v in _SAMPLE_API_RECORDS[0].items() if k != "gbifID"}

    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response([record_no_gbifid], count=1)

        records, _, _ = _fetch_gbif(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=None,
            limit=1000,
        )

    assert records[0]["gbifID"] == str(record_no_gbifid["key"])


# ---------------------------------------------------------------------------
# gbif_occurrences MCP tool
# ---------------------------------------------------------------------------


def test_gbif_occurrences_success():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response(_SAMPLE_API_RECORDS, count=2)

        result = gbif_occurrences(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=50.0,
            start_date="2019-08-01",
            end_date="2019-08-31",
        )

    assert result["_meta"]["success"] is True
    assert result["_meta"]["source"] == "gbif"
    assert result["_meta"]["rows_returned"] == 2
    assert result["_meta"]["auth_required"] is False
    assert "capped" in result["_meta"]
    assert "total_count" in result["_meta"]


def test_gbif_occurrences_meta_variable_info():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response(_SAMPLE_API_RECORDS, count=2)

        result = gbif_occurrences(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=50.0,
            start_date="2019-08-01",
            end_date="2019-08-31",
        )

    vi = result["_meta"]["variable_info"]
    assert vi, "variable_info should be non-empty"
    assert "species" in vi
    assert "decimalLatitude" in vi
    assert vi["decimalLatitude"]["units"] == VARIABLE_INFO["decimalLatitude"]["units"]


def test_gbif_occurrences_meta_license_populated():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response(_SAMPLE_API_RECORDS, count=2)

        result = gbif_occurrences(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=50.0,
            start_date="2019-08-01",
            end_date="2019-08-31",
        )

    assert result["_meta"]["license"] != ""
    assert result["_meta"]["license_url"] == LICENSE_INFO["license_url"]


def test_gbif_occurrences_http_error_returns_structured():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.side_effect = httpx.ConnectError("API unreachable")

        result = gbif_occurrences(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=50.0,
            start_date="2019-08-01",
            end_date="2019-08-31",
        )

    assert result["_meta"]["success"] is False
    assert "API unreachable" in result["_meta"]["error"]
    assert result["data"] == []


def test_gbif_occurrences_query_params_echoed():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response(_SAMPLE_API_RECORDS, count=2)

        result = gbif_occurrences(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=50.0,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=12345,
        )

    qp = result["_meta"]["query_params"]
    assert qp["latitude"] == _YAKIMA_LAT
    assert qp["radius_km"] == 50.0
    assert qp["taxon_key"] == 12345


# ---------------------------------------------------------------------------
# gbif_bbox_occurrences MCP tool
# ---------------------------------------------------------------------------


def test_gbif_bbox_occurrences_success():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response(_SAMPLE_API_RECORDS, count=2)

        result = gbif_bbox_occurrences(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
        )

    assert result["_meta"]["success"] is True
    assert result["_meta"]["source"] == "gbif"
    assert result["_meta"]["rows_returned"] == 2


def test_gbif_bbox_occurrences_capped_flag():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.return_value = _make_mock_response(
            _SAMPLE_API_RECORDS, count=1001, end_of_records=True
        )

        result = gbif_bbox_occurrences(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            limit=1000,
        )

    assert result["_meta"]["capped"] is True
    assert result["_meta"]["total_count"] > 1000


def test_gbif_bbox_occurrences_http_error_returns_structured():
    with patch("env_data_mcp.sources.gbif.httpx.get") as mock_get:
        mock_get.side_effect = httpx.ConnectError("API unreachable")

        result = gbif_bbox_occurrences(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
        )

    assert result["_meta"]["success"] is False
    assert result["data"] == []
