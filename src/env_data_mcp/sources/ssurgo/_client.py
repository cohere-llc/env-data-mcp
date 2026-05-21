from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from .constants import _AVAIL_SQL_TABLES, _COLUMN_TABLE_PRIORITY, _SDA_URL, _XS_NS

# ---------------------------------------------------------------------------
# Session-level caches
# ---------------------------------------------------------------------------

# avail_sql → {colphyname: {"table", "label", "description", "units"}}
_VARIABLE_INFO_CACHE: dict[str, dict[str, dict[str, str]]] = {}

# physical column name → owning table; populated lazily by _get_column_table_map()
_COLUMN_TABLE_CACHE: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _get_column_table_map() -> dict[str, str]:
    """Build and cache physical column → owning table for all SSURGO query tables.

    Queries each table in ``_COLUMN_TABLE_PRIORITY`` via ``SELECT TOP 1 *``
    and parses the XSD schema embedded in the SDA response.  Each column name
    is stored only once (first wins), so shared FK names such as ``mukey``
    and ``cokey`` resolve to their PK table.  Results are cached for the
    lifetime of the process.
    """
    if _COLUMN_TABLE_CACHE:
        return _COLUMN_TABLE_CACHE
    for table in _COLUMN_TABLE_PRIORITY:
        try:
            for col in _sda_table_columns(table):
                if col not in _COLUMN_TABLE_CACHE:
                    _COLUMN_TABLE_CACHE[col] = table
        except Exception:
            pass  # skip unavailable tables; unresolved columns stay unqualified
    return _COLUMN_TABLE_CACHE


def _parse_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parse SDA XML response into a list of column-keyed dicts.

    The SDA tabular service returns XML where the root is ``<NewDataSet>`` and
    each row is a ``<Table>`` element whose children are named after the
    SELECT columns.  Returns an empty list when the dataset is empty.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    records: list[dict[str, Any]] = []
    for table_el in root.findall(".//Table"):
        row: dict[str, Any] = {}
        for child in table_el:
            row[child.tag] = child.text  # None for SQL NULL values
        if row:
            records.append(row)
    return records


def _fetch_sda(sql: str) -> tuple[list[dict[str, Any]], float]:
    """Post *sql* to SDA and return ``(records, latency_s)``.

    Returns an empty records list when the response contains no rows (e.g.
    the geometry falls outside SSURGO coverage).
    """
    t0 = time.perf_counter()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(_SDA_URL, data={"query": sql})
        resp.raise_for_status()
    latency = time.perf_counter() - t0
    return _parse_xml(resp.text), latency


def _sda_table_columns(table: str) -> list[str]:
    """Return column names for *table* by parsing the XSD schema in a TOP-1 SDA response.

    The SDA tabular service embeds an ``xs:element`` schema in each response.
    Requesting a single row is enough to trigger schema generation; the
    returned column names are then used to build the column→table cache
    without relying on the ``mdstatcolmas`` metadata catalogue.
    """
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(_SDA_URL, data={"query": f"SELECT TOP 1 * FROM {table}"})
        resp.raise_for_status()
    root = ET.fromstring(resp.text)
    return [
        name
        for el in root.findall(f".//{{{_XS_NS}}}element")
        if (name := el.get("name")) is not None and name not in ("NewDataSet", "Table")
    ]


def _get_variable_info(avail_sql: str) -> dict[str, dict[str, str]]:
    """Fetch and cache variable metadata for the tables associated with *avail_sql*.

    Tries the ``mdstatcolmas`` catalogue query first.  If that table is
    unavailable (the SDA returns HTTP 400), falls back to discovering column
    names from the actual data tables via ``SELECT TOP 1 *`` and the XSD
    schema embedded in the response.  Metadata fields (label, description,
    units) are left blank in the fallback case.

    Returns a flat dict keyed by physical column name.  Each value contains
    ``"table"``, ``"label"``, ``"description"``, and ``"units"`` entries.
    Results are cached for the lifetime of the process.
    """
    if avail_sql in _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE[avail_sql]
    info: dict[str, dict[str, str]] = {}
    try:
        records, _ = _fetch_sda(avail_sql)
        for row in records:
            col = row.get("colphyname") or ""
            if col:
                info[col] = {
                    "table": row.get("tabphyname") or "",
                    "label": row.get("collogname") or "",
                    "description": row.get("coldesc") or "",
                    "units": row.get("uomabbrev") or "",
                }
    except Exception:
        # mdstatcolmas catalogue unavailable — fall back to schema discovery.
        for table in _AVAIL_SQL_TABLES.get(avail_sql, ()):
            try:
                for col in _sda_table_columns(table):
                    if col not in info:
                        info[col] = {
                            "table": table,
                            "label": "",
                            "description": "",
                            "units": "",
                        }
            except Exception:
                pass
        if not info:
            raise  # Both the catalogue query and all schema discovery failed
    _VARIABLE_INFO_CACHE[avail_sql] = info
    return info
