"""Unit tests for env_data_mcp.sources.soilgrids._query."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
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


def _get_mock_httpx_client() -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.text = _VARIABLE_INFO_HTML
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


# ---------------------------------------------------------------------------
# _get_base_variable_list
# ---------------------------------------------------------------------------


def test_get_base_variable_list():
    """Tests that _get_base_variable_list returns variables."""
    with patch(
        "env_data_mcp.sources.soilgrids._query.httpx.Client",
        return_value=_get_mock_httpx_client(),
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


# ---------------------------------------------------------------------------
# _query_one_coverage
# ---------------------------------------------------------------------------


def test_query_one_coverage_returns_results() -> None:
    """Test _query_one_coverage returns expected results."""
    coverage = "bdod_0-5cm_mean"

    data = np.array([[100, -32768], [250, -32768]], dtype=np.int16)
    transform = from_origin(0.0, 0.0, 250.0, 250.0)

    with MemoryFile() as memory_file:
        with memory_file.open(
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="int16",
            nodata=-32768,
            transform=transform,
        ) as dataset:
            dataset.write(data, 1)
        payload = memory_file.read()

    mock_response = MagicMock()
    mock_response.read.return_value = payload

    coverage_info = MagicMock()
    coverage_info.supportedFormats = ["GEOTIFF_INT16"]

    mock_client = MagicMock()
    mock_client.contents = {coverage: coverage_info}
    mock_client.getCoverage.return_value = mock_response

    mock_var_info = {
        coverage: VariableInfo(
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

    with (
        patch(
            "env_data_mcp.sources.soilgrids._query._get_client_for_coverage",
            return_value=mock_client,
        ),
        patch(
            "env_data_mcp.sources.soilgrids._query.get_variable_info",
            return_value=mock_var_info,
        ),
    ):
        lats, lons, values = _query_one_coverage((0.0, 0.0, 1.0, 1.0), coverage)

    # Two valid cells survive nodata masking and are scaled by conversion factor 100.
    assert len(lats) == len(lons) == len(values) == 4
    assert 1.0 in values
    assert 2.5 in values


# ---------------------------------------------------------------------------
# query_bbox
# ---------------------------------------------------------------------------


def test_query_bbox_returns_results() -> None:
    """Test query_bbox returns expected results."""
    variables = ["bdod_15-30cm_Q0.5", "soc_0-5cm_mean", "oops", "nitrogen_0-5cm_Q0.05"]

    def mock_query_one_coverage(
        request_grid: tuple[float, float, float, float], coverage: str
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        lats = np.array([33.811, 33.812])
        lons = np.array([-116.688, -116.687])
        if coverage == "bdod_15-30cm_Q0.5":
            return lats, lons, np.array([1.5, 1.6])
        if coverage == "soc_0-5cm_mean":
            return lats, lons, np.array([0.3, float("nan")])
        if coverage == "nitrogen_0-5cm_Q0.05":
            return lats, lons, np.array([0.8, 0.9])
        raise ValueError(f"Invalid coverage name: {coverage}")

    with patch(
        "env_data_mcp.sources.soilgrids._query._query_one_coverage",
        side_effect=mock_query_one_coverage,
    ):
        results, unavailable = query_bbox(
            min_lat=33.8105,
            max_lat=33.8136,
            min_lon=-116.6900,
            max_lon=-116.6850,
            variables=variables,
        )
    assert unavailable == ["oops"]
    assert len(results) > 0
    assert "records" in results[0]
    assert len(results[0]["records"]) > 0
    assert "bdod_15-30cm_Q0.5" in results[0]["records"][0]
    assert results[0]["records"][0]["bdod_15-30cm_Q0.5"] > 0.0
    assert "soc_0-5cm_mean" in results[0]["records"][0]
    assert "nitrogen_0-5cm_Q0.05" in results[0]["records"][0]
