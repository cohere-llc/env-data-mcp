"""On-disk variable cache for the Sentinel 5-TROPOMI adapter.

The MCP server serves ``tropomi_available_variables``, filters requested
variables in queries, and constructs S3 keys for COGT reads from the
committed :file:`variables.json` shipped alongside this module, never from
the network.  The live-fetch path (Copernicus S3 catalog listings) is used
only by the refresh script and its drift integration test.

Serialization notes
-------------------
The in-memory cache holds :class:`_VariableInfo` dataclass instances because
query code needs typed access to ``product_type`` / ``underscored_name`` /
``cogt_name`` to build S3 URLs.  On disk, each entry is a flat
``dict[str, str]``; ``product_type`` is stored as its ``StrEnum`` value.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from env_data_mcp.helpers import load_json_cache
from env_data_mcp.scripts.refresh_variable_caches import VariableCacheEntry, register

from ._constants import AWS_URL, PRODUCT_TYPES, UNITS_MAP, ProductType

_VARIABLES_PATH = Path(__file__).parent / "variables.json"


@dataclass(frozen=True)
class VariableInfo:
    """Full set of per-variable information."""

    name: str  # Variable name exposed to MCP tool users (e.g., OFFL-L2_O3)
    description: str
    units: str
    product_type: ProductType
    property_name: str  # name of property (e.g., L2_O3)
    underscored_name: str  # name used in building URIs (e.g., L2__O3____)
    cogt_name: str  # descriptive name embedded in COGT file names (e.g., ozone_total_column)


# Session-level cache of dataclass instances, populated lazily on first
# _get_full_variable_info call from the on-disk JSON.
_VARIABLE_INFO_CACHE: dict[str, VariableInfo] = {}

# Processing streams in the order an equivalent variable is preferred: RPRO is
# the reprocessed archive (most refined calibration), OFFL the routine offline
# stream, and NRTI the near-real-time one (published within hours, least
# refined).
_STREAM_PREFERENCE: tuple[ProductType, ...] = (
    ProductType.RPRO,
    ProductType.OFFL,
    ProductType.NRTI,
)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _variable_info_to_dict(v: VariableInfo) -> dict[str, str]:
    """Convert a :class:`_VariableInfo` to the flat dict shape stored on disk."""
    return {
        "name": v.name,
        "description": v.description,
        "units": v.units,
        "product_type": v.product_type.value,
        "property_name": v.property_name,
        "underscored_name": v.underscored_name,
        "cogt_name": v.cogt_name,
    }


def _variable_info_from_dict(d: dict[str, str]) -> VariableInfo:
    """Rehydrate a :class:`_VariableInfo` from its on-disk dict shape."""
    return VariableInfo(
        name=d["name"],
        description=d["description"],
        units=d["units"],
        product_type=ProductType(d["product_type"]),
        property_name=d["property_name"],
        underscored_name=d["underscored_name"],
        cogt_name=d["cogt_name"],
    )


# ---------------------------------------------------------------------------
# Live discovery helpers (used by the refresh script only)
# ---------------------------------------------------------------------------


_S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"


def _extract_name_from_variable_url(url: str) -> tuple[str, str]:
    """Extract a variable name from its url in the data catalog.

    URLs are of the form
    ``https://meeo-s5p.s3.amazonaws.com/COGT/OFFL/L2__CO____/catalog.json``
    for the variable named ``L2__CO____``.  Returns a cleaned name (without
    multiple underscores in a row) for users, and the raw variable name for
    queries.
    """
    parts = url.split("/")
    if len(parts) < 6:
        return "", ""
    name = re.sub(r"_+", "_", parts[5]).rstrip("_")
    return name, parts[5]


def _get_cogt_variable_name(product_type: ProductType, variable_folder: str) -> str:
    """Return the COGT variable name for a given variable folder.

    e.g., ``("OFFL", "L2__O3____") -> "total_column_ozone"``.
    """
    resp = httpx.get(
        AWS_URL,
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
    parts = key.split("_PRODUCT_")
    if len(parts) != 2:
        msg = f"Unparsable S3 Key for COGT variable name: {key}"
        raise ValueError(msg)
    return parts[1].removesuffix("_4326.tif")


def _fetch_full_variable_info_live() -> dict[str, VariableInfo]:
    """Discover available variables for TROPOMI by hitting S3 catalog + listings."""
    result: dict[str, VariableInfo] = {}
    for product_type, product_description in PRODUCT_TYPES.items():
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{AWS_URL}COGT/{product_type}/catalog.json")
            resp.raise_for_status()
            info = resp.json()
        for var in info.get("links", []):
            if "title" not in var:
                continue
            cleaned, underscored = _extract_name_from_variable_url(var.get("href"))
            name = f"{product_type}-{cleaned}"
            result[name] = VariableInfo(
                name=name,
                description=f"{product_description}: {var.get('title')}",
                units=UNITS_MAP.get(cleaned, "unknown"),
                product_type=product_type,
                property_name=cleaned,
                underscored_name=underscored,
                cogt_name=_get_cogt_variable_name(product_type, underscored),
            )
    return result


def _fetch_all_variable_info_live() -> dict[str, dict[str, str]]:
    """Fetch full variable info from upstream and return the JSON-serialisable shape."""
    return {
        name: _variable_info_to_dict(vi) for name, vi in _fetch_full_variable_info_live().items()
    }


# ---------------------------------------------------------------------------
# Disk-backed lookup (used by the MCP server runtime)
# ---------------------------------------------------------------------------


def _load_all_variable_info_from_disk() -> dict[str, dict[str, str]]:
    """Return the on-disk cache as a JSON-shaped dict."""
    data: Any = load_json_cache(_VARIABLES_PATH)
    return data


def get_full_variable_info() -> dict[str, VariableInfo]:
    """Return the full :class:`_VariableInfo` dict, loading from disk once."""
    if _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE
    for name, entry in _load_all_variable_info_from_disk().items():
        _VARIABLE_INFO_CACHE[name] = _variable_info_from_dict(entry)
    return _VARIABLE_INFO_CACHE


def get_variable_info() -> dict[str, dict[str, str]]:
    """Return the flattened ``{name: {description, units}}`` view used by tools."""
    return {
        key: {"description": val.description, "units": val.units}
        for key, val in get_full_variable_info().items()
    }


def get_equivalent_variables(variable: VariableInfo) -> list[VariableInfo]:
    """Return the same measurement from other processing streams, best first.

    Two entries are equivalent only when the product folder, the COGT variable
    name and the units all match, so a caller substituting one for the other
    never swaps in a different quantity: ``NRTI-L2_NO2`` is a tropospheric
    column while ``OFFL-L2_NO2`` is a summed total column, and the differing
    ``cogt_name`` keeps the two apart.
    """
    equivalents = [
        info
        for info in get_full_variable_info().values()
        if info.product_type != variable.product_type
        and info.underscored_name == variable.underscored_name
        and info.cogt_name == variable.cogt_name
        and info.units == variable.units
    ]
    return sorted(equivalents, key=lambda info: _STREAM_PREFERENCE.index(info.product_type))


# ---------------------------------------------------------------------------
# Registration with the refresh script
# ---------------------------------------------------------------------------


register(
    VariableCacheEntry(
        name="tropomi",
        cache_path=_VARIABLES_PATH,
        fetch_live=_fetch_all_variable_info_live,
        load_disk=_load_all_variable_info_from_disk,
    )
)
