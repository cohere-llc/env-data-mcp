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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import PurePosixPath
from typing import Any

import httpx
import numpy as np
import rasterio
import rasterio.windows
from rasterio.env import Env

from env_data_mcp.helpers import parse_date

from ._constants import (
    AWS_URL,
    CDSE_ODATA_URL,
    GDAL_OPTS,
    IO_WORKERS,
    MINIMUM_VALUE,
    QA_THRESHOLD,
)
from ._var_cache import VariableInfo, get_equivalent_variables, get_full_variable_info

# ---------------------------------------------------------------------------
# Core query logic
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
    variable: VariableInfo, start_date: str, end_date: str, geometry_string: str
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
            CDSE_ODATA_URL,
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


def _resolve_granules(
    variable: VariableInfo, start_date: str, end_date: str, geometry_string: str
) -> tuple[VariableInfo, list[str]]:
    """Return the variable the catalogue can serve, and its granule paths.

    CDSE lists a single processing stream per acquisition.  When the mission
    archive was reprocessed the superseded ``OFFL`` granules were withdrawn in
    favour of ``RPRO`` ones, so a stream-pinned search finds nothing for those
    dates even though both streams remain published as COGTs.  Fall back to an
    equivalent stream whenever the requested one has no granules at all in the
    window; the fallback cannot be applied granule by granule, because a day
    with no overpass of the target location is indistinguishable from a day
    whose stream was withdrawn.
    """
    paths = _get_netcdf_file_paths(variable, start_date, end_date, geometry_string)
    if paths:
        return variable, paths
    for equivalent in get_equivalent_variables(variable):
        paths = _get_netcdf_file_paths(equivalent, start_date, end_date, geometry_string)
        if paths:
            return equivalent, paths
    return variable, []


def _plan_reads(
    variables: list[str], start_date: str, end_date: str, geometry_string: str
) -> tuple[list[tuple[VariableInfo, str]], set[str], dict[str, str]]:
    """Resolve every requested variable to the COGT reads that will serve it.

    Returns the ``(variable served, granule path)`` work items, the requested
    names this adapter knows nothing about, and the ``requested -> served``
    substitutions made by :func:`_resolve_granules`.
    """
    var_info = get_full_variable_info()
    unavailable: set[str] = {var for var in variables if var not in var_info}
    reads: list[tuple[VariableInfo, str]] = []
    substitutions: dict[str, str] = {}
    for name in variables:
        if name in unavailable:
            continue
        served, paths = _resolve_granules(var_info[name], start_date, end_date, geometry_string)
        if served.name != name:
            substitutions[name] = served.name
        reads.extend((served, path) for path in paths)
    return reads, unavailable, substitutions


def _get_cogt_urls(netcdf_path: str, variable: VariableInfo) -> tuple[str, str]:
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
        f"/vsicurl/{AWS_URL}{cogt_path.with_name(new_name)}",
        f"/vsicurl/{AWS_URL}{cogt_path.with_name(new_qa_name)}",
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
    variable: VariableInfo,
    netcdf_path: str,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    """Fetch product and QA values for a point location from a GeoTIFF file.

    Values below the QA threshold are excluded from the results.
    """
    var_url, qa_url = _get_cogt_urls(netcdf_path, variable)
    with Env(aws_unsigned=True, **GDAL_OPTS):
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
        or var_val < MINIMUM_VALUE
    ):
        return {}
    if qa_nodata is not None and qa_val == qa_nodata:
        return {}
    # normalize qa_value from 0-100 to 0-1 scale
    if qa_val / 100.0 < QA_THRESHOLD:
        return {}

    return {
        "variable_name": variable.name,
        "date": _extract_date_from_netcdf_path(netcdf_path),
        "latitude": float(var_lat),
        "longitude": float(var_lon),
        "value": float(var_val),
    }


def _query_bbox_from_file(
    variable: VariableInfo,
    netcdf_path: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> list[dict[str, Any]]:
    """Fetch product and QA values for all pixels within a bounding box from a GeoTIFF file.

    Values below the QA threshold are excluded from the results.
    """
    var_url, qa_url = _get_cogt_urls(netcdf_path, variable)
    with Env(aws_unsigned=True, **GDAL_OPTS):
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
        and val >= MINIMUM_VALUE
        and not (qa_nodata is not None and qa == qa_nodata)
        and qa / 100.0 >= QA_THRESHOLD
    ]


def query_point(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    variables: list[str],
) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
    """Query for a set of variables at a point location.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
        start_date: ISO 8601 date (YYYY-MM-DD).
        end_date: ISO 8601 date (YYYY-MM-DD).
        variables: list of variable names to query for.
    Returns:
        Tuple of properties by geometry, list of unavailable variables, and the
        ``requested -> served`` processing streams substituted for any variable
        whose own stream the catalogue no longer lists for this window.  Values
        are keyed by the name of the variable that actually served them, so a
        substituted variable appears under its serving stream's name.
    """
    geometry = _get_point_geometry_string(latitude=latitude, longitude=longitude)
    reads, unavailable, substitutions = _plan_reads(variables, start_date, end_date, geometry)
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=IO_WORKERS) as pool:
        futures = [
            pool.submit(_query_point_from_file, served, path, latitude, longitude)
            for served, path in reads
        ]
        for future in as_completed(futures):
            try:
                rec = future.result()
            except Exception:
                # silently ignore failures for individual file reads to avoid failing the whole run
                continue
            if rec:
                records.append(rec)
    results = _format_results(records)
    has_data: set[str] = {
        var for geo in results for rec in geo["records"] for var in rec if var != "date"
    }
    unavailable |= {var for var in variables if substitutions.get(var, var) not in has_data}
    return results, list(unavailable), substitutions


def query_bbox(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    variables: list[str],
) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
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
        Tuple of properties by geometry, list of unavailable variables, and the
        ``requested -> served`` processing streams substituted for any variable
        whose own stream the catalogue no longer lists for this window.  Values
        are keyed by the name of the variable that actually served them, so a
        substituted variable appears under its serving stream's name.
    """
    geometry = _get_bbox_geometry_string(
        min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon
    )
    reads, unavailable, substitutions = _plan_reads(variables, start_date, end_date, geometry)
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=IO_WORKERS) as pool:
        futures = [
            pool.submit(_query_bbox_from_file, served, path, min_lat, max_lat, min_lon, max_lon)
            for served, path in reads
        ]
        for future in as_completed(futures):
            try:
                recs = future.result()
            except Exception:
                # silently ignore failures for individual file reads to avoid failing the whole run
                continue
            records.extend(recs)
    results = _format_results(records)
    has_data: set[str] = {
        var for geo in results for rec in geo["records"] for var in rec if var != "date"
    }
    unavailable |= {var for var in variables if substitutions.get(var, var) not in has_data}
    return results, list(unavailable), substitutions
