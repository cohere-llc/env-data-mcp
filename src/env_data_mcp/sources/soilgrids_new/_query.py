"""Core query logic for SoilGrids: point/bbox data extraction."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from ._client import get_specific_variable_info
from .constants import _LAYERS_INFO_URL

# ---------------------------------------------------------------------------
# Session-level caches
# ---------------------------------------------------------------------------


@dataclass
class BaseVariableInfo:
    """Variable descriptions and coversions for base variable types."""

    name: str
    description: str
    mapped_units: str
    conversion_factor: float
    conventional_units: str


@dataclass
class VariableInfo:
    """Variable descriptions and conversions for specific variables."""

    description: str
    units: str
    base: BaseVariableInfo


# available variables -> { variable: VariableInfo}
_VARIABLE_INFO_CACHE: dict[str, VariableInfo] | None = None

# base variables -> { variable: BaseVariableInfo}
_BASE_VARIABLE_INFO_CACHE: list[BaseVariableInfo] | None = None

# ---------------------------------------------------------------------------
# Core query logic
# ---------------------------------------------------------------------------


def _get_base_variable_list() -> list[BaseVariableInfo]:
    """Returns list of base variable names for SoilGrids queries."""
    global _BASE_VARIABLE_INFO_CACHE
    if _BASE_VARIABLE_INFO_CACHE:
        return _BASE_VARIABLE_INFO_CACHE
    with httpx.Client(timeout=30) as client:
        resp = client.get(_LAYERS_INFO_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

    # Properties are in the first multi-column table
    # It has 5 columns: code, description, mapped units, conversion factor, conventional units
    _BASE_VARIABLE_INFO_CACHE = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) == 5 and cells[0] and not cells[0].startswith("Top"):
                code, description, mapped_units, conversion_factor, conventional_units = cells
                try:
                    float(conversion_factor)
                except ValueError:
                    continue
                _BASE_VARIABLE_INFO_CACHE.append(
                    BaseVariableInfo(
                        name=code,
                        description=description,
                        mapped_units=mapped_units,
                        conversion_factor=float(conversion_factor),
                        conventional_units=conventional_units,
                    )
                )
        if _BASE_VARIABLE_INFO_CACHE:
            break  # stop parsing after properties table

    return _BASE_VARIABLE_INFO_CACHE


def get_variable_info() -> dict[str, VariableInfo]:
    """Discover available variables for SoilGrids queries.

    :return: dict keyed on variable with `description`
    """
    global _VARIABLE_INFO_CACHE
    if _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE
    _VARIABLE_INFO_CACHE = {}
    base_var_info = _get_base_variable_list()
    for base in base_var_info:
        var_info = get_specific_variable_info(base.name)
        for key, val in var_info.items():
            _VARIABLE_INFO_CACHE[key] = VariableInfo(
                description=f"{base.description}; depth: {val[0]}; quantile: {val[1]}",
                units=base.conventional_units,
                base=base,
            )
    return _VARIABLE_INFO_CACHE
