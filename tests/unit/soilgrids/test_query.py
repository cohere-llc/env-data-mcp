"""Unit tests for env_data_mcp.sources.soilgrids._query."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from env_data_mcp.sources.soilgrids_new._query import (
    BaseVariableInfo,
    VariableInfo,
    _get_base_variable_list,
    get_variable_info,
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
        "env_data_mcp.sources.soilgrids_new._query.httpx.Client",
        return_value=_get_mock_httpx_client(),
    ):
        variables = _get_base_variable_list()

    assert len(variables) > 0
    found = False
    for var in variables:
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
            "env_data_mcp.sources.soilgrids_new._query.httpx.Client",
            return_value=_get_mock_httpx_client(),
        ),
        patch(
            "env_data_mcp.sources.soilgrids_new._query.get_specific_variable_info",
            side_effect=_mock_get_specific_variable_info,
        ),
    ):
        var_info = get_variable_info()
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
