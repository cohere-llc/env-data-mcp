"""Core query logic for Sentinel 5-TROPOMI: point/bbox data extraction.

Query strategy
--------------
1. Call the Copernicus Data Space Ecosystem (CDSE) OData API with a spatial
   intersection filter to find only the 1-2 orbit NetCDF files per day that
   actually cover the target point or bbox.  For a 1-month query this
   reduces ~420 candidate files to ~47.

2. Fetch the Cloud-Optimized GeoTIFF (COGT) file for each matching key
   from the MEEO public S3 bucket using GDAL VSICURL HTTP range GETs.  A
   COG point read downloads ~650 KB (the TIFF header + the tile covering
   the target location) instead of the ~5.5 MB needed to read the raw
   NetCDF, and GDAL handles the range requests automatically.

3. All GeoTIFF COG reads are performed in parallel (16 worker threads).
"""

from __future__ import annotations

import datetime
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import httpx
import numpy as np
import rasterio
import rasterio.windows
from rasterio.env import Env

from env_data_mcp.helpers import parse_date

from .constants import (
    _AWS_URL,
    _CDSE_ODATA_URL,
    _GDAL_OPTS,
    _IO_WORKERS,
    _MINIMUM_VALUE,
    _PRODUCT_TYPES,
    _QA_THRESHOLD,
    _UNITS_MAP,
    ProductType,
)

# ---------------------------------------------------------------------------
# Session-level caches
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _VariableInfo:
    """Full set of per-variable information."""

    name: str  # Variable name exposed to MCP tool users (e.g., OFFL-L2_O3)
    description: str
    units: str
    product_type: ProductType
    property_name: str  # name of property (e.g., L2_O3)
    underscored_name: str  # name used in building URIs (e.g., L2__O3____)
    cogt_name: str  # descriptive name embedded in COGT file names (e.g., ozone_total_column)


# available variables by name
_VARIABLE_INFO_CACHE: dict[str, _VariableInfo] = {}

# ---------------------------------------------------------------------------
# Core query logic
# ---------------------------------------------------------------------------


def _extract_name_from_variable_url(url: str) -> tuple[str, str]:
    """Extracts a variable name from its url in the data catalog.

    URLs are of the form:
    https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/L2__CO____/catalog.json

    for the variable named:
    L2__CO____

    yes, that's right, with a whole bunch of underscores to make it
    effectively unreadable and very difficult to accurately reproduce
    (for humans at least). So, return a cleaned name (without multiple
    underscores in a row) for users, and the raw variable name for queries.

    :return: cleaned variable name, raw variable name
    """
    parts = url.split("/")
    if len(parts) < 6:
        return "", ""
    name = re.sub(r"_+", "_", parts[5]).rstrip("_")
    return name, parts[5]


# ---------------------------------------------------------------------------
# Available variables
# ---------------------------------------------------------------------------


_S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"


def _get_cogt_variable_name(product_type: ProductType, variable_folder: str) -> str:
    """Returns the COGT variable name associated with a variable folder.

    e.g., "OFFL", "L2__O3____" -> "total_column_ozone"
    """
    resp = httpx.get(
        _AWS_URL,
        params={
            "list-type": "2",
            "prefix": f"COGT/{product_type}/{variable_folder}/",
            "max-keys": "4",
        },
        timeout=30,
    )
    resp.raise_for_status()
    xml_resp = ET.fromstring(resp.text)
    keys = [(el.text or "").strip() for el in xml_resp.findall(f".//{{{_S3_NS}}}Key")]
    key = next((k for k in keys if "_PRODUCT_" in k and "qa_value" not in k), "")
    # key = "COGT/NRTI/L2__NO2___/.../..._PRODUCT_nitrogendioxide_tropospheric_column_4326.tif"
    parts = key.split("_PRODUCT_")
    if len(parts) != 2:
        raise ValueError(f"Unparsable S3 Key for COGT variable name: {key}")
    return parts[1].removesuffix("_4326.tif")


