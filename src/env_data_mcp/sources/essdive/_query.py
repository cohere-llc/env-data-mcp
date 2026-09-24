"""Query logic for the ESS-DIVE adapter.

See https://api.ess-dive.lbl.gov/ for ESS-DIVE API details.
"""

from http import HTTPStatus
from typing import Any

from hishel import BaseFilter, FilterPolicy, Response
from hishel.httpx import SyncCacheClient

from ._constants import ESSDIVE_BASE_URL, BBox, DataFile, Package, Point

_KM_TO_M = 1000

_client: SyncCacheClient | None = None


class _SuccessOnlyFilter(BaseFilter[Response]):
    def needs_body(self) -> bool:
        return False

    def apply(self, item: Response, body: bytes | None) -> bool:
        return item.status_code == HTTPStatus.OK


def _get_client() -> SyncCacheClient:
    global _client
    if _client is None:
        _client = SyncCacheClient(
            policy=FilterPolicy(response_filters=[_SuccessOnlyFilter()]),
            timeout=30.0,
        )
    return _client


def query_point(
    lat: float,
    lon: float,
    radius_km: float,
    start_date: str | None = None,
    end_date: str | None = None,
    keywords: list[str] | None = None,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Queries for datasets within radius_km of a point location.

    Returns either an empty list (no datasets for location, time range, and
    keywords(when included)) or a list of datasets grouped by a GeoJSON ``Polygon``
    geometry that corresponds to the studied region for each dataset.

    If ``keywords`` is omitted, all datasets for the location and time range
    are returned. If ``api_key`` is omitted, only public datasets are returned.
    If `start_date` and/or `end_date` are omitted, the bound is not applied to the query.
    """
    client = _get_client()
    params: dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "radius": radius_km * _KM_TO_M,
    }
    if start_date:
        params["beginDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    if keywords:
        params["keywords"] = keywords
    packages = _query_for_packages(client, params, api_key, Point(lat, lon))
    return _generate_response(packages)


def query_bbox(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str | None = None,
    end_date: str | None = None,
    keywords: list[str] | None = None,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Queries for datasets within a bounding-box location.

    Returns either an empty list (no datasets for location, time range, and
    keywords(when included)) or a list of datasets grouped by a GeoJSON ``Polygon``
    geometry that corresponds to the studied region for each dataset.

    If ``keywords`` is omitted, all datasets for the location and time range
    are returned. If ``api_key`` is omitted, only public datasets are returned.
    If `start_date` and/or `end_date` are omitted, the bound is not applied to the query.
    """
    client = _get_client()
    params: dict[str, Any] = {
        "bbox": f"{min_lat},{min_lon},{max_lat},{max_lon}",
    }
    if start_date:
        params["beginDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    if keywords:
        params["keywords"] = keywords
    packages = _query_for_packages(
        client,
        params,
        api_key,
        BBox(min_lat=min_lat, min_lon=min_lon, max_lat=max_lat, max_lon=max_lon),
    )
    return _generate_response(packages)


# ---------------------------------------------------------------------------
# auth helper
# ---------------------------------------------------------------------------


def _build_headers(api_key: str | None) -> dict[str, str] | None:
    return {"X-API-Key": api_key, "Accept": "application/json"} if api_key else None


# ---------------------------------------------------------------------------
# package helpers
# ---------------------------------------------------------------------------


def _extract_data_file(data: dict[str, Any]) -> DataFile:
    return DataFile(
        url=data.get("contentUrl", ""),
        encoding=data.get("encodingFormat", ""),
        name=data.get("name", ""),
        size_kb=data.get("contentSize", 0),
    )


def _extract_geometry(data: dict[str, Any]) -> BBox:
    min_lat: float = 0
    max_lat: float = 0
    min_lon: float = 0
    max_lon: float = 0
    for corner in data["geo"]:
        if corner["name"] == "Northwest":
            max_lat = corner["latitude"]
            min_lon = corner["longitude"]
        if corner["name"] == "Southeast":
            min_lat = corner["latitude"]
            max_lon = corner["longitude"]
    return BBox(
        min_lat=min_lat,
        min_lon=min_lon,
        max_lat=max_lat,
        max_lon=max_lon,
    )


def _extract_geometries(geos: list[dict[str, Any]]) -> list[BBox]:
    bboxes: list[BBox] = []
    if geos:
        if isinstance(geos, list):
            for geo in geos:
                bboxes.append(_extract_geometry(geo))
        else:
            bboxes.append(_extract_geometry(geos))
    return bboxes


def _extract_package(data: dict[str, Any], default_geo: BBox | Point) -> Package:
    dataset = data["dataset"]
    geos: list[BBox | Point] = []
    if bboxes := data.get("spatialCoverage"):
        geos.extend(_extract_geometries(bboxes))
    if bboxes := dataset.get("spatialCoverage"):
        geos.extend(_extract_geometries(bboxes))
    if not geos:
        geos.append(default_geo)
    dists: list[dict[str, Any]] = data.get("distribution", [])
    dists.extend(dataset.get("distribution", []))
    return Package(
        id=data.get("id", ""),
        url=data.get("url", ""),
        view_url=data.get("viewUrl", ""),
        citation=data.get("citation", ""),
        license=dataset.get("license", ""),
        funder=";".join([org.get("name", "") for org in dataset.get("funder", [])]),
        geos=geos,
        variables=dataset.get("variableMeasured", []),
        techniques=dataset.get("measurementTechnique", []),
        files=[_extract_data_file(dist) for dist in dists],
    )


def _extract_packages(data: list[dict[str, Any]], default_geo: BBox | Point) -> list[Package]:
    packages: list[Package] = []
    for item in data:
        packages.append(_extract_package(item, default_geo))
    return packages


def _query_for_packages(
    client: SyncCacheClient, params: dict[str, Any], api_key: str | None, default_geo: BBox | Point
) -> list[Package]:
    resp = client.get(f"{ESSDIVE_BASE_URL}packages", params=params, headers=_build_headers(api_key))
    # ESS-DIVE returns a 404 error when no records are found, even though the search ran
    # properly
    if resp.status_code == HTTPStatus.NOT_FOUND:
        return []
    resp.raise_for_status()
    packages: list[Package] = []
    packages.extend(_extract_packages(resp.json()["result"], default_geo))
    while resp.json()["nextCursor"]:
        params["cursor"] = resp.json()["nextCursor"]
        resp = client.get(
            f"{ESSDIVE_BASE_URL}packages", params=params, headers=_build_headers(api_key)
        )
        # ESS-DIVE returns a 404 error when no records are found, even though the search ran
        # properly
        if resp.status_code == HTTPStatus.NOT_FOUND:
            return []
        resp.raise_for_status()
        packages.extend(_extract_packages(resp.json()["result"], default_geo))
    return packages


# ---------------------------------------------------------------------------
# response helpers
# ---------------------------------------------------------------------------


def _generate_geometry(geo: BBox | Point) -> dict[str, Any]:
    if isinstance(geo, BBox):
        return {
            "type": "Polygon",
            "coordinates": [
                [geo.min_lon, geo.min_lat],
                [geo.max_lon, geo.min_lat],
                [geo.max_lon, geo.max_lat],
                [geo.min_lon, geo.max_lat],
                [geo.min_lon, geo.min_lat],
            ],
        }
    return {
        "type": "Point",
        "coordinates": [geo.lon, geo.lat],
    }


def _generate_response(packages: list[Package]) -> list[dict[str, Any]]:
    return [
        {
            "geometry": _generate_geometry(geo),
            "records": [
                {
                    "id": package.id,
                    "url": package.url,
                    "view_url": package.view_url,
                    "citation": package.citation,
                    "license": package.license,
                    "funder": package.funder,
                    "variables": package.variables,
                    "techniques": package.techniques,
                    "files": [
                        {
                            "url": file.url,
                            "encoding": file.encoding,
                            "name": file.name,
                            "size_kb": file.size_kb,
                        }
                        for file in package.files
                    ],
                }
            ],
        }
        for package in packages
        for geo in package.geos
    ]
