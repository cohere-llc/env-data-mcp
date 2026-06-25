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

Resulting latency: ~2 s (CDSE) + ~7 s (parallel COGT reads) ≈ <10 s for a
full calendar month, vs ~100 s with the previous per-day listing approach.
"""

from __future__ import annotations

import datetime
import re
import xml.etree.ElementTree as ET

import httpx

from env_data_mcp.helpers import parse_date

from .constants import _AWS_URL, _CDSE_ODATA_URL, _PRODUCT_TYPES, _UNITS_MAP

# ---------------------------------------------------------------------------
# Session-level caches
# ---------------------------------------------------------------------------

# available variables by name -> { variable: { "description": str, "units": str } }
_VARIABLE_INFO_CACHE: dict[str, dict[str, str]] = {}

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


def _get_cogt_variable_name(product_type: str, variable_folder: str) -> str:
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
    xml_resp = ET.fromstring(resp.text)
    keys = [(el.text or "").strip() for el in xml_resp.findall(f".//{{{_S3_NS}}}Key")]
    key = next((k for k in keys if "_PRODUCT_" in k and "qa_value" not in k), "")
    # key = "COGT/NRTI/L2__NO2___/.../..._PRODUCT_nitrogendioxide_tropospheric_column_4326.tif"
    parts = key.split("_PRODUCT_")
    if len(parts) != 2:
        raise ValueError(f"Unparsable S3 Key for COGT variable name: {key}")
    return parts[1].removesuffix("_4326.tif")


def _get_variable_info() -> dict[str, dict[str, str]]:
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
                f"{product_type}-{(names := _extract_name_from_variable_url(var.get('href')))[0]}": {  # noqa: E501
                    "description": f"{product_description}: {var.get('title')}",
                    "units": _UNITS_MAP.get(names[0], "unknown"),
                    "url": var.get("href"),
                    "product_type": product_type,  # e.g., OFFL
                    "variable_folder": names[1],  # e.g., L2__O3____
                    "cogt_name": _get_cogt_variable_name(
                        product_type, names[1]
                    ),  # e.g., methane_mixing_ratio
                }
                for var in info.get("links")
                if "title" in var
            }
        )
    return _VARIABLE_INFO_CACHE


# ---------------------------------------------------------------------------
# File identification
# ---------------------------------------------------------------------------


def _get_point_geometry_string(
    *latitude: float,
    longitude: float,
) -> str:
    """Returns an OData geometry filter string for a point location."""
    return f"geography'SRID=4326;POINT({longitude} {latitude})'"


def _get_bbox_geometry_string(
    *min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> str:
    """Returns an OData geometry filter string for a bounding box."""
    return (
        f"geography`SRID=4326;POLYGON(("
        f"{min_lon} {min_lat},{max_lon} {min_lat},"
        f"{max_lon} {max_lat},{min_lon} {max_lat},"
        f"{min_lon} {min_lat}))'"
    )


def _get_s3_file_paths(
    variable_name: str, start_date: str, end_date: str, geometry_string: str
) -> list[str]:
    """Returns a set of S3 paths to NetCDF files for given date and location ranges."""
    # the prefix is going to be something like 'S5P_OFFL_L2__CO'
    all_var_info = _get_variable_info()
    if variable_name not in all_var_info:
        msg = (
            f"Invalid TROPOMI variable name: {variable_name}. Use "
            "tropomi_available_variables tool to find valid variable names."
        )
        raise ValueError(msg)
    var_info = all_var_info[variable_name]
    name_prefix = f"S5P_{var_info['product_type']}_{var_info['variable_folder'].rstrip('_')}"

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
