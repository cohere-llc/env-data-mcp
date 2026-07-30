"""On-disk variable cache for the SSURGO adapter.

The MCP server serves ``ssurgo_*_available_variables`` and qualifies SQL
column references from the committed :file:`variables.json` shipped
alongside this module, never from the network.  The live-fetch path
(SDA XSD schema introspection + Tables & Columns Report PDF parsing) is
used only by the refresh script and its drift integration test.

The ``soil_suitability`` query family is intentionally excluded from this
cache: its "available" list is a set of interpretation rule names sourced
from a live ``cointerp`` SQL query, not a set of column names.

On-disk shape
-------------
Two things need to be cached to keep the server offline:

* ``variable_info`` — per-query-type map of ``{col: {table, label, units}}``,
  used by ``_available_variables`` tools and by the ``variable_info`` meta
  block in query responses.
* ``column_table_map`` — flat ``{col: table}`` map used by ``sql.py`` to
  fully-qualify column references when building SDA SQL statements.

Both are derived from the same underlying data (XSD schemas + PDF report),
but we persist the derived caches directly so no rebuild logic runs at
server startup.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import httpx
import pdfplumber

from env_data_mcp.helpers import load_json_cache
from env_data_mcp.scripts.refresh_variable_caches import VariableCacheEntry, register

from ._client import _sda_table_columns
from ._constants import AVAIL_SQL_TABLES, COLUMN_TABLE_PRIORITY, QueryType

_VARIABLES_PATH = Path(__file__).parent / "variables.json"

# Session-level caches populated lazily on first access from the on-disk JSON.
_VARIABLE_INFO_CACHE: dict[QueryType, dict[str, dict[str, str]]] = {}
_COLUMN_TABLE_CACHE: dict[str, str] = {}


# ---------------------------------------------------------------------------
# PDF metadata parsing (used only by the refresh script)
# ---------------------------------------------------------------------------


_PDF_URL = "https://sdmdataaccess.nrcs.usda.gov/documents/TablesAndColumnsReport.pdf"

# Matches a column data row: seq, label, colphyname, logname, logtype, phytype, notnull, rest
_ROW_RE = re.compile(
    r"^(\d+)\s+"
    r"(.+?)\s+"  # label (non-greedy, always Mixed/Title Case)
    r"([a-z][a-z0-9]*)\s+"  # colphyname (lowercase, no underscores)
    r"([a-z][a-z0-9_]*)\s+"  # logname (lowercase; may or may not contain underscores)
    r"(String|Integer|Float|Boolean|Choice|DateTime|Decimal|Narrative\s+Text)\s+"
    r"(Varchar(?:\([^)]+\))?|Char|Smallint|Int|Real|Float|Bit|DateTime|Decimal|Text)\s+"
    r"(yes|no)\s*"
    r"(.*)$",
)


def _extract_uom(rest: str) -> str:
    """Extract the unit of measure from the trailing fields of a column row.

    After the ``Not Null?`` flag, the fields are: Size [Prec.] [Min] [Max] [UOM]
    [Domain].  Domain names always contain underscores; pure numbers are
    Size/Prec/Min/Max; everything else is the UOM (e.g. ``percent``, ``g/cm3``,
    ``cmol(+)/kg``).
    """
    tokens = rest.split()
    if tokens and "_" in tokens[-1]:  # strip domain name
        tokens.pop()
    if tokens:
        last = tokens[-1]
        if last and not re.match(r"^-?\d+(\.\d+)?$", last):
            return last
    return ""


def _parse_col_metadata_pdf(pdf_bytes: bytes) -> dict[str, dict[str, dict[str, str]]]:
    """Parse the SDA Tables and Columns Report PDF into a metadata dict.

    Returns ``{table_name: {colphyname: {"label": ..., "units": ...}}}``.
    Multi-page tables are handled by tracking the current table name across
    page boundaries.  Unrecognised lines are silently skipped.
    """
    result: dict[str, dict[str, dict[str, str]]] = {}
    current_table: str | None = None
    _SKIP_PREFIXES = (
        "Seq.",
        "Soil Data Mart",
        "Table Label:",
        "Table Logical Name:",
        "November",
        "USDA",
    )
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"^Table Physical Name:\s*(\S+)", line)
                if m:
                    tn = m.group(1)
                    if tn:
                        current_table = tn
                        result.setdefault(tn, {})
                    continue
                if current_table is None or any(line.startswith(p) for p in _SKIP_PREFIXES):
                    continue
                m = _ROW_RE.match(line)
                if not m:
                    continue
                colphyname = m.group(3)
                result[current_table][colphyname] = {
                    "label": m.group(2).strip(),
                    "units": _extract_uom(m.group(8)),
                }
    return result


def _load_column_metadata_live() -> dict[str, dict[str, dict[str, str]]]:
    """Download and parse the SDA Tables and Columns Report PDF.

    Returns ``{table_name: {colphyname: {"label", "units"}}}``.  On any error
    an empty dict is returned so refresh can proceed without enrichment.
    """
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(_PDF_URL)
            resp.raise_for_status()
    except Exception:
        return {}
    return _parse_col_metadata_pdf(resp.content)


# ---------------------------------------------------------------------------
# Live discovery (used only by the refresh script)
# ---------------------------------------------------------------------------


def _pdf_lookup(col: str, table_meta: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """Look up PDF metadata for *col*, with _r/_l/_h suffix fallback."""
    entry = table_meta.get(col)
    if entry is not None:
        return entry
    for suffix in ("_r", "_l", "_h"):
        if col.endswith(suffix):
            stripped = col[: -len(suffix)]
            entry = table_meta.get(stripped)
            if entry is not None:
                return entry
    return None


def _fetch_all_variable_info_live() -> dict[str, Any]:
    """Rebuild the full SSURGO cache from live SDA + PDF sources.

    Returns a JSON-serialisable dict with ``variable_info`` (per-query-type
    column metadata) and ``column_table_map`` (flat column - owning-table
    dict used by ``sql.py``).  Tables whose XSD introspection fails during
    refresh are silently skipped - matching the runtime tolerance the code
    used to have.
    """
    pdf_metadata = _load_column_metadata_live()

    # Cache XSD introspection results across query types so we hit SDA only
    # once per table during a refresh.
    table_columns: dict[str, list[str]] = {}

    def _columns_for(table: str) -> list[str]:
        if table not in table_columns:
            try:
                table_columns[table] = _sda_table_columns(table)
            except Exception:
                table_columns[table] = []
        return table_columns[table]

    variable_info: dict[str, dict[str, dict[str, str]]] = {}
    for qt in QueryType:
        info: dict[str, dict[str, str]] = {}
        for table in AVAIL_SQL_TABLES.get(qt, ()):
            table_meta = pdf_metadata.get(table, {})
            for col in _columns_for(table):
                if col in info:
                    continue
                entry: dict[str, str] = {"table": table, "label": "", "units": ""}
                pdf_meta = _pdf_lookup(col, table_meta)
                if pdf_meta is not None:
                    entry["label"] = pdf_meta.get("label", "")
                    entry["units"] = pdf_meta.get("units", "")
                info[col] = entry
        variable_info[qt.value] = info

    # column_table_map: PK-owning tables first so shared FK columns resolve
    # to their PK owner (mirrors first-wins insertion in _get_column_table_map).
    column_table_map: dict[str, str] = {}
    for table in COLUMN_TABLE_PRIORITY:
        for col in _columns_for(table):
            if col not in column_table_map:
                column_table_map[col] = table

    return {
        "variable_info": variable_info,
        "column_table_map": column_table_map,
    }


# ---------------------------------------------------------------------------
# Disk-backed lookup (used by the MCP server runtime)
# ---------------------------------------------------------------------------


def _load_all_variable_info_from_disk() -> dict[str, Any]:
    """Return the on-disk cache as a JSON-shaped dict."""
    data: Any = load_json_cache(_VARIABLES_PATH)
    return data


def _hydrate_caches_from_disk() -> None:
    """Populate both module-level caches from disk if either is empty."""
    if _VARIABLE_INFO_CACHE and _COLUMN_TABLE_CACHE:
        return
    raw = _load_all_variable_info_from_disk()
    for qt_value, cols in raw.get("variable_info", {}).items():
        try:
            qt = QueryType(qt_value)
        except ValueError:
            continue  # skip query types not defined in this build
        _VARIABLE_INFO_CACHE[qt] = dict(cols)
    _COLUMN_TABLE_CACHE.update(raw.get("column_table_map", {}))


def get_variable_info(query_type: QueryType) -> dict[str, dict[str, str]]:
    """Return cached ``{col: {table, label, units}}`` for *query_type*.

    Raises :class:`RuntimeError` when no columns are cached for the query type
    (mirrors the runtime behaviour the previous XSD-fetching version had when
    every configured table failed to respond).
    """
    _hydrate_caches_from_disk()
    info = _VARIABLE_INFO_CACHE.get(query_type)
    if not info:
        msg = f"No cached variable info for SSURGO query type {query_type!r} in {_VARIABLES_PATH}"
        raise RuntimeError(msg)
    return info


def get_column_table_map() -> dict[str, str]:
    """Return the cached ``{col: table}`` map used to qualify SQL columns."""
    _hydrate_caches_from_disk()
    return _COLUMN_TABLE_CACHE


# ---------------------------------------------------------------------------
# Registration with the refresh script
# ---------------------------------------------------------------------------


register(
    VariableCacheEntry(
        name="ssurgo",
        cache_path=_VARIABLES_PATH,
        fetch_live=_fetch_all_variable_info_live,
        load_disk=_load_all_variable_info_from_disk,
    )
)
