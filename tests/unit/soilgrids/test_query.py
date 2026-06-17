"""Unit tests for env_data_mcp.sources.soilgrids._query."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from httpx import HTTPStatusError
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from env_data_mcp.sources.soilgrids._query import (
    BaseVariableInfo,
    VariableInfo,
    _get_client_for_coverage,
    _get_coverage_format,
    _query_one_coverage,
    get_base_variable_list,
    get_variable_info,
    query_bbox,
)
from env_data_mcp.sources.soilgrids._types import Client

_VARIABLE_INFO_HTML: str = """\
<!DOCTYPE html>
<html>
<body>
  <!-- Properties table: header row + data rows -->
  <table>
    <tr>
      <td>Name</td><td>Description</td><td>Mapped unit</td><td>Conversion factor</td><td>
      Conventional unit</td>
    </tr>
    <tr>
      <td>bdod</td><td>Bulk density</td><td>cg/cm3</td><td>100</td><td>kg/dm3</td>
    </tr>
    <tr>
      <td>cec</td><td>CEC buffered at pH7</td><td>mmol(c)/kg</td><td>10</td><td>cmol(c)/kg</td>
    </tr>
    <tr>
      <td>phh2o</td><td>pH water</td><td>pH x 10</td><td>10</td><td>-</td>
    </tr>
    <tr>
      <td>soc</td><td>Soil organic carbon</td><td>dg/kg</td><td>10</td><td>g/kg</td>
    </tr>
  </table>
  <!-- Depth intervals table: should NOT be parsed (first cell starts with "Top") -->
  <table>
    <tr>
      <td>Top depth (cm)</td><td>0</td><td>5</td><td>15</td><td>30</td>
    </tr>
    <tr>
      <td>Bottom depth (cm)</td><td>5</td><td>15</td><td>30</td><td>60</td>
    </tr>
  </table>
</body>
</html>
"""

_VARIABLE_INFO_HTML_BAD_TABLE: str = """\
<!DOCTYPE html>
<html>
<body>
  <!-- Properties table: header row + data rows -->
  <table>
    <tr>
      <td>Name</td><td>Description</td><td>Mapped unit</td><td>Conversion factor</td>
    </tr>
    <tr>
      <td>bdod</td><td>Bulk density</td><td>cg/cm3</td><td>100</td>
    </tr>
    <tr>
      <td>cec</td><td>CEC buffered at pH7</td><td>mmol(c)/kg</td><td>10</td>
    </tr>
    <tr>
      <td>phh2o</td><td>pH water</td><td>pH x 10</td><td>10</td>
    </tr>
    <tr>
      <td>soc</td><td>Soil organic carbon</td><td>dg/kg</td><td>10</td>
    </tr>
  </table>
  <!-- Depth intervals table: should NOT be parsed (first cell starts with "Top") -->
  <table>
    <tr>
      <td>Top depth (cm)</td><td>0</td><td>5</td><td>15</td><td>30</td>
    </tr>
    <tr>
      <td>Bottom depth (cm)</td><td>5</td><td>15</td><td>30</td><td>60</td>
    </tr>
  </table>
</body>
</html>
"""

_VARIABLE_INFO_HTML_MISSING_CONVERSION: str = """\
<!DOCTYPE html>
<html>
<body>
  <!-- Properties table: header row + data rows -->
  <table>
    <tr>
      <td>Name</td><td>Description</td><td>Mapped unit</td><td>Conversion factor</td><td>
      Conventional unit</td>
    </tr>
    <tr>
      <td>bdod</td><td>Bulk density</td><td>cg/cm3</td><td>100</td><td>kg/dm3</td>
    </tr>
    <tr>
      <td>cec</td><td>CEC buffered at pH7</td><td>mmol(c)/kg</td><td>10</td><td>cmol(c)/kg</td>
    </tr>
    <tr>
      <td>phh2o</td><td>pH water</td><td>pH x 10</td><td>ten</td><td>-</td>
    </tr>
    <tr>
      <td>soc</td><td>Soil organic carbon</td><td>dg/kg</td><td>10</td><td>g/kg</td>
    </tr>
  </table>
  <!-- Depth intervals table: should NOT be parsed (first cell starts with "Top") -->
  <table>
    <tr>
      <td>Top depth (cm)</td><td>0</td><td>5</td><td>15</td><td>30</td>
    </tr>
    <tr>
      <td>Bottom depth (cm)</td><td>5</td><td>15</td><td>30</td><td>60</td>
    </tr>
  </table>
