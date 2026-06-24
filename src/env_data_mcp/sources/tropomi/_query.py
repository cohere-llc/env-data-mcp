"""Core query logic for Sentinel 5-TROPOMI: point/bbox data extraction."""

from __future__ import annotations

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


def _extract_name_from_variable_url(url: str) -> str:
    """Extracts a variable name from its url in the data catalog.

    URLs are of the form:
    https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/L2__CO____/catalog.json

    for the variable named:
    L2__CO____
    (yes, that's right, with a whole bunch of underscores to make it
     unreadable)
    """
    parts = url.split("/")
    if len(parts) < 6:
        return ""
    return parts[5]


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
                f"{product_type}-{(name := _extract_name_from_variable_url(var.get('href')))}": {
                    "description": f"{product_description}: {var.get('title')}",
                    "units": _UNITS_MAP.get(name, "unknown"),
                    "url": var.get("href"),
                    "product_type": product_type,
                    "variable_name": name,
                }
                for var in info.get("links")
                if "title" in var
            }
        )
    return _VARIABLE_INFO_CACHE
