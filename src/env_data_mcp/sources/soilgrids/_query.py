"""Core query logic for SoilGrids: point/bbox data extraction.

Descriptions of how to query against the WCS clients are described
here: https://docs.isric.org/globaldata/soilgrids/WCS_from_Python.html
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Final

import httpx
import numpy as np
from bs4 import BeautifulSoup
from rasterio.io import MemoryFile
from rasterio.warp import transform, transform_bounds

from ._client import get_client
from ._types import Client
from .constants import (
    _CELL_SIZE_METERS,
    _LAYERS_INFO_URL,
    _QUANTILES,
    _REQUEST_CRS,
    _RESPONSE_CRS,
    _TRANSFORM_CRS,
)

# Invalid data value used in assembling query results
_INVALID_DATA_VALUE: Final[float] = float("nan")


# ---------------------------------------------------------------------------
# Session-level caches
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaseVariableInfo:
    """Variable descriptions and coversions for base variable types."""

    name: str
    description: str
    mapped_units: str
    conversion_factor: float
    conventional_units: str


@dataclass(frozen=True)
class VariableInfo:
    """Variable descriptions and conversions for specific variables."""

    description: str
    units: str
    base: BaseVariableInfo


# available variables -> { base_variable: { variable: VariableInfo } }
_VARIABLE_INFO_CACHE: dict[str, dict[str, VariableInfo]] = {}

# base variables -> { variable: BaseVariableInfo }
_BASE_VARIABLE_INFO_CACHE: dict[str, BaseVariableInfo] | None = None

# ---------------------------------------------------------------------------
# Available variables query functions
# ---------------------------------------------------------------------------


def get_base_variable_list() -> dict[str, BaseVariableInfo]:
    """Returns a list of base variable names for SoilGrids queries.

    This includes things like `bdod` (soil density), `phh2o` (pH), etc.
    They only seem to be available by scraping a web page. Once the list
    is created, the names can be used to create WCS clients for each
    category. The clients are then used for all other queries.
    """
    global _BASE_VARIABLE_INFO_CACHE
    if _BASE_VARIABLE_INFO_CACHE:
        return _BASE_VARIABLE_INFO_CACHE
    with httpx.Client(timeout=30) as client:
        resp = client.get(_LAYERS_INFO_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

    # Properties are in the first multi-column table
    # It has 5 columns: code, description, mapped units, conversion factor, conventional units
    _BASE_VARIABLE_INFO_CACHE = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            # skip the table about depth intervals
            if len(cells) > 0 and cells[0] and cells[0].startswith("Top"):
                break
            if len(cells) == 5 and cells[0]:
                code, description, mapped_units, conversion_factor, conventional_units = cells
                try:
                    float(conversion_factor)
                except ValueError:
                    continue
                _BASE_VARIABLE_INFO_CACHE[code] = BaseVariableInfo(
                    name=code,
                    description=description,
                    mapped_units=mapped_units,
                    conversion_factor=float(conversion_factor),
                    conventional_units=conventional_units,
                )
        if _BASE_VARIABLE_INFO_CACHE:
            break  # stop parsing after properties table

    return _BASE_VARIABLE_INFO_CACHE


def _get_specific_variable_info(base_variable: str) -> dict[str, tuple[str, str]]:
    """Get specifc variables for a base variable with depth interval and quantile.

    For a base variable like `bdod` or `silt`, you will get a list of specific
    variables (or 'coverages' in SoilGrids lingo) for specific quantiles and depths.
    The dict will end up being something like:
    ```
    {
        "bdod_0-5cm_Q0.05" : ("0-5cm", "Q0.05"),
        "bdod_5-10cm_Q0.5": ("5-10cm", "median"),
        ...
    }
    ```
    """
    client = get_client(base_variable=base_variable)
    result: dict[str, tuple[str, str]] = {}
    for var in list(client.contents):
        parts = var.split("_")
        if len(parts) != 3:
            msg = f"Invalid coverage name: {var}"
            raise ValueError(msg)
        result[var] = parts[1], _QUANTILES.get(parts[2]) or parts[2]
    return result


def get_variable_info(base_variable: str) -> dict[str, VariableInfo]:
    """Discover available variables for SoilGrids queries.

    :return: dict keyed on variable with `description`, `units`, etc.
    """
    global _VARIABLE_INFO_CACHE
    if base_variable in _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE[base_variable]
    _VARIABLE_INFO_CACHE[base_variable] = {}
    var_info = _get_specific_variable_info(base_variable)
    base_info = get_base_variable_list()[base_variable]
    for key, val in var_info.items():
        _VARIABLE_INFO_CACHE[base_variable][key] = VariableInfo(
            description=f"{base_info.description}; depth: {val[0]}; quantile: {val[1]}",
            units=base_info.conventional_units,
            base=base_info,
        )
    return _VARIABLE_INFO_CACHE[base_variable]


def _bbox_to_request_grid(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> tuple[float, float, float, float]:
    """Converts lat/lon bbox in degrees to the equivalent bbox for SoilGrids queries."""
    return transform_bounds(
        _RESPONSE_CRS,
        _TRANSFORM_CRS,
        min_lon,
        min_lat,
        max_lon,
        max_lat,
    )


def _get_base_variable_for_coverage(coverage: str) -> str:
    """Returns the base variable for a specific coverage.

    A variable like `phh2o_5-10cm_uncertainty` will return `phh2o`.
    """
    parts = coverage.split("_")
    if len(parts) != 3:
        msg = f"Invalid coverage name: {coverage}"
        raise ValueError(msg)
    return parts[0]


def _get_client_for_coverage(coverage: str) -> Client:
    """Gets a client for a given coverage."""
    return get_client(_get_base_variable_for_coverage(coverage))


def _get_coverage_format(client: Client, coverage: str) -> str:
    """Get the GeoTIFF format for a specific coverage.

    Most (maybe all?) SoilGrids coverages are in `GEOTIFF_INT16`.
    """
    if coverage_info := client.contents.get(coverage):
        formats = list(coverage_info.supportedFormats)
        for format in ("GEOTIFF_INT16", "GEOTIFF_FLOAT32", "GeoTIFF"):
            if format in formats:
                return format
        msg = f"No valid format found for {coverage}"
        raise RuntimeError(msg)
    msg = f"Invalid coverage name: {coverage}"
    raise ValueError(msg)


def _query_one_coverage(
    request_grid: tuple[float, float, float, float], coverage: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Queries SoilGrids for a single property in a request grid.

    Returns three aligned arrays: (lat, lon, values).
    Invalid cells are set to _INVALID_DATA_VALUE.
    """
    client = _get_client_for_coverage(coverage)
    format = _get_coverage_format(client, coverage)
    response = client.getCoverage(
        identifier=coverage,
        bbox=request_grid,
        crs=_REQUEST_CRS,
        resx=_CELL_SIZE_METERS,
        resy=_CELL_SIZE_METERS,
        format=format,
        interpolation="nearest neighbor",
    )

    payload = response.read()
    var_info = get_variable_info(_get_base_variable_for_coverage(coverage))
    conv_factor: float = 1.0 / var_info[coverage].base.conversion_factor

    with MemoryFile(payload) as memory_file, memory_file.open() as dataset:
        cols, rows = np.meshgrid(np.arange(dataset.width), np.arange(dataset.height))
        xs, ys = dataset.transform * (cols.flatten(), rows.flatten())
        coords = transform(_TRANSFORM_CRS, _RESPONSE_CRS, xs, ys)  # coords = (lons, lats)

        lats = np.asarray(coords[1], dtype=np.float64)
        lons = np.asarray(coords[0], dtype=np.float64)

        raw_values = dataset.read(1).flatten().astype(np.float64)
        invalid = ~np.isfinite(raw_values)
        if dataset.nodata is not None:
            invalid |= np.isclose(raw_values, dataset.nodata)

        values = raw_values * conv_factor
        values[invalid] = _INVALID_DATA_VALUE

    return lats, lons, values


