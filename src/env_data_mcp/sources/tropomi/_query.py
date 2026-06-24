"""Core query logic for Sentinel 5-TROPOMI: point/bbox data extraction.

Query strategy
--------------
1. Call the Copernicus Data Space Ecosystem (CDSE) OData API with a spatial
   intersection filter to find only the 1-2 orbit granules per day that
   actually cover the target point or bbox.  For a 1-month query this
   reduces ~420 candidate granules to ~47.

2. Fetch the Cloud-Optimized GeoTIFF (COGT) file for each matching granule
   from the MEEO public S3 bucket using GDAL VSICURL HTTP range GETs.  A
   COG point read downloads ~650 KB (the TIFF header + the tile covering
   the target location) instead of the ~5.5 MB needed to read the raw
   NetCDF, and GDAL handles the range requests automatically.

3. All granule COG reads are performed in parallel (16 worker threads).

Resulting latency: ~2 s (CDSE) + ~7 s (parallel COGT reads) ≈ <10 s for a
full calendar month, vs ~100 s with the previous per-day listing approach.
"""

from __future__ import annotations

import re

import httpx

from .constants import _CATALOG_URL_PREFIX, _PRODUCT_TYPES, _UNITS_MAP

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


def _get_variable_info() -> dict[str, dict[str, str]]:
    """Discover available variables for TROPOMI.

    :return: dict keyed on variable with `description` and `units`
    """
    global _VARIABLE_INFO_CACHE
    if _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE
    for product_type, product_description in _PRODUCT_TYPES.items():
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{_CATALOG_URL_PREFIX}{product_type}/catalog.json")
            resp.raise_for_status()
            info = resp.json()
        _VARIABLE_INFO_CACHE.update(
            {
                f"{product_type}-{(names := _extract_name_from_variable_url(var.get('href')))[0]}": {  # noqa: E501
                    "description": f"{product_description}: {var.get('title')}",
                    "units": _UNITS_MAP.get(names[0], "unknown"),
                    "url": var.get("href"),
                    "product_type": product_type,
                    "variable_name": names[1],
                }
                for var in info.get("links")
                if "title" in var
            }
        )
    return _VARIABLE_INFO_CACHE
