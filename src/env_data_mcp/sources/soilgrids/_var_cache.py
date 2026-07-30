"""On-disk variable cache for the SoilGrids adapter.

The MCP server serves ``soilgrids_available_variables``, filters requested
variables in queries, and looks up per-variable ``conversion_factor`` values
from the committed :file:`variables.json` shipped alongside this module,
never from the network.  The live-fetch path (ISRIC HTML scrape + WCS
per-base listings) is used only by the refresh script and its drift
integration test.

Serialization notes
-------------------
The in-memory cache holds nested :class:`BaseVariableInfo` /
:class:`VariableInfo` dataclass instances because query code needs typed
access to ``.base.conversion_factor``.  On disk each base variable is
serialized as ``{"base": BaseInfoDict, "coverages": {coverage: {...}}}`` -
base info is stored once per base variable rather than duplicated inside
every coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from env_data_mcp.helpers import load_json_cache
from env_data_mcp.scripts.refresh_variable_caches import VariableCacheEntry, register

from ._client import get_client
from ._constants import LAYERS_INFO_URL, QUANTILES

_VARIABLES_PATH = Path(__file__).parent / "variables.json"


# ---------------------------------------------------------------------------
# Data model
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


# Session-level caches populated lazily on first access from the on-disk JSON.
_BASE_VARIABLE_INFO_CACHE: dict[str, BaseVariableInfo] = {}
_VARIABLE_INFO_CACHE: dict[str, dict[str, VariableInfo]] = {}


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _base_variable_info_to_dict(v: BaseVariableInfo) -> dict[str, Any]:
    return {
        "name": v.name,
        "description": v.description,
        "mapped_units": v.mapped_units,
        "conversion_factor": v.conversion_factor,
        "conventional_units": v.conventional_units,
    }


def _base_variable_info_from_dict(d: dict[str, Any]) -> BaseVariableInfo:
    return BaseVariableInfo(
        name=d["name"],
        description=d["description"],
        mapped_units=d["mapped_units"],
        conversion_factor=float(d["conversion_factor"]),
        conventional_units=d["conventional_units"],
    )


# ---------------------------------------------------------------------------
# Live discovery (used by the refresh script only)
# ---------------------------------------------------------------------------


def _fetch_base_variable_list_live() -> dict[str, BaseVariableInfo]:
    """Scrape the ISRIC properties HTML table to discover base variables."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(LAYERS_INFO_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

    # Properties are in the first multi-column table.
    # It has 5 columns: code, description, mapped units, conversion factor,
    # conventional units.
    result: dict[str, BaseVariableInfo] = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            # skip the depth-intervals table if we encounter it
            if len(cells) > 0 and cells[0] and cells[0].startswith("Top"):
                break
            if len(cells) == 5 and cells[0]:
                code, description, mapped_units, conversion_factor, conventional_units = cells
                try:
                    conv_factor = float(conversion_factor)
                except ValueError:
                    continue
                result[code] = BaseVariableInfo(
                    name=code,
                    description=description,
                    mapped_units=mapped_units,
                    conversion_factor=conv_factor,
                    conventional_units=conventional_units,
                )
        if result:
            break  # stop parsing after properties table
    return result


def _fetch_specific_variable_info_live(base_variable: str) -> dict[str, tuple[str, str]]:
    """Return coverage_name → (depth, quantile) for *base_variable* via WCS."""
    client = get_client(base_variable=base_variable)
    result: dict[str, tuple[str, str]] = {}
    for var in list(client.contents):
        parts = var.split("_")
        if len(parts) != 3:
            msg = f"Invalid coverage name: {var}"
            raise ValueError(msg)
        result[var] = parts[1], QUANTILES.get(parts[2]) or parts[2]
    return result


def _fetch_all_variable_info_live() -> dict[str, dict[str, Any]]:
    """Discover the full SoilGrids variable catalog and return the JSON-serialisable shape.

    Shape: ``{base_variable: {"base": {...}, "coverages": {coverage: {description, units}}}}``.

    Base variables whose WCS endpoint is unavailable are skipped silently,
    mirroring runtime tolerance in :func:`soilgrids_available_variables`.
    """
    base_info = _fetch_base_variable_list_live()
    result: dict[str, dict[str, Any]] = {}
    for base, bvi in base_info.items():
        try:
            specific = _fetch_specific_variable_info_live(base)
        except Exception:
            continue
        coverages = {
            key: {
                "description": f"{bvi.description}; depth: {depth}; quantile: {quantile}",
                "units": bvi.conventional_units,
            }
            for key, (depth, quantile) in specific.items()
        }
        result[base] = {
            "base": _base_variable_info_to_dict(bvi),
            "coverages": coverages,
        }
    return result


# ---------------------------------------------------------------------------
# Disk-backed lookup (used by the MCP server runtime)
# ---------------------------------------------------------------------------


def _load_all_variable_info_from_disk() -> dict[str, dict[str, Any]]:
    """Return the on-disk cache as a JSON-shaped dict."""
    data: Any = load_json_cache(_VARIABLES_PATH)
    return data


def _hydrate_caches_from_disk() -> None:
    """Populate both module-level caches from disk if either is empty."""
    if _BASE_VARIABLE_INFO_CACHE and _VARIABLE_INFO_CACHE:
        return
    raw = _load_all_variable_info_from_disk()
    for base, block in raw.items():
        bvi = _base_variable_info_from_dict(block["base"])
        _BASE_VARIABLE_INFO_CACHE[base] = bvi
        _VARIABLE_INFO_CACHE[base] = {
            coverage: VariableInfo(
                description=entry["description"],
                units=entry["units"],
                base=bvi,
            )
            for coverage, entry in block["coverages"].items()
        }


def get_base_variable_list() -> dict[str, BaseVariableInfo]:
    """Return ``{base_variable: BaseVariableInfo}`` from the on-disk cache."""
    _hydrate_caches_from_disk()
    return _BASE_VARIABLE_INFO_CACHE


def get_variable_info(base_variable: str) -> dict[str, VariableInfo]:
    """Return ``{coverage: VariableInfo}`` for *base_variable* from the on-disk cache."""
    _hydrate_caches_from_disk()
    if base_variable not in _VARIABLE_INFO_CACHE:
        msg = (
            f"No cached variable info for SoilGrids base variable "
            f"{base_variable!r} in {_VARIABLES_PATH}"
        )
        raise KeyError(msg)
    return _VARIABLE_INFO_CACHE[base_variable]


# ---------------------------------------------------------------------------
# Registration with the refresh script
# ---------------------------------------------------------------------------


register(
    VariableCacheEntry(
        name="soilgrids",
        cache_path=_VARIABLES_PATH,
        fetch_live=_fetch_all_variable_info_live,
        load_disk=_load_all_variable_info_from_disk,
    )
)
