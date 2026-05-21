from __future__ import annotations

import io
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx
import pdfplumber

from .constants import _AVAIL_SQL_TABLES, _COLUMN_TABLE_PRIORITY, _SDA_URL, _XS_NS

# ---------------------------------------------------------------------------
# Session-level caches
# ---------------------------------------------------------------------------

# avail_sql → {colphyname: {"table": str, "label": str, "units": str}}
_VARIABLE_INFO_CACHE: dict[str, dict[str, dict[str, str]]] = {}

# physical column name → owning table; populated lazily by _get_column_table_map()
_COLUMN_TABLE_CACHE: dict[str, str] = {}

# table_name → {colphyname: {"label": str, "units": str}}; populated from PDF
_PDF_COL_METADATA_CACHE: dict[str, dict[str, dict[str, str]]] = {}

# set to True once a load attempt has been made (success or failure)
_PDF_COL_METADATA_LOADED: bool = False

# ---------------------------------------------------------------------------
# PDF metadata constants and helpers
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


def _load_column_metadata() -> dict[str, dict[str, dict[str, str]]]:
    """Download and parse the SDA Tables and Columns Report PDF (once per process).

    Returns ``_PDF_COL_METADATA_CACHE`` which maps table name → column physical
    name → ``{label, units}``.  On any error the cache remains empty and
    callers proceed without metadata enrichment.
    """
    global _PDF_COL_METADATA_LOADED
    if _PDF_COL_METADATA_LOADED:
        return _PDF_COL_METADATA_CACHE
    _PDF_COL_METADATA_LOADED = True
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(_PDF_URL)
            resp.raise_for_status()
        _PDF_COL_METADATA_CACHE.update(_parse_col_metadata_pdf(resp.content))
    except Exception:
        pass  # proceed without enrichment
    return _PDF_COL_METADATA_CACHE


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
    """Discover available columns for the tables associated with *avail_sql*.

    Column names are discovered by parsing the XSD schema embedded in a
    ``SELECT TOP 1 *`` response for each relevant table, then enriched with
    human-readable ``label`` and ``units`` from the SDA Tables and Columns
    Report PDF.  Results are cached for the lifetime of the process.
    """
    if avail_sql in _VARIABLE_INFO_CACHE:
        return _VARIABLE_INFO_CACHE[avail_sql]
    info: dict[str, dict[str, str]] = {}
    last_exc: Exception | None = None
    col_metadata = _load_column_metadata()
    for table in _AVAIL_SQL_TABLES.get(avail_sql, ()):
        try:
            table_meta = col_metadata.get(table, {})
            for col in _sda_table_columns(table):
                if col not in info:
                    # Look up PDF metadata: exact match first, then strip
                    # the _r / _l / _h representative-value suffix.
                    pdf_meta = table_meta.get(col)
                    if pdf_meta is None:
                        for suffix in ("_r", "_l", "_h"):
                            if col.endswith(suffix):
                                pdf_meta = table_meta.get(col[: -len(suffix)])
                                break
                    entry: dict[str, str] = {"table": table}
                    if pdf_meta:
                        entry.update(pdf_meta)
                    info[col] = entry
        except Exception as exc:
            last_exc = exc
    if not info:
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"No tables configured for avail_sql key: {avail_sql!r}")
    _VARIABLE_INFO_CACHE[avail_sql] = info
    return info
