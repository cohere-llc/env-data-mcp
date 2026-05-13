"""USDA SSURGO soil data adapter.

Data source: USDA Web Soil Survey Soil Data Access (SDA)
  ``https://sdmdataaccess.nrcs.usda.gov/``
Coverage: Continental US + territories; no auth required
Auth required: No
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from env_data_mcp.helpers import bbox_centroid, build_meta, clamp_bbox
from env_data_mcp.server import mcp

# ---------------------------------------------------------------------------
# Licence and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
    "license": "Public domain (USDA/US Government).",
    "license_url": "https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo",
    "citation": "USDA-NRCS (2024). Web Soil Survey. "
    "Soil Survey Geographic Database (SSURGO). "
    "https://websoilsurvey.nrcs.usda.gov",
}

_SDA_URL = "https://sdmdataaccess.nrcs.usda.gov/Tabular/SDMTabularService/post.rest"

# Column names in SELECT order — used to build row dicts after XML parsing.
_COLUMNS = [
    "mukey",
    "muname",
    "musym",
    "compname",
    "majcompflag",
    "drainagecl",
    "comppct_r",
    "hzdepb_r",
    "sandtotal_r",
    "silttotal_r",
    "claytotal_r",
    "ph1to1h2o_r",
    "om_r",
    "ksat_r",
    "dbthirdbar_r",
]

_NO_COVERAGE_MSG = (
    "No SSURGO data for this location. "
    "The point may be outside SSURGO coverage (non-US or unmapped area)."
)

# Plain-language descriptions and expected units for every column returned
# by the SDA SQL query.  Included in _meta.variable_info on every response.
COLUMN_INFO: dict[str, dict[str, str]] = {
    "mukey": {"description": "SSURGO map-unit key (unique ID)", "units": "—"},
    "muname": {"description": "Map unit name (e.g., 'Ritzville silt loam')", "units": "—"},
    "musym": {"description": "Map unit symbol", "units": "—"},
    "compname": {"description": "Soil component name (dominant soil series)", "units": "—"},
    "majcompflag": {
        "description": "Whether this is the major component ('Yes'/'No')",
        "units": "—",
    },
    "drainagecl": {
        "description": "Drainage class (e.g., 'well drained', 'poorly drained')",
        "units": "—",
    },
    "comppct_r": {
        "description": "Percent of map unit occupied by this component (representative value)",
        "units": "%",
        "valid_range": "0 to 100",
    },
    "hzdepb_r": {
        "description": "Horizon bottom depth (representative value)",
        "units": "cm",
        "valid_range": "0 to ~300",
    },
    "sandtotal_r": {
        "description": "Total sand content (representative value)",
        "units": "%",
        "valid_range": "0 to 100",
    },
    "silttotal_r": {
        "description": "Total silt content (representative value)",
        "units": "%",
        "valid_range": "0 to 100",
    },
    "claytotal_r": {
        "description": "Total clay content (representative value)",
        "units": "%",
        "valid_range": "0 to 100",
    },
    "ph1to1h2o_r": {
        "description": "Soil pH measured in 1:1 water suspension (representative value)",
        "units": "pH units",
        "valid_range": "2 to 11",
    },
    "om_r": {
        "description": "Organic matter content (representative value)",
        "units": "%",
        "valid_range": "0 to ~100",
    },
    "ksat_r": {
        "description": "Saturated hydraulic conductivity (representative value)",
        "units": "µm/s",
        "valid_range": "0 to ~700",
    },
    "dbthirdbar_r": {
        "description": "Bulk density at 1/3 bar water content (representative value)",
        "units": "g/cm³",
        "valid_range": "0.5 to 2.0",
    },
}


# ---------------------------------------------------------------------------
# Core query logic (sync, testable without MCP)
# ---------------------------------------------------------------------------


def _build_sql(wkt_point: str) -> str:
    """Return the SDA SQL for the given WKT POINT geometry."""
    return f"""
        SELECT
            mapunit.mukey,
            mapunit.muname,
            mapunit.musym,
            component.compname,
            component.majcompflag,
            component.drainagecl,
            component.comppct_r,
            chorizon.hzdepb_r,
            chorizon.sandtotal_r,
            chorizon.silttotal_r,
            chorizon.claytotal_r,
            chorizon.ph1to1h2o_r,
            chorizon.om_r,
            chorizon.ksat_r,
            chorizon.dbthirdbar_r
        FROM mapunit
        JOIN component ON component.mukey = mapunit.mukey
        LEFT JOIN chorizon ON chorizon.cokey = component.cokey
        WHERE mapunit.mukey IN (
            SELECT DISTINCT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84(
                '{wkt_point}'
            )
        )
        AND component.majcompflag = 'Yes'
        ORDER BY mapunit.mukey, component.cokey, chorizon.hzdepb_r
    """


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


def _fetch_ssurgo(lat: float, lon: float) -> tuple[list[dict[str, Any]], float]:
    """Query SDA for the major component + horizon data at (lat, lon).

    Returns ``(records, latency_s)``.  ``records`` is empty when the point
    falls outside SSURGO coverage.  Coordinates use WKT POINT format
    (longitude latitude).
    """
    wkt = f"POINT({float(lon)} {float(lat)})"
    sql = _build_sql(wkt)
    t0 = time.perf_counter()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(_SDA_URL, data={"query": sql})
        resp.raise_for_status()
    latency = time.perf_counter() - t0
    records = _parse_xml(resp.text)
    return records, latency


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def ssurgo_query(
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    """Query USDA SSURGO soil data for a point location.

    Returns component and horizon data for the dominant soil map unit at the
    given location.  Data includes texture (sand/silt/clay), organic matter,
    pH, hydraulic conductivity, and bulk density for soil horizons.
    Coverage: CONUS + US territories.  No API key required.

    Args:
        latitude: Decimal degrees, WGS84 (-90 to 90).
        longitude: Decimal degrees, WGS84 (-180 to 180).
    """
    query_params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
    }

    t0 = time.perf_counter()
    try:
        records, latency = _fetch_ssurgo(latitude, longitude)
        return {
            "data": records,
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                variable_info=COLUMN_INFO,
                error=_NO_COVERAGE_MSG if not records else None,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                variable_info=COLUMN_INFO,
                success=False,
                error=str(exc),
            ),
        }


@mcp.tool()
def ssurgo_bbox_query(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> dict[str, Any]:
    """Query USDA SSURGO soil data for a bounding-box area.

    Uses the centroid of the bounding box to identify the dominant soil map
    unit.  Bounding boxes exceeding 10° in either dimension are clamped.

    Args:
        min_lat: South boundary, decimal degrees.
        max_lat: North boundary, decimal degrees.
        min_lon: West boundary, decimal degrees.
        max_lon: East boundary, decimal degrees.
    """
    bbox = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }
    bbox = clamp_bbox(bbox)
    clat, clon = bbox_centroid(bbox)

    query_params: dict[str, Any] = {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
        "centroid_lat": clat,
        "centroid_lon": clon,
    }

    t0 = time.perf_counter()
    try:
        records, latency = _fetch_ssurgo(clat, clon)
        return {
            "data": records,
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=len(records),
                latency_s=latency,
                license_info=LICENSE_INFO,
                variable_info=COLUMN_INFO,
                error=_NO_COVERAGE_MSG if not records else None,
            ),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "data": [],
            "_meta": build_meta(
                source="ssurgo",
                query_params=query_params,
                rows_returned=0,
                latency_s=latency,
                license_info=LICENSE_INFO,
                variable_info=COLUMN_INFO,
                success=False,
                error=str(exc),
            ),
        }
