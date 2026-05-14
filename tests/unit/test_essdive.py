"""Unit tests for the ESS-DIVE source adapter.

All HTTP calls are mocked; no network access required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from env_data_mcp.sources.essdive import (
    LICENSE_INFO,
    _aggregate_licenses,
    _extract_record,
    _search_packages,
    essdive_bbox_query,
    essdive_query,
)

# ---------------------------------------------------------------------------
# Sample fixtures
# ---------------------------------------------------------------------------

_YAKIMA_LAT = 46.2531882
_YAKIMA_LON = -119.4768203


def _make_result(
    pkg_id: str = "ess-dive-abc123-20240101",
    doi: str = "doi:10.15485/1234567",
    title: str = "Yakima River Biogeochemistry 2019",
    license_url: str = "https://creativecommons.org/licenses/by/4.0/",
    date_published: str = "2020",
    temporal_start: str = "2019-07-01",
    temporal_end: str = "2019-09-30",
    keywords: list[str] | None = None,
    variables_measured: list[str] | None = None,
    description: str = "A dataset about biogeochemistry near Yakima.",
    view_url: str = "https://data.ess-dive.lbl.gov/view/doi:10.15485/1234567",
) -> dict:
    """Return a single ESS-DIVE API result dict."""
    return {
        "id": pkg_id,
        "viewUrl": view_url,
        "url": f"https://api.ess-dive.lbl.gov/packages/{pkg_id}",
        "dateUploaded": "2024-01-01T00:00:00.000Z",
        "dataset": {
            "@context": "http://schema.org/",
            "@type": "Dataset",
            "@id": doi,
            "name": title,
            "description": description,
            "license": license_url,
            "datePublished": date_published,
            "temporalCoverage": {
                "@type": "DateTime",
                "startDate": temporal_start,
                "endDate": temporal_end,
            },
            "keywords": keywords or ["river", "biogeochemistry", "DOC"],
            "variableMeasured": variables_measured or ["DOC", "temperature", "pH"],
        },
    }


def _make_api_response(
    results: list[dict] | None = None,
    total: int | None = None,
    next_cursor: str | None = None,
) -> dict:
    """Return a mock GET /packages response body."""
    if results is None:
        results = [_make_result()]
    return {
        "total": total if total is not None else len(results),
        "pageSize": len(results),
        "rowStart": 1,
        "result": results,
        "nextCursor": next_cursor,
        "previousCursor": None,
    }


# ---------------------------------------------------------------------------
# _extract_record
# ---------------------------------------------------------------------------


def test_extract_record_basic_fields():
    r = _extract_record(_make_result())
    assert r["id"] == "ess-dive-abc123-20240101"
    assert r["doi"] == "doi:10.15485/1234567"
    assert r["title"] == "Yakima River Biogeochemistry 2019"
    assert r["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert r["date_published"] == "2020"
    assert r["temporal_start"] == "2019-07-01"
    assert r["temporal_end"] == "2019-09-30"
    assert r["url"] == "https://data.ess-dive.lbl.gov/view/doi:10.15485/1234567"
    assert r["keywords"] == ["river", "biogeochemistry", "DOC"]
    assert r["variables_measured"] == ["DOC", "temperature", "pH"]
    assert "Yakima" in r["description"]


def test_extract_record_description_as_list():
    result = _make_result()
    result["dataset"]["description"] = [
        "First paragraph about the study.",
        "Second paragraph with more detail.",
        "Third paragraph (should be truncated).",
    ]
    r = _extract_record(result)
    assert "First paragraph" in r["description"]
    assert "Second paragraph" in r["description"]


def test_extract_record_description_truncated():
    result = _make_result()
    result["dataset"]["description"] = "x" * 600
    r = _extract_record(result)
    assert len(r["description"]) == 500


def test_extract_record_variables_as_dicts():
    result = _make_result()
    result["dataset"]["variableMeasured"] = [
        {"name": "DOC", "unitText": "mg/L"},
        {"name": "pH", "unitText": "unitless"},
        "temperature",
    ]
    r = _extract_record(result)
    assert r["variables_measured"] == ["DOC", "pH", "temperature"]


def test_extract_record_temporal_coverage_string():
    result = _make_result()
    result["dataset"]["temporalCoverage"] = "2019/2020"
    r = _extract_record(result)
    assert r["temporal_start"] == "2019/2020"
    assert r["temporal_end"] == "2019/2020"


def test_extract_record_missing_fields():
    """Gracefully handles a minimal result with missing optional fields."""
    minimal = {
        "id": "ess-dive-min-001",
        "dataset": {"@id": "doi:10.15485/0000000", "name": "Minimal"},
    }
    r = _extract_record(minimal)
    assert r["id"] == "ess-dive-min-001"
    assert r["title"] == "Minimal"
    assert r["license"] == ""
    assert r["keywords"] == []
    assert r["variables_measured"] == []
    assert r["url"] == ""


# ---------------------------------------------------------------------------
# _aggregate_licenses
# ---------------------------------------------------------------------------


def test_aggregate_licenses_single():
    records = [
        {"license": "https://creativecommons.org/publicdomain/zero/1.0/"},
        {"license": "https://creativecommons.org/publicdomain/zero/1.0/"},
    ]
    result = _aggregate_licenses(records)
    assert result == "https://creativecommons.org/publicdomain/zero/1.0/"


def test_aggregate_licenses_multiple_sorted():
    records = [
        {"license": "https://creativecommons.org/licenses/by/4.0/"},
        {"license": "https://creativecommons.org/publicdomain/zero/1.0/"},
        {"license": "https://creativecommons.org/licenses/by/4.0/"},
    ]
    result = _aggregate_licenses(records)
    parts = result.split(" | ")
    assert len(parts) == 2
    assert sorted(parts) == parts


def test_aggregate_licenses_empty_falls_back():
    result = _aggregate_licenses([])
    assert result == LICENSE_INFO["license"]


def test_aggregate_licenses_blank_entries_skipped():
    records = [{"license": ""}, {"license": "https://example.com/cc0"}]
    result = _aggregate_licenses(records)
    assert "example.com" in result


# ---------------------------------------------------------------------------
# _search_packages (mocked httpx.Client.get)
# ---------------------------------------------------------------------------


def _mock_get(response_body: dict, status_code: int = 200):
    """Return a mock httpx response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = response_body
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_search_packages_single_page():
    body = _make_api_response(results=[_make_result(), _make_result(pkg_id="ess-dive-xyz")])
    with patch("env_data_mcp.sources.essdive.httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        instance.get.return_value = _mock_get(body)
        records = _search_packages({"lat": _YAKIMA_LAT, "lon": _YAKIMA_LON}, limit=25, token="tok")
    assert len(records) == 2


def test_search_packages_respects_limit():
    results = [_make_result(pkg_id=f"ess-dive-{i}") for i in range(10)]
    body = _make_api_response(results=results)
    with patch("env_data_mcp.sources.essdive.httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        instance.get.return_value = _mock_get(body)
        records = _search_packages({}, limit=3, token="tok")
    assert len(records) == 3


def test_search_packages_401_raises_value_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch("env_data_mcp.sources.essdive.httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        instance.get.return_value = mock_resp
        with pytest.raises(ValueError, match="401"):
            _search_packages({}, limit=5, token="bad_token")


def test_search_packages_pagination_follows_cursor():
    result1 = _make_result(pkg_id="pkg-1")
    result2 = _make_result(pkg_id="pkg-2")
    page1 = _make_api_response(results=[result1], next_cursor="cur_abc")
    page2 = _make_api_response(results=[result2], next_cursor=None)
    with patch("env_data_mcp.sources.essdive.httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        instance.get.side_effect = [_mock_get(page1), _mock_get(page2)]
        records = _search_packages({}, limit=25, token="tok")
    assert len(records) == 2
    assert records[0]["id"] == "pkg-1"
    assert records[1]["id"] == "pkg-2"
    # second call must include the cursor
    second_call_params = instance.get.call_args_list[1]
    assert "cursor" in second_call_params.kwargs.get("params", {})


# ---------------------------------------------------------------------------
# essdive_query
# ---------------------------------------------------------------------------


def test_essdive_query_no_token(monkeypatch):
    monkeypatch.delenv("ESSDIVE_TOKEN", raising=False)
    result = essdive_query(latitude=_YAKIMA_LAT, longitude=_YAKIMA_LON)
    assert result["data"] == []
    meta = result["_meta"]
    assert meta["auth_required"] is True
    assert meta["auth_present"] is False
    assert meta["success"] is False
    assert "ESSDIVE_TOKEN" in meta["error"]


def test_essdive_query_success(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", "test_token")
    mock_records = [_extract_record(_make_result())]
    with patch("env_data_mcp.sources.essdive._search_packages", return_value=mock_records):
        result = essdive_query(latitude=_YAKIMA_LAT, longitude=_YAKIMA_LON)
    assert len(result["data"]) == 1
    meta = result["_meta"]
    assert meta["success"] is True
    assert meta["auth_required"] is True
    assert meta["auth_present"] is True
    assert meta["rows_returned"] == 1


def test_essdive_query_expired_token(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", "expired_token")
    with patch(
        "env_data_mcp.sources.essdive._search_packages",
        side_effect=ValueError("ESS-DIVE token rejected (HTTP 401)"),
    ):
        result = essdive_query(latitude=_YAKIMA_LAT, longitude=_YAKIMA_LON)
    assert result["data"] == []
    meta = result["_meta"]
    assert meta["success"] is False
    assert meta["auth_present"] is True
    assert "401" in meta["error"]


def test_essdive_query_no_results(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", "test_token")
    with patch("env_data_mcp.sources.essdive._search_packages", return_value=[]):
        result = essdive_query(latitude=_YAKIMA_LAT, longitude=_YAKIMA_LON)
    assert result["data"] == []
    assert result["_meta"]["success"] is True
    assert result["_meta"]["rows_returned"] == 0


def test_essdive_query_meta_fields(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", "test_token")
    records = [_extract_record(_make_result())]
    with patch("env_data_mcp.sources.essdive._search_packages", return_value=records):
        result = essdive_query(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=50.0,
            start_date="2019-01-01",
            end_date="2019-12-31",
            text="biogeochemistry",
        )
    meta = result["_meta"]
    assert meta["source"] == "essdive"
    assert meta["license_url"] == "https://data.ess-dive.lbl.gov"
    assert "latitude" in meta["query_params"]
    assert meta["query_params"]["radius_km"] == 50.0
    assert meta["query_params"]["start_date"] == "2019-01-01"
    assert meta["query_params"]["text"] == "biogeochemistry"


def test_essdive_query_license_aggregated(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", "test_token")
    r1 = _extract_record(_make_result(license_url="https://creativecommons.org/licenses/by/4.0/"))
    r2 = _extract_record(
        _make_result(
            pkg_id="ess-dive-xyz",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        )
    )
    with patch("env_data_mcp.sources.essdive._search_packages", return_value=[r1, r2]):
        result = essdive_query(latitude=_YAKIMA_LAT, longitude=_YAKIMA_LON)
    # Both licenses should appear in _meta.license
    assert "creativecommons.org" in result["_meta"]["license"]


def test_essdive_query_upstream_exception(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", "test_token")
    with patch(
        "env_data_mcp.sources.essdive._search_packages",
        side_effect=RuntimeError("network timeout"),
    ):
        result = essdive_query(latitude=_YAKIMA_LAT, longitude=_YAKIMA_LON)
    assert result["data"] == []
    assert result["_meta"]["success"] is False
    assert "network timeout" in result["_meta"]["error"]


# ---------------------------------------------------------------------------
# essdive_bbox_query
# ---------------------------------------------------------------------------


def test_essdive_bbox_query_no_token(monkeypatch):
    monkeypatch.delenv("ESSDIVE_TOKEN", raising=False)
    result = essdive_bbox_query(min_lat=46.0, max_lat=47.0, min_lon=-120.0, max_lon=-119.0)
    assert result["data"] == []
    meta = result["_meta"]
    assert meta["auth_present"] is False
    assert meta["success"] is False


def test_essdive_bbox_query_success(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", "test_token")
    records = [_extract_record(_make_result())]
    with patch("env_data_mcp.sources.essdive._search_packages", return_value=records):
        result = essdive_bbox_query(min_lat=46.0, max_lat=47.0, min_lon=-120.0, max_lon=-119.0)
    assert len(result["data"]) == 1
    assert result["_meta"]["success"] is True


def test_essdive_bbox_query_bbox_echo(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", "test_token")
    with patch("env_data_mcp.sources.essdive._search_packages", return_value=[]):
        result = essdive_bbox_query(
            min_lat=46.0,
            max_lat=47.0,
            min_lon=-120.0,
            max_lon=-119.0,
            start_date="2019-01-01",
            end_date="2019-12-31",
        )
    qp = result["_meta"]["query_params"]
    assert qp["min_lat"] == 46.0
    assert qp["max_lat"] == 47.0
    assert qp["min_lon"] == -120.0
    assert qp["max_lon"] == -119.0
    assert qp["start_date"] == "2019-01-01"


def test_essdive_bbox_query_bbox_passed_to_api(monkeypatch):
    """Verify the API receives bbox in the correct min_lat,min_lon,max_lat,max_lon format."""
    monkeypatch.setenv("ESSDIVE_TOKEN", "test_token")
    captured: list[dict] = []

    def fake_search(search_params, limit, token):
        captured.append(search_params)
        return []

    with patch("env_data_mcp.sources.essdive._search_packages", side_effect=fake_search):
        essdive_bbox_query(min_lat=46.0, max_lat=47.0, min_lon=-120.0, max_lon=-119.0)

    assert len(captured) == 1
    bbox_str = captured[0]["bbox"]
    parts = [float(x) for x in bbox_str.split(",")]
    # order: min_lat, min_lon, max_lat, max_lon
    assert parts[0] == 46.0
    assert parts[1] == -120.0
    assert parts[2] == 47.0
    assert parts[3] == -119.0


def test_essdive_bbox_query_expired_token(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", "expired")
    with patch(
        "env_data_mcp.sources.essdive._search_packages",
        side_effect=ValueError("ESS-DIVE token rejected (HTTP 401)"),
    ):
        result = essdive_bbox_query(min_lat=46.0, max_lat=47.0, min_lon=-120.0, max_lon=-119.0)
    assert result["_meta"]["success"] is False
    assert result["_meta"]["auth_present"] is True
    assert "401" in result["_meta"]["error"]