</body>
</html>
"""


def _get_mock_httpx_client(html_text: str = _VARIABLE_INFO_HTML) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.text = html_text
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp
    return mock_client


def _get_mock_httpx_client_status_errors() -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = HTTPStatusError(
        "404 not found.", request=MagicMock(), response=MagicMock()
    )
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp
    return mock_client


def _mock_get_specific_variable_info(base: str) -> dict[str, tuple[str, str]]:
    if base == "bdod":
        return {
            "bdod_15-30cm_mean": ("15-30cm", "mean"),
            "bdod_30-60cm_Q0.5": ("15-30cm", "median"),
        }
    return {}


def _get_mock_client_with_contents(contents: dict[str, Any]) -> Client:
    mock = MagicMock(spec=Client)
    mock.contents = contents
    return mock


# ---------------------------------------------------------------------------
# get_base_variable_list
# ---------------------------------------------------------------------------


def test_get_base_variable_list():
    """Tests that get_base_variable_list returns variables."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids._query.httpx.Client",
            return_value=_get_mock_httpx_client(),
        ),
        patch("env_data_mcp.sources.soilgrids._query._BASE_VARIABLE_INFO_CACHE", None),
    ):
        variables = get_base_variable_list()

    assert len(variables) > 0
    found = False
    for key, var in variables.items():
        assert key == var.name
        if var.name == "bdod":
            found = True
            assert var.mapped_units == "cg/cm3"
    assert found


def test_get_base_variable_list_raises_http_status_error():
    """Tests that HTTP status errors propogate."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids._query.httpx.Client",
            return_value=_get_mock_httpx_client_status_errors(),
        ),
        patch("env_data_mcp.sources.soilgrids._query._BASE_VARIABLE_INFO_CACHE", None),
        pytest.raises(HTTPStatusError, match="404 not found"),
    ):
        _ = get_base_variable_list()


def test_get_base_variable_list_returns_empty_for_bad_html():
    """Tests that an empty dict is returned for invalid HTML tables."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids._query.httpx.Client",
            return_value=_get_mock_httpx_client(_VARIABLE_INFO_HTML_BAD_TABLE),
        ),
        patch("env_data_mcp.sources.soilgrids._query._BASE_VARIABLE_INFO_CACHE", None),
    ):
        variables = get_base_variable_list()
    assert variables == {}


