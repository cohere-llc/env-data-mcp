"""Unit tests for the GBIF source adapter.

All S3 and PyArrow calls are mocked; no network access required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pyarrow as pa
import pytest

from env_data_mcp.sources.gbif import (
    _DEFAULT_LIMIT,
    _GBIF_BUCKET,
    LICENSE_INFO,
    VARIABLE_INFO,
    _discover_latest_partition,
    _fetch_gbif,
    gbif_bbox_occurrences,
    gbif_occurrences,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_YAKIMA_LAT = 46.2531882
_YAKIMA_LON = -119.4768203
_PARTITION = "2024-06-01"

# Column names are lowercase to match the real GBIF S3 Parquet schema.
# The source module renames them to camelCase before returning records.
_SAMPLE_ROWS: list[dict[str, Any]] = [
    {
        "species": "Salix exigua",
        "decimallatitude": 46.26,
        "decimallongitude": -119.48,
        "eventdate": "2019-08-15",
        "taxonkey": 2881663,
        "license": "http://creativecommons.org/licenses/by/4.0/legalcode",
        "gbifid": "1111111111",
    },
    {
        "species": "Populus trichocarpa",
        "decimallatitude": 46.27,
        "decimallongitude": -119.49,
        "eventdate": "2019-08-19",
        "taxonkey": 3040740,
        "license": "http://creativecommons.org/publicdomain/zero/1.0/legalcode",
        "gbifid": "2222222222",
    },
]


def _make_mock_dataset(rows: list[dict[str, Any]]) -> MagicMock:
    """Return a MagicMock that behaves like a pyarrow.dataset.Dataset for our purposes."""
    pdf = pd.DataFrame(rows)
    table = pa.Table.from_pandas(pdf, preserve_index=False)

    mock_scanner = MagicMock()
    mock_scanner.head.return_value = table

    mock_dataset = MagicMock()
    mock_dataset.scanner.return_value = mock_scanner

    return mock_dataset


@pytest.fixture(autouse=True)
def _reset_partition_cache():
    """Reset the module-level partition cache before/after every test."""
    import env_data_mcp.sources.gbif as _gbif_mod

    _gbif_mod._cached_latest_partition = None
    yield
    _gbif_mod._cached_latest_partition = None


# ---------------------------------------------------------------------------
# _discover_latest_partition
# ---------------------------------------------------------------------------


def test_discover_latest_partition_returns_most_recent():
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [
        f"{_GBIF_BUCKET}/occurrence/2023-06-01",
        f"{_GBIF_BUCKET}/occurrence/2024-06-01",
        f"{_GBIF_BUCKET}/occurrence/2024-01-01",
        f"{_GBIF_BUCKET}/occurrence/catalog",  # Non-date entry — should be ignored.
    ]
    result = _discover_latest_partition(mock_fs)
    assert result == "2024-06-01"


def test_discover_latest_partition_cached():
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/2024-06-01"]
    _discover_latest_partition(mock_fs)
    _discover_latest_partition(mock_fs)
    # Should only call S3 once.
    assert mock_fs.ls.call_count == 1


def test_discover_latest_partition_empty_raises():
    mock_fs = MagicMock()
    mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/catalog"]
    with pytest.raises(RuntimeError, match="No GBIF partition"):
        _discover_latest_partition(mock_fs)


# ---------------------------------------------------------------------------
# _fetch_gbif — spatial / temporal filtering and row cap
# ---------------------------------------------------------------------------


def test_fetch_gbif_returns_records():
    with (
        patch("env_data_mcp.sources.gbif.s3fs.S3FileSystem") as mock_s3_cls,
        patch("env_data_mcp.sources.gbif.pads.dataset") as mock_ds,
    ):
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/{_PARTITION}"]
        mock_s3_cls.return_value = mock_fs
        mock_ds.return_value = _make_mock_dataset(_SAMPLE_ROWS)

        records, total, partition, licenses = _fetch_gbif(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=None,
            limit=_DEFAULT_LIMIT,
        )

    assert len(records) == 2
    assert partition == _PARTITION
    assert "http://creativecommons.org/licenses/by/4.0/legalcode" in licenses


def test_fetch_gbif_row_cap():
    """When result count equals limit+1, capped should be detectable."""
    # Build limit+1 rows using _make_mock_dataset so scanner.head() returns them all.
    limit = _DEFAULT_LIMIT
    many_rows = (_SAMPLE_ROWS * ((limit // 2) + 1))[: limit + 1]
    mock_dataset = _make_mock_dataset(many_rows)  # scanner.head() returns all limit+1 rows.

    with (
        patch("env_data_mcp.sources.gbif.s3fs.S3FileSystem") as mock_s3_cls,
        patch("env_data_mcp.sources.gbif.pads.dataset", return_value=mock_dataset),
    ):
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/{_PARTITION}"]
        mock_s3_cls.return_value = mock_fs

        records, total, partition, _licenses = _fetch_gbif(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=None,
            limit=limit,
        )

    # Records returned capped at limit.
    assert len(records) == limit
    # total_before_cap > limit → capped is detected by caller.
    assert total > limit


def test_fetch_gbif_license_aggregation():
    rows_mixed = [
        {**_SAMPLE_ROWS[0], "license": "http://creativecommons.org/licenses/by/4.0/legalcode"},
        {
            **_SAMPLE_ROWS[1],
            "license": "http://creativecommons.org/publicdomain/zero/1.0/legalcode",
        },
    ]
    with (
        patch("env_data_mcp.sources.gbif.s3fs.S3FileSystem") as mock_s3_cls,
        patch("env_data_mcp.sources.gbif.pads.dataset") as mock_ds,
    ):
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/{_PARTITION}"]
        mock_s3_cls.return_value = mock_fs
        mock_ds.return_value = _make_mock_dataset(rows_mixed)

        _records, _total, _partition, licenses = _fetch_gbif(
            min_lat=46.0,
            max_lat=46.5,
            min_lon=-119.8,
            max_lon=-119.2,
            start_date="2019-08-01",
            end_date="2019-08-31",
            taxon_key=None,
            limit=_DEFAULT_LIMIT,
        )

    assert len(licenses) == 2


# ---------------------------------------------------------------------------
# gbif_occurrences MCP tool
# ---------------------------------------------------------------------------


def test_gbif_occurrences_success():
    with (
        patch("env_data_mcp.sources.gbif.s3fs.S3FileSystem") as mock_s3_cls,
        patch("env_data_mcp.sources.gbif.pads.dataset") as mock_ds,
    ):
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/{_PARTITION}"]
        mock_s3_cls.return_value = mock_fs
        mock_ds.return_value = _make_mock_dataset(_SAMPLE_ROWS)

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
    assert "partition_date" in result["_meta"]


def test_gbif_occurrences_meta_variable_info():
    with (
        patch("env_data_mcp.sources.gbif.s3fs.S3FileSystem") as mock_s3_cls,
        patch("env_data_mcp.sources.gbif.pads.dataset") as mock_ds,
    ):
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/{_PARTITION}"]
        mock_s3_cls.return_value = mock_fs
        mock_ds.return_value = _make_mock_dataset(_SAMPLE_ROWS)

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
    with (
        patch("env_data_mcp.sources.gbif.s3fs.S3FileSystem") as mock_s3_cls,
        patch("env_data_mcp.sources.gbif.pads.dataset") as mock_ds,
    ):
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/{_PARTITION}"]
        mock_s3_cls.return_value = mock_fs
        mock_ds.return_value = _make_mock_dataset(_SAMPLE_ROWS)

        result = gbif_occurrences(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=50.0,
            start_date="2019-08-01",
            end_date="2019-08-31",
        )

    assert result["_meta"]["license"] != ""
    assert result["_meta"]["license_url"] == LICENSE_INFO["license_url"]


def test_gbif_occurrences_s3_error_returns_structured():
    with (
        patch("env_data_mcp.sources.gbif.s3fs.S3FileSystem") as mock_s3_cls,
    ):
        mock_fs = MagicMock()
        mock_fs.ls.side_effect = ConnectionError("S3 unreachable")
        mock_s3_cls.return_value = mock_fs

        result = gbif_occurrences(
            latitude=_YAKIMA_LAT,
            longitude=_YAKIMA_LON,
            radius_km=50.0,
            start_date="2019-08-01",
            end_date="2019-08-31",
        )

    assert result["_meta"]["success"] is False
    assert "S3 unreachable" in result["_meta"]["error"]
    assert result["data"] == []


def test_gbif_occurrences_query_params_echoed():
    with (
        patch("env_data_mcp.sources.gbif.s3fs.S3FileSystem") as mock_s3_cls,
        patch("env_data_mcp.sources.gbif.pads.dataset") as mock_ds,
    ):
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/{_PARTITION}"]
        mock_s3_cls.return_value = mock_fs
        mock_ds.return_value = _make_mock_dataset(_SAMPLE_ROWS)

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
    with (
        patch("env_data_mcp.sources.gbif.s3fs.S3FileSystem") as mock_s3_cls,
        patch("env_data_mcp.sources.gbif.pads.dataset") as mock_ds,
    ):
        mock_fs = MagicMock()
        mock_fs.ls.return_value = [f"{_GBIF_BUCKET}/occurrence/{_PARTITION}"]
        mock_s3_cls.return_value = mock_fs
        mock_ds.return_value = _make_mock_dataset(_SAMPLE_ROWS)

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
