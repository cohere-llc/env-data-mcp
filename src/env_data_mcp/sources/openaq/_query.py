"""Query logic for the OpenAQ adapter.

See https://api.openaq.org/docs#/v3/ for OpenAQ API details.
"""

import time
from http import HTTPStatus
from types import MappingProxyType
from typing import Any

import httpx
from hishel import BaseFilter, FilterPolicy, Response
from hishel.httpx import SyncCacheClient

from ._constants import OPENAQ_BASE_URL, Location, Parameter, Sensor

_KM_TO_M = 1000

_AVAILABLE_PARAMETERS: MappingProxyType[int, Parameter] | None = None

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


def _get_with_retry(
    client: SyncCacheClient,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    max_retries: int = 3,
) -> httpx.Response:
    resp = client.get(url, headers=headers, params=params)
    for attempt in range(max_retries):
        if resp.status_code != HTTPStatus.TOO_MANY_REQUESTS:
            return resp
        wait = int(resp.headers.get("Retry-After", 60 * attempt))
        time.sleep(wait)
        resp = client.get(url, headers=headers, params=params)
    return resp


def get_variable_info(api_key: str) -> dict[str, dict[str, str]]:
    """Returns the set of available variables with descriptions and units."""
    client = _get_client()
    return {
        param.name: {
            "description": param.description if param.description is not None else param.name,
            "units": param.units,
        }
        for param in _fetch_parameters(client, api_key).values()
    }