def _get_full_variable_info() -> dict[str, _VariableInfo]:
    """Discover available variables for TROPOMI.

    :return: dict keyed on variable with `description` and `units`
    """
    global _VARIABLE_INFO_CACHE
    if _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE
    for product_type, product_description in _PRODUCT_TYPES.items():
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{_AWS_URL}COGT/{product_type}/catalog.json")
            resp.raise_for_status()
            info = resp.json()
        _VARIABLE_INFO_CACHE.update(
            {
                (
                    name
                    := f"{product_type}-{(names := _extract_name_from_variable_url(var.get('href')))[0]}"  # noqa: E501
                ): _VariableInfo(
                    name=name,
                    description=f"{product_description}: {var.get('title')}",
                    units=_UNITS_MAP.get(names[0], "unknown"),
                    product_type=product_type,
                    property_name=names[0],
                    underscored_name=names[1],
                    cogt_name=_get_cogt_variable_name(product_type, names[1]),
                )
                for var in info.get("links")
                if "title" in var
            }
        )
    return _VARIABLE_INFO_CACHE


def get_variable_info() -> dict[str, dict[str, str]]:
    """Return descriptions and units for each available variable."""
    return {
        key: {"description": val.description, "units": val.units}
        for key, val in _get_full_variable_info().items()
    }


# ---------------------------------------------------------------------------
# File identification
# ---------------------------------------------------------------------------


def _get_point_geometry_string(
    *,
    latitude: float,
    longitude: float,
) -> str:
    """Returns an OData geometry filter string for a point location."""
    return f"geography'SRID=4326;POINT({longitude} {latitude})'"