def query_bbox(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    variables: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Queries SoilGrids for a bounding box area.

    Args:
        min_lat: Decimal degrees, WGS84 (-90 to 90).
        max_lat: Decimal degrees, WGS84 (-90 to 90).
        min_lon: Decimal degrees, WGS84 (-180 to 180).
        max_lon: Decimal degrees, WGS84 (-180 to 180).
        variables: Variable names to query for.
    Returns:
        Tuple of properties by geometry and list of unavailable variables.
    """
    request_grid = _bbox_to_request_grid(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )

    results_by_var: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    unavailable: list[str] = []

    max_workers = min(8, max(1, len(variables)))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_var = {
            pool.submit(_query_one_coverage, request_grid, var): var for var in variables
        }

        for future in as_completed(future_to_var):
            var = future_to_var[future]
            try:
                results_by_var[var] = future.result()
            except Exception:
                unavailable.append(var)

    available_vars = [v for v in variables if v in results_by_var]
    if not available_vars:
        return ([], unavailable)

    # All results should be on the same set of lat, lon points
    ref_lats, ref_lons, _ = results_by_var[available_vars[0]]
    n = ref_lats.size

    results: list[dict[str, Any]] = []
    for i in range(n):
        lat = float(ref_lats[i])
        lon = float(ref_lons[i])
        row: dict[str, Any] = {
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "latitude": lat,
            "longitude": lon,
            "in_bbox": bool((min_lat <= lat <= max_lat) and (min_lon <= lon <= max_lon)),
            "records": [],
        }
        all_invalid = True
        record: dict[str, Any] = {}
        for var in available_vars:
            _, _, vals = results_by_var[var]
            val = vals[i]
            if np.isnan(val):
                record[var] = None
            else:
                record[var] = float(val)
                all_invalid = False

        if not all_invalid:
            row["records"].append(record)
            results.append(row)

    return (results, unavailable)