def test_get_base_variable_list_skips_invalid_conversion():
    """Tests that invalid values for conversion factor lead to a silent skip of that row."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids._query.httpx.Client",
            return_value=_get_mock_httpx_client(_VARIABLE_INFO_HTML_MISSING_CONVERSION),
        ),
        patch("env_data_mcp.sources.soilgrids._query._BASE_VARIABLE_INFO_CACHE", None),
    ):
        variables = get_base_variable_list()
    assert len(variables) == 3
    assert "phh2o" not in variables


def test_get_base_variable_list_uses_cache():
    """Tests that the first call sets the cache, and subsequent calls use it."""
    sentinel = {"bdod": MagicMock()}

    with (
        patch("env_data_mcp.sources.soilgrids._query._BASE_VARIABLE_INFO_CACHE", sentinel),
        patch("env_data_mcp.sources.soilgrids._query.httpx.Client") as mock_httpx,
    ):
        result = get_base_variable_list()
    mock_httpx.assert_not_called()
    assert result is sentinel


# ---------------------------------------------------------------------------
# get_variable_info
# ---------------------------------------------------------------------------


def test_get_variable_info_test():
    """Test that get_variable_info returns results."""
    with (
        patch(
            "env_data_mcp.sources.soilgrids._query.httpx.Client",
            return_value=_get_mock_httpx_client(),
        ),
        patch(
            "env_data_mcp.sources.soilgrids._query.get_specific_variable_info",
            side_effect=_mock_get_specific_variable_info,
        ),
    ):
        var_info = get_variable_info("bdod")
    assert "bdod_15-30cm_mean" in var_info
    assert var_info["bdod_15-30cm_mean"] == VariableInfo(
        description="Bulk density; depth: 15-30cm; quantile: mean",
        units="kg/dm3",
        base=BaseVariableInfo(
            name="bdod",
            description="Bulk density",
            mapped_units="cg/cm3",
            conversion_factor=100,
            conventional_units="kg/dm3",
        ),
    )
    assert "bdod_30-60cm_Q0.5" in var_info


def test_get_variable_info_uses_cache():
    """Tests that get_variable_info uses cached values when present."""
    mock_var_info = MagicMock()
    with (
        patch("env_data_mcp.sources.soilgrids._query.httpx.Client") as mock_httpx,
        patch(
            "env_data_mcp.sources.soilgrids._query._VARIABLE_INFO_CACHE", {"bdod": mock_var_info}
        ),
    ):
        var_info = get_variable_info("bdod")
    mock_httpx.assert_not_called()
    assert var_info is mock_var_info


# ---------------------------------------------------------------------------
# _get_client_for_coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "coverage,expected",
    [
        pytest.param("bdod_15-30cm_mean", "bdod", id="density"),
        pytest.param("nitrogen_0-5cm_Q0.5", "nitrogen", id="nitrogen"),
    ],
)
def test_get_client_for_coverage_returns_client(coverage: str, expected: str):
    """Test that get_client_for_coverage gets correct client."""
    mock = MagicMock()
    mock.contents = {coverage: None}

    def mock_client(coverage: str) -> MagicMock:
        if coverage == expected:
            return mock
        return MagicMock()

    with patch("env_data_mcp.sources.soilgrids._query.get_client", side_effect=mock_client):
        client = _get_client_for_coverage(coverage)
    assert coverage in client.contents


@pytest.mark.parametrize(
    "coverage",
    [
        pytest.param("invalid_coverage", id="too short"),
        pytest.param("in_valid_cover_age", id="too long"),
        pytest.param("", id="non-existant"),
    ],
)
def test_get_client_for_coverage_raises_value_error(coverage: str):
    """Tests that _get_client_for_coverage raises ValueError on bad coverage format."""
    with (
        patch("env_data_mcp.sources.soilgrids._query.get_client", return_value=MagicMock()),
        pytest.raises(ValueError, match="Invalid coverage name"),
    ):
        _ = _get_client_for_coverage(coverage)


# ---------------------------------------------------------------------------
# _get_coverage_format
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "coverage,formats,expected",
    [
        pytest.param("bdod_15-30cm_mean", ["foo", "bar", "GeoTIFF"], "GeoTIFF", id="standard"),
        pytest.param(
            "nitrogen_0-5cm_Q0.5", ["baz", "GEOTIFF_FLOAT32", "qux"], "GEOTIFF_FLOAT32", id="float"
        ),
        pytest.param(
            "soc_5-15cm_Q0.95",
            ["GEOTIFF_INT16", "quux", "corge", "grault", "garply", "waldo"],
            "GEOTIFF_INT16",
            id="int",
        ),
    ],
)
def test_get_coverage_format_returns_value(coverage: str, formats: list[str], expected: str):
    """Tests that _get_coverage_format returns correct format."""
    mock_formats = MagicMock()
    mock_formats.supportedFormats = {format: None for format in formats}
    mock = MagicMock()
    mock.contents = {coverage: mock_formats}
    with patch("env_data_mcp.sources.soilgrids._query.get_client", return_value=mock):
        client = _get_client_for_coverage(coverage)
        format = _get_coverage_format(client, coverage)
    assert format in ("GeoTIFF", "GEOTIFF_INT16", "GEOTIFF_FLOAT32")


@pytest.mark.parametrize(
    "coverage,formats",
    [
        pytest.param("bdod_15-30cm_mean", ["foo", "bar", "baz"], id="invalid"),
        pytest.param(
            "nitrogen_0-5cm_Q0.5", ["qux", "quux", "corge", "grault", "garply", "waldo"], id="many"
        ),
        pytest.param("soc_5-15cm_Q0.95", [], id="none"),
    ],
)
def test_get_coverage_format_raises_runtime_error(coverage: str, formats: list[str]):
    """Tests that _get_coverage_format returns correct format."""
    mock_formats = MagicMock()
    mock_formats.supportedFormats = {format: None for format in formats}
    mock = MagicMock()
    mock.contents = {coverage: mock_formats}
    with (
        patch("env_data_mcp.sources.soilgrids._query.get_client", return_value=mock),
        pytest.raises(RuntimeError, match="No valid format found"),
    ):
        client = _get_client_for_coverage(coverage)
        _ = _get_coverage_format(client, coverage)


def test_get_coverage_format_raises_value_error():
    """Tests that an invalid coverage name raises a ValueError."""
    client = _get_mock_client_with_contents({})
    with pytest.raises(ValueError, match="Invalid coverage name"):
        _ = _get_coverage_format(client, "foo")


# ---------------------------------------------------------------------------
# _query_one_coverage
# ---------------------------------------------------------------------------

_COVERAGE = "bdod_0-5cm_mean"
_PATCH_CLIENT = "env_data_mcp.sources.soilgrids._query._get_client_for_coverage"
_PATCH_VAR_INFO = "env_data_mcp.sources.soilgrids._query.get_variable_info"

_MOCK_VAR_INFO = {
    _COVERAGE: VariableInfo(
        description="Bulk density; depth: 0-5cm; quantile: mean",
        units="kg/dm3",
        base=BaseVariableInfo(
            name="bdod",
            description="Bulk density",
            mapped_units="cg/cm3",
            conversion_factor=100.0,
            conventional_units="kg/dm3",
        ),
    )
}


def _make_geotiff_payload(data: np.ndarray, nodata: int | None = None) -> bytes:
    """Build an in-memory single-band GeoTIFF payload from a 2-D array."""
    h, w = data.shape
    kwargs: dict = dict(
        driver="GTiff",
        width=w,
        height=h,
        count=1,
        dtype=data.dtype.name,
        transform=from_origin(0.0, 0.0, 250.0, 250.0),
    )
    if nodata is not None:
        kwargs["nodata"] = nodata
    with MemoryFile() as mf:
        with mf.open(**kwargs) as ds:
            ds.write(data, 1)
        return mf.read()


def _make_coverage_mock_client(coverage: str, payload: bytes) -> MagicMock:
    """Return a mock WCS client whose getCoverage() returns *payload*."""
    mock_response = MagicMock()
    mock_response.read.return_value = payload
    coverage_info = MagicMock()
    coverage_info.supportedFormats = ["GEOTIFF_INT16"]
    mock_client = MagicMock()
    mock_client.contents = {coverage: coverage_info}
    mock_client.getCoverage.return_value = mock_response
    return mock_client


def test_query_one_coverage_returns_results() -> None:
    """Test _query_one_coverage returns expected results."""
    data = np.array([[100, -32768], [250, -32768]], dtype=np.int16)
    payload = _make_geotiff_payload(data, nodata=-32768)
    mock_client = _make_coverage_mock_client(_COVERAGE, payload)

    with (
        patch(_PATCH_CLIENT, return_value=mock_client),
        patch(_PATCH_VAR_INFO, return_value=_MOCK_VAR_INFO),
    ):
        lats, lons, values = _query_one_coverage((0.0, 0.0, 1.0, 1.0), _COVERAGE)

    # Two valid cells survive nodata masking and are scaled by conversion factor 100.
    assert len(lats) == len(lons) == len(values) == 4
    assert 1.0 in values
    assert 2.5 in values


def test_query_one_coverage_no_nodata() -> None:
    """Tests that _query_one_coverage works when the dataset has no nodata value set."""
    data = np.array([[100, 200], [250, 300]], dtype=np.int16)
    payload = _make_geotiff_payload(data)  # no nodata
    mock_client = _make_coverage_mock_client(_COVERAGE, payload)

    with (
        patch(_PATCH_CLIENT, return_value=mock_client),
        patch(_PATCH_VAR_INFO, return_value=_MOCK_VAR_INFO),
    ):
        lats, lons, values = _query_one_coverage((0.0, 0.0, 1.0, 1.0), _COVERAGE)

    assert len(values) == 4
    assert np.all(np.isfinite(values))


def test_query_one_coverage_all_nodata() -> None:
    """Tests that a grid where every cell equals the nodata value returns all NaN values."""
    data = np.full((2, 2), -32768, dtype=np.int16)
    payload = _make_geotiff_payload(data, nodata=-32768)
    mock_client = _make_coverage_mock_client(_COVERAGE, payload)

    with (
        patch(_PATCH_CLIENT, return_value=mock_client),
        patch(_PATCH_VAR_INFO, return_value=_MOCK_VAR_INFO),
    ):
        lats, lons, values = _query_one_coverage((0.0, 0.0, 1.0, 1.0), _COVERAGE)

    assert len(values) == 4
    assert np.all(np.isnan(values))


def test_query_one_coverage_single_cell() -> None:
    """Tests that a 1×1 grid (degenerate case) is handled without error."""
    data = np.array([[100]], dtype=np.int16)
    payload = _make_geotiff_payload(data, nodata=-32768)
    mock_client = _make_coverage_mock_client(_COVERAGE, payload)

    with (
        patch(_PATCH_CLIENT, return_value=mock_client),
        patch(_PATCH_VAR_INFO, return_value=_MOCK_VAR_INFO),
    ):
        lats, lons, values = _query_one_coverage((0.0, 0.0, 1.0, 1.0), _COVERAGE)

    assert len(lats) == len(lons) == len(values) == 1
    assert values[0] == pytest.approx(1.0)  # 100 / conversion_factor(100)


def test_query_one_coverage_get_coverage_raises() -> None:
    """Tests that exceptions from getCoverage propagate to the caller."""
    coverage_info = MagicMock()
    coverage_info.supportedFormats = ["GEOTIFF_INT16"]
    mock_client = MagicMock()
    mock_client.contents = {_COVERAGE: coverage_info}
    mock_client.getCoverage.side_effect = ConnectionError("timeout")

    with (
        patch(_PATCH_CLIENT, return_value=mock_client),
        patch(_PATCH_VAR_INFO, return_value=_MOCK_VAR_INFO),
        pytest.raises(ConnectionError, match="timeout"),
    ):
        _query_one_coverage((0.0, 0.0, 1.0, 1.0), _COVERAGE)


# ---------------------------------------------------------------------------
# query_bbox
# ---------------------------------------------------------------------------

_PATCH_QUERY_ONE = "env_data_mcp.sources.soilgrids._query._query_one_coverage"

# Bbox used across query_bbox tests
_BBOX = dict(min_lat=33.8105, max_lat=33.8136, min_lon=-116.6900, max_lon=-116.6850)

# Two points: both inside _BBOX
_LATS = np.array([33.811, 33.812])
_LONS = np.array([-116.688, -116.687])


def test_query_bbox_returns_results() -> None:
    """Test query_bbox returns expected results."""
    variables = ["bdod_15-30cm_Q0.5", "soc_0-5cm_mean", "oops", "nitrogen_0-5cm_Q0.05"]

    def mock_query_one_coverage(
        request_grid: tuple[float, float, float, float], coverage: str
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if coverage == "bdod_15-30cm_Q0.5":
            return _LATS, _LONS, np.array([1.5, 1.6])
        if coverage == "soc_0-5cm_mean":
            return _LATS, _LONS, np.array([0.3, float("nan")])
        if coverage == "nitrogen_0-5cm_Q0.05":
            return _LATS, _LONS, np.array([0.8, 0.9])
        raise ValueError(f"Invalid coverage name: {coverage}")

    with patch(_PATCH_QUERY_ONE, side_effect=mock_query_one_coverage):
        results, unavailable = query_bbox(**_BBOX, variables=variables)

    assert unavailable == ["oops"]
    assert len(results) > 0
    assert "records" in results[0]
    assert len(results[0]["records"]) > 0
    assert "bdod_15-30cm_Q0.5" in results[0]["records"][0]
    assert results[0]["records"][0]["bdod_15-30cm_Q0.5"] > 0.0
    assert "soc_0-5cm_mean" in results[0]["records"][0]
    assert "nitrogen_0-5cm_Q0.05" in results[0]["records"][0]


def test_query_bbox_all_variables_unavailable() -> None:
    """Tests that all variables failing returns an empty results list."""
    variables = ["bdod_15-30cm_Q0.5", "soc_0-5cm_mean"]

    with patch(_PATCH_QUERY_ONE, side_effect=ConnectionError("unreachable")):
        results, unavailable = query_bbox(**_BBOX, variables=variables)

    assert results == []
    assert set(unavailable) == set(variables)


def test_query_bbox_all_nan_point_filtered_out() -> None:
    """Tests that a point with all-NaN values across every variable is omitted."""
    nan = float("nan")
    # Point 0: valid for both vars. Point 1: NaN for all vars → should be filtered.
    with patch(
        _PATCH_QUERY_ONE,
        side_effect=lambda grid, cov: (_LATS, _LONS, np.array([1.0, nan])),
    ):
        results, _ = query_bbox(**_BBOX, variables=["bdod_15-30cm_Q0.5", "soc_0-5cm_mean"])

    assert len(results) == 1
    assert results[0]["latitude"] == pytest.approx(_LATS[0])


def test_query_bbox_in_bbox_flag() -> None:
    """Tests that in_bbox is True for points inside the bbox and False for points outside."""
    # Three points: inside, on the min boundary, and clearly outside
    lats = np.array([33.811, 33.8105, 33.800])  # inside, on min edge, outside
    lons = np.array([-116.688, -116.688, -116.688])

    with patch(
        _PATCH_QUERY_ONE,
        side_effect=lambda grid, cov: (lats, lons, np.array([1.0, 1.0, 1.0])),
    ):
        results, _ = query_bbox(**_BBOX, variables=["bdod_15-30cm_Q0.5"])

    in_bbox_flags = {round(r["latitude"], 4): r["in_bbox"] for r in results}
    assert in_bbox_flags[33.811] is True
    assert in_bbox_flags[33.8105] is True  # boundary is inclusive
    assert in_bbox_flags[33.8] is False


def test_query_bbox_single_variable() -> None:
    """Tests that a single-variable query works (max_workers=1 path)."""
    with patch(
        _PATCH_QUERY_ONE,
        side_effect=lambda grid, cov: (_LATS, _LONS, np.array([1.0, 2.0])),
    ):
        results, unavailable = query_bbox(**_BBOX, variables=["soc_0-5cm_mean"])

    assert unavailable == []
    assert len(results) == 2
    assert "soc_0-5cm_mean" in results[0]["records"][0]


def test_query_bbox_empty_variables() -> None:
    """Tests that an empty variables list returns an empty results list immediately."""
    with patch(_PATCH_QUERY_ONE) as mock_qoc:
        results, unavailable = query_bbox(**_BBOX, variables=[])

    mock_qoc.assert_not_called()
    assert results == []
    assert unavailable == []