def query_point(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    radius_km: float,
    variables: list[str],
    api_key: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Queries for specified measurements for a point location and date range.

    Returns ``(groups, unavailable_variables)`` where ``groups`` is either an
    empty list (no data for location and time range) or a list of records grouped
    by GeoJSON ``Point`` geometry and containing a time-series of data in
    ``records``.
    """
    client = _get_client()
    param_ids: list[int] = [
        param.id for param in _fetch_parameters(client, api_key).values() if param.name in variables
    ]
    locations = _fetch_point_locations(client, api_key, lat, lon, radius_km, param_ids)
    results = _fetch_measurements(client, api_key, locations, start_date, end_date)
    return results, _collect_unavailable_variables(results, variables)


def query_bbox(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: str,
    end_date: str,
    variables: list[str],
    api_key: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Queries for specified measurements for a bounding-box location and date range.

    Returns ``(groups, unavailable_variables)`` where ``groups`` is either an
    empty list (no data for location and time range) or a list of records grouped
    by GeoJSON ``Point`` geometry and containing a time-series of data in
    ``records``.
    """
    client = _get_client()
    param_ids: list[int] = [
        param.id for param in _fetch_parameters(client, api_key).values() if param.name in variables
    ]
    locations = _fetch_bbox_locations(
        client, api_key, min_lat, max_lat, min_lon, max_lon, param_ids
    )
    results = _fetch_measurements(client, api_key, locations, start_date, end_date)
    return results, _collect_unavailable_variables(results, variables)


# ---------------------------------------------------------------------------
# auth helper
# ---------------------------------------------------------------------------


def _build_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Accept": "application/json"}


# ---------------------------------------------------------------------------
# parameters helper
# ---------------------------------------------------------------------------


def _extract_parameter(data: dict[str, Any]) -> Parameter:
    """Extract parameter data from json response."""
    return Parameter(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        units=data["units"],
    )


def _fetch_parameters(client: SyncCacheClient, api_key: str) -> MappingProxyType[int, Parameter]:
    global _AVAILABLE_PARAMETERS
    if _AVAILABLE_PARAMETERS is None:
        resp = _get_with_retry(
            client,
            f"{OPENAQ_BASE_URL}/parameters",
            headers=_build_headers(api_key),
        )
        resp.raise_for_status()
        _AVAILABLE_PARAMETERS = MappingProxyType(
            {
                (param := _extract_parameter(item)).id: param
                for item in resp.json().get("results", [])
            }
        )
    return _AVAILABLE_PARAMETERS


def _collect_unavailable_variables(
    results: list[dict[str, Any]], variables: list[str]
) -> list[str]:
    return [
        var
        for var in variables
        if var not in {key for geom in results for rec in geom.get("records", []) for key in rec}
    ]


# ---------------------------------------------------------------------------
# location helpers
# ---------------------------------------------------------------------------


def _extract_location(data: dict[str, Any], parameter_ids: list[int]) -> Location | None:
    """Extract location data from json response."""
    sensors: list[Sensor] = [
        Sensor(id=sensor["id"], parameter_id=sensor["parameter"]["id"])
        for sensor in data.get("sensors", [])
        if sensor["parameter"]["id"] in parameter_ids
    ]
    return (
        Location(
            id=data["id"],
            lat=data["coordinates"]["latitude"],
            lon=data["coordinates"]["longitude"],
            sensors=sensors,
            name=data.get("name"),
        )
        if sensors
        else None
    )


def _fetch_point_locations(
    client: SyncCacheClient,
    api_key: str,
    lat: float,
    lon: float,
    radius_km: float,
    parameter_ids: list[int],
) -> list[Location]:
    """Fetch locations near a point location."""
    resp = _get_with_retry(
        client,
        f"{OPENAQ_BASE_URL}/locations",
        params={"coordinates": f"{lat},{lon}", "radius": f"{radius_km * _KM_TO_M}"},
        headers=_build_headers(api_key),
    )
    resp.raise_for_status()
    return [
        loc
        for item in resp.json().get("results", [])
        if (loc := _extract_location(item, parameter_ids)) is not None
    ]


def _fetch_bbox_locations(
    client: SyncCacheClient,
    api_key: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    parameter_ids: list[int],
) -> list[Location]:
    """Fetch locations within a bounding box."""
    resp = _get_with_retry(
        client,
        f"{OPENAQ_BASE_URL}/locations",
        params={"bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}"},
        headers=_build_headers(api_key),
    )
    resp.raise_for_status()
    return [
        loc
        for item in resp.json().get("results", [])
        if (loc := _extract_location(item, parameter_ids)) is not None
    ]


# ---------------------------------------------------------------------------
# measurement helpers
# ---------------------------------------------------------------------------


def _fetch_sensor_measurements(
    client: SyncCacheClient, api_key: str, sensor: Sensor, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    """Fetch measurements from one sensor over a date range."""
    param = _fetch_parameters(client, api_key)[sensor.parameter_id]
    resp = _get_with_retry(
        client,
        f"{OPENAQ_BASE_URL}/sensors/{sensor.id}/measurements",
        params={
            "date_from": f"{start_date}T00:00:00Z",
            "date_to": f"{end_date}T23:59:59Z",
        },
        headers=_build_headers(api_key),
    )
    resp.raise_for_status()
    recs = resp.json().get("results", [])
    return [
        {
            "datetime": rec["period"],
            f"{param.name}": rec["value"],
            f"{param.name}_units": param.units,
        }
        for rec in recs
    ]


def _fetch_measurements(
    client: SyncCacheClient,
    api_key: str,
    locations: list[Location],
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Fetch measurements for specified locations and all included sensors.

    Each group carries the OpenAQ location's ``station_id`` and ``station_name`` so a
    caller can link a group back to the station (``https://explore.openaq.org/locations/<id>``).
    """
    results: list[dict[str, Any]] = []
    for location in locations:
        location_records: list[dict[str, Any]] = []
        for sensor in location.sensors:
            location_records.extend(
                _fetch_sensor_measurements(client, api_key, sensor, start_date, end_date)
            )
        results.append(
            {
                "station_id": location.id,
                "station_name": location.name,
                "geometry": {"type": "Point", "coordinates": [location.lon, location.lat]},
                "latitude": location.lat,
                "longitude": location.lon,
                "records": location_records,
            }
        )
    return results
