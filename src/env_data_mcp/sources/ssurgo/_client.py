from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from .constants import _SDA_URL, _XS_NS


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


_WFS_URL = "https://sdmdataaccess.sc.egov.usda.gov/Spatial/SDMWGS84Geographic.wfs"
_WFS_MAX_FEATURES = 500


def _parse_gml2_coords(coords_text: str) -> list[list[float]]:
    """Parse a GML2 ``lat,lon`` coordinate string into a GeoJSON ``[lon, lat]`` ring."""
    ring: list[list[float]] = []
    for pair in coords_text.strip().split():
        parts = pair.split(",")
        if len(parts) >= 2:
            try:
                lat, lon = float(parts[0]), float(parts[1])
                ring.append([lon, lat])
            except ValueError:
                continue
    return ring


def _gml2_to_geojson(gml_text: str, mukeys: set[str]) -> dict[str, dict[str, Any]]:
    """Parse a GML2 WFS response; return mukey → GeoJSON geometry for *mukeys* only.

    Multiple WFS features sharing the same mukey are merged into a single
    MultiPolygon.
    """
    try:
        root = ET.fromstring(gml_text)
    except ET.ParseError:
        return {}

    GML_NS = "http://www.opengis.net/gml"
    MS_NS = "http://mapserver.gis.umn.edu/mapserver"

    # Collect every polygon (as a list-of-rings) per mukey.
    mukey_polygons: dict[str, list[list[list[list[float]]]]] = {}
    for feat in root.findall(f".//{{{MS_NS}}}mapunitpoly"):
        mk_el = feat.find(f"{{{MS_NS}}}mukey")
        if mk_el is None or mk_el.text not in mukeys:
            continue
        mk = mk_el.text
        for poly in feat.findall(f".//{{{GML_NS}}}Polygon"):
            rings: list[list[list[float]]] = []
            outer = poly.find(f"{{{GML_NS}}}outerBoundaryIs//{{{GML_NS}}}coordinates")
            if outer is not None and outer.text:
                rings.append(_parse_gml2_coords(outer.text))
            for inner_el in poly.findall(f"{{{GML_NS}}}innerBoundaryIs//{{{GML_NS}}}coordinates"):
                if inner_el.text:
                    rings.append(_parse_gml2_coords(inner_el.text))
            if rings and rings[0]:
                mukey_polygons.setdefault(mk, []).append(rings)

    result: dict[str, dict[str, Any]] = {}
    for mk, polygons in mukey_polygons.items():
        if len(polygons) == 1:
            result[mk] = {"type": "Polygon", "coordinates": polygons[0]}
        else:
            result[mk] = {"type": "MultiPolygon", "coordinates": polygons}
    return result


def _fetch_mukey_geometries(
    mukeys: list[str], bbox: tuple[float, float, float, float]
) -> dict[str, dict[str, Any]]:
    """Fetch GeoJSON polygon geometry for each mukey via the SDA WFS endpoint.

    *bbox* is ``(min_lon, min_lat, max_lon, max_lat)`` in WGS-84.  For point
    queries, callers should expand the point by a small buffer before passing
    it here.

    Returns a dict mapping mukey → GeoJSON geometry dict.  Mukeys whose
    geometry cannot be fetched or parsed are silently omitted.
    """
    if not mukeys:
        return {}
    min_lon, min_lat, max_lon, max_lat = bbox
    bbox_filter = (
        f"<Filter><BBOX><PropertyName>Geometry</PropertyName>"
        f"<Box srsName='EPSG:4326'>"
        f"<coordinates>{min_lon},{min_lat} {max_lon},{max_lat}</coordinates>"
        f"</Box></BBOX></Filter>"
    )
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                _WFS_URL,
                params={
                    "SERVICE": "WFS",
                    "VERSION": "1.1.0",
                    "REQUEST": "GetFeature",
                    "TYPENAME": "mapunitpoly",
                    "FILTER": bbox_filter,
                    "OUTPUTFORMAT": "GML2",
                    "MAXFEATURES": str(_WFS_MAX_FEATURES),
                },
            )
            resp.raise_for_status()
    except Exception:
        return {}
    return _gml2_to_geojson(resp.text, set(mukeys))