def _get_bbox_geometry_string(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> str:
    """Returns an OData geometry filter string for a bounding box."""
    return (
        f"geography'SRID=4326;POLYGON(("
        f"{min_lon} {min_lat},{max_lon} {min_lat},"
        f"{max_lon} {max_lat},{min_lon} {max_lat},"
        f"{min_lon} {min_lat}))'"
    )


def _get_netcdf_file_paths(
    variable: _VariableInfo, start_date: str, end_date: str, geometry_string: str
) -> list[str]:
    """Returns a set of S3 paths to NetCDF files for given date and location ranges."""
    # the prefix is going to be something like 'S5P_OFFL_L2__CO'
    name_prefix = f"S5P_{variable.product_type}_{variable.underscored_name.rstrip('_')}"

    start_dt = parse_date(start_date)
    end_dt = parse_date(end_date) + datetime.timedelta(days=1)
    filter_string = (
        f"Collection/Name eq 'SENTINEL-5P'"
        f" and startswith(Name,'{name_prefix}')"
        f" and OData.CSC.Intersects(area={geometry_string})"
        f" and ContentDate/Start ge {start_dt.isoformat()}T00:00:00.000Z"
        f" and ContentDate/Start lt {end_dt.isoformat()}T00:00:00.000Z"
    )

    paths: list[str] = []
    skip = 0
    page_size = 1000
    while True:
        resp = httpx.get(
            _CDSE_ODATA_URL,
            params={
                "$filter": filter_string,
                "$top": str(page_size),
                "$skip": str(skip),
                "$select": "S3Path",
            },
            timeout=30,
        )
        resp.raise_for_status()
        page = resp.json().get("value", [])
        paths.extend(r["S3Path"] for r in page)
        if len(page) < page_size:
            break
        skip += page_size
    return paths


def _get_cogt_urls(netcdf_path: str, variable: _VariableInfo) -> tuple[str, str]:
    """Returns GDAL VSICURL URLs for an equivalent S3 NetCDF path.

    The URLs returned are for the requested variable and the qa_values."""
    parts = netcdf_path.split("TROPOMI")
    if len(parts) != 2:
        msg = f"Unparsable NetCDF S3 path: {netcdf_path}"
        raise ValueError(msg)
    # parts[1] e.g. "/L2__O3____/2024/01/03/S5P_OFFL_L2__O3_____20240103.nc"
    cogt_path = PurePosixPath(f"COGT/{variable.product_type}{parts[1]}")
    new_name = f"{cogt_path.stem}_PRODUCT_{variable.cogt_name}_4326.tif"
    new_qa_name = f"{cogt_path.stem}_PRODUCT_qa_value_4326.tif"
    return (
        f"/vsicurl/{_AWS_URL}{cogt_path.with_name(new_name)}",
        f"/vsicurl/{_AWS_URL}{cogt_path.with_name(new_qa_name)}",
    )


# ---------------------------------------------------------------------------
# Point and BBox Query functions
# ---------------------------------------------------------------------------


def _extract_date_from_netcdf_path(netcdf_path: str) -> str:
    """Extract date information from a NetCDF path and returns it as YYYY-MM-DD."""
    parts = netcdf_path.split("/")
    if len(parts) < 8:
        msg = f"Unparsable NetCDF path for date: {netcdf_path}"
        raise ValueError(msg)
    return f"{parts[5]}-{parts[6]}-{parts[7]}"


def _format_results(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw query results into common mcp tool format."""
    results: dict[tuple[float, float], dict[str, Any]] = {}
    for rec in records:
        key = (rec["latitude"], rec["longitude"])
        if key not in results:
            results[key] = {
                "geometry": {"type": "Point", "coordinates": [key[1], key[0]]},
                "latitude": key[0],
                "longitude": key[1],
                "records_dict": {},
            }
        if rec["date"] not in results[key]["records_dict"]:
            results[key]["records_dict"][rec["date"]] = {}
        results[key]["records_dict"][rec["date"]][rec["variable_name"]] = rec["value"]
    for _, val in results.items():
        val["records"] = [{"date": key, **rec} for key, rec in val["records_dict"].items()]
        val.pop("records_dict")
    return [val for _, val in results.items()]


def _query_point_from_file(
    variable: _VariableInfo,
    netcdf_path: str,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    """Fetch product and QA values for a point location from a GeoTIFF file.

    Values below the QA threshhold are excluded from the results.
    """
    var_url, qa_url = _get_cogt_urls(netcdf_path, variable)
    with Env(aws_unsigned=True, **_GDAL_OPTS):
        with rasterio.open(var_url) as ds:
            var_nodata = ds.nodata
            row, col = ds.index(longitude, latitude)
            var_lon, var_lat = ds.xy(row, col)
            var_val = float(next(ds.sample([(longitude, latitude)]))[0])
        with rasterio.open(qa_url) as ds:
            qa_nodata = ds.nodata
            qa_val = float(next(ds.sample([(longitude, latitude)]))[0])

    if (
        (var_nodata is not None and var_val == var_nodata)
        or not np.isfinite(var_val)
        or var_val < _MINIMUM_VALUE
    ):
        return {}
    if qa_nodata is not None and qa_val == qa_nodata:
        return {}
    # normalize qa_value from 0-100 to 0-1 scale
    if qa_val / 100.0 < _QA_THRESHOLD:
        return {}

    return {
        "variable_name": variable.name,
        "date": _extract_date_from_netcdf_path(netcdf_path),
        "latitude": float(var_lat),
        "longitude": float(var_lon),
        "value": float(var_val),
    }


def _query_bbox_from_file(
    variable: _VariableInfo,
    netcdf_path: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> list[dict[str, Any]]:
    """Fetch product and QA values for a point location from a GeoTIFF file.

    Values below the QA threshhold are excluded from the results.
    """
    var_url, qa_url = _get_cogt_urls(netcdf_path, variable)
    with Env(aws_unsigned=True, **_GDAL_OPTS):
        with rasterio.open(var_url) as ds:
            var_nodata = ds.nodata
            window = rasterio.windows.from_bounds(min_lon, min_lat, max_lon, max_lat, ds.transform)
            var_vals = ds.read(1, window=window).astype(np.float64)

            nrows, ncols = var_vals.shape
            row_idx = np.arange(int(window.row_off), int(window.row_off) + nrows)
            col_idx = np.arange(int(window.col_off), int(window.col_off) + ncols)
            col_grid, row_grid = np.meshgrid(col_idx, row_idx)
            lons, lats = ds.xy(row_grid, col_grid)
            lons = np.array(lons)
            lats = np.array(lats)
        with rasterio.open(qa_url) as ds:
            qa_nodata = ds.nodata
            qa_vals = ds.read(1, window=window).astype(np.float64)

    date = _extract_date_from_netcdf_path(netcdf_path)
    return [
        {
            "variable_name": variable.name,
            "date": date,
            "latitude": float(lat),
            "longitude": float(lon),
            "value": float(val),
        }
        for val, qa, lat, lon in zip(
            var_vals.ravel(), qa_vals.ravel(), lats.ravel(), lons.ravel(), strict=True
        )
        if not (var_nodata is not None and val == var_nodata)
        and np.isfinite(val)
        and val >= _MINIMUM_VALUE
        and not (qa_nodata is not None and qa == qa_nodata)
        and qa / 100.0 >= _QA_THRESHOLD
    ]


def query_point(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    variables: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Query for a set of variables at a point location.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        start_date: ISO 8601 date (YYYY-MM-DD).
        end_date: ISO 8601 date (YYYY-MM-DD).
        variables: list of variable names to query for.
    Returns:
        Tuple of properties by geometry and list of unavailable variables.
    """
    var_info = _get_full_variable_info()
    unavailable: set[str] = {var for var in variables if var not in var_info}
    geometry = _get_point_geometry_string(latitude=latitude, longitude=longitude)
    netcdf_paths: list[tuple[_VariableInfo, str]] = [
        (var_info[name], path)
        for name in variables
        if name not in unavailable
        for path in _get_netcdf_file_paths((var_info[name]), start_date, end_date, geometry)
    ]
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=_IO_WORKERS) as pool:
        futures = [
            pool.submit(_query_point_from_file, rec[0], rec[1], latitude, longitude)
            for rec in netcdf_paths
        ]
        for future in as_completed(futures):
            try:
                rec = future.result()
                if rec:
                    records.append(rec)
            except Exception:
                # silently ignore failures for individual file reads to avoid failing the whole run
                continue
    results = _format_results(records)
    has_data: set[str] = {
        var for geo in results for rec in geo["records"] for var in rec if var != "date"
    }
    unavailable |= {var for var in variables if var not in has_data}
    return results, list(unavailable)


def query_bbox(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    variables: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Query for a set of variables within a bounding box.

    Args:
        min_lat: Decimal degrees, WGS84 (-90 to 90).
        max_lat: Decimal degrees, WGS84 (-90 to 90).
        min_lon: Decimal degrees, WGS84 (-180 to 180).
        max_lon: Decimal degrees, WGS84 (-180 to 180).
        start_date: ISO 8601 date (YYYY-MM-DD).
        end_date: ISO 8601 date (YYYY-MM-DD).
        variables: list of variable names to query for.
    Returns:
        Tupe of properties by geometry and list of unavailable variables.
    """
    var_info = _get_full_variable_info()
    unavailable: set[str] = {var for var in variables if var not in var_info}
    geometry = _get_bbox_geometry_string(
        min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon
    )
    netcdf_paths: list[tuple[_VariableInfo, str]] = [
        (var_info[name], path)
        for name in variables
        if name not in unavailable
        for path in _get_netcdf_file_paths((var_info[name]), start_date, end_date, geometry)
    ]
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=_IO_WORKERS) as pool:
        futures = [
            pool.submit(_query_bbox_from_file, rec[0], rec[1], min_lat, max_lat, min_lon, max_lon)
            for rec in netcdf_paths
        ]
        for future in as_completed(futures):
            try:
                recs = future.result()
                if recs:
                    records.extend(recs)
            except Exception:
                # silently ignore failures for individual file reads to avoid failing the whole run
                continue
    results = _format_results(records)
    has_data: set[str] = {
        var for geo in results for rec in geo["records"] for var in rec if var != "date"
    }
    unavailable |= {var for var in variables if var not in has_data}
    return results, list(unavailable)
