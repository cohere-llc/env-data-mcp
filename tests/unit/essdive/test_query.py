"""Unit tests for the ESS-DIVE _query module.

All HTTP calls are mocked via ``pytest-httpx``; no network access required.
"""

from __future__ import annotations

from typing import Any

import pytest

from env_data_mcp.sources.essdive._constants import (
    BBox,
    DataFile,
    Package,
    Point,
)
from env_data_mcp.sources.essdive._query import (
    _build_headers,
    _extract_data_file,
    _extract_geometries,
    _extract_geometry,
    _extract_package,
    _extract_packages,
    _generate_geometry,
    _generate_response,
    _get_client,
    _query_for_packages,
    query_bbox,
    query_point,
)

from .conftest import (
    _API_KEY,
    _PACKAGES_RESPONSE,
)


def test_query_point(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_query_for_packages(client, params, api_key, default_geo):
        captured["client"] = client
        captured["params"] = params
        captured["api_key"] = api_key
        captured["default_geo"] = default_geo
        return ["sentinel-packages"]

    def fake_generate_response(packages):
        captured["generate_response_packages"] = packages
        return ["sentinel-response"]

    monkeypatch.setattr(
        "env_data_mcp.sources.essdive._query._query_for_packages", fake_query_for_packages
    )
    monkeypatch.setattr(
        "env_data_mcp.sources.essdive._query._generate_response", fake_generate_response
    )

    result = query_point(
        lat=46.25,
        lon=-119.48,
        radius_km=5.0,
        start_date="2020-01-01",
        end_date="2020-12-31",
        keywords=["soil"],
        api_key=_API_KEY,
    )

    assert captured["client"] is _get_client()
    assert captured["params"] == {
        "lat": 46.25,
        "lon": -119.48,
        "radius": 5.0 * 1000,
        "beginDate": "2020-01-01",
        "endDate": "2020-12-31",
        "keywords": ["soil"],
    }
    assert captured["api_key"] == _API_KEY
    assert captured["default_geo"] == Point(46.25, -119.48)
    assert captured["generate_response_packages"] == ["sentinel-packages"]
    assert result == ["sentinel-response"]


def test_query_bbox(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_query_for_packages(client, params, api_key, default_geo):
        captured["client"] = client
        captured["params"] = params
        captured["api_key"] = api_key
        captured["default_geo"] = default_geo
        return ["sentinel-packages"]

    def fake_generate_response(packages):
        captured["generate_response_packages"] = packages
        return ["sentinel-response"]

    monkeypatch.setattr(
        "env_data_mcp.sources.essdive._query._query_for_packages", fake_query_for_packages
    )
    monkeypatch.setattr(
        "env_data_mcp.sources.essdive._query._generate_response", fake_generate_response
    )

    result = query_bbox(
        min_lat=12.3,
        max_lat=15.4,
        min_lon=109.2,
        max_lon=110.3,
        start_date="2020-01-01",
        end_date="2020-12-31",
        keywords=["soil"],
        api_key=_API_KEY,
    )

    assert captured["client"] is _get_client()
    assert captured["params"] == {
        "bbox": "12.3,109.2,15.4,110.3",
        "beginDate": "2020-01-01",
        "endDate": "2020-12-31",
        "keywords": ["soil"],
    }
    assert captured["api_key"] == _API_KEY
    assert captured["default_geo"] == BBox(12.3, 109.2, 15.4, 110.3)
    assert captured["generate_response_packages"] == ["sentinel-packages"]
    assert result == ["sentinel-response"]


# ---------------------------------------------------------------------------
# _build_headers
# ---------------------------------------------------------------------------


def test_build_headers():
    header = _build_headers(_API_KEY)
    assert header == {"X-API-Key": _API_KEY, "Accept": "application/json"}


# ---------------------------------------------------------------------------
# package helpers
# ---------------------------------------------------------------------------


def test_extract_data_file():
    result: DataFile = _extract_data_file({})
    assert result.url == ""
    assert result.encoding == ""
    assert result.name == ""
    assert result.size_kb == 0

    result = _extract_data_file(
        {
            "contentUrl": "http://foo.com/bar/",
            "encodingFormat": "application/json",
            "name": "baz",
            "contentSize": 42,
        }
    )
    assert result.url == "http://foo.com/bar/"
    assert result.encoding == "application/json"
    assert result.name == "baz"
    assert result.size_kb == 42


def test_extract_geometry():
    with pytest.raises(KeyError):
        _: BBox = _extract_geometry({})
    result: BBox = _extract_geometry(
        {
            "@type": "Place",
            "description": "SPRUCE Experiment Site",
            "geo": [
                {
                    "@type": "GeoCoordinates",
                    "name": "Northwest",
                    "latitude": 47.50656,
                    "longitude": -93.45399,
                },
                {
                    "@type": "GeoCoordinates",
                    "name": "Southeast",
                    "latitude": 47.5047,
                    "longitude": -93.45256,
                },
            ],
        }
    )
    assert result.min_lat == 47.5047
    assert result.max_lat == 47.50656
    assert result.min_lon == -93.45399
    assert result.max_lon == -93.45256


def test_extract_geometries():
    result: list[BBox] = _extract_geometries([])
    assert result == []

    result = _extract_geometries(
        [
            {
                "@type": "Place",
                "description": "SPRUCE Experiment Site",
                "geo": [
                    {
                        "@type": "GeoCoordinates",
                        "name": "Northwest",
                        "latitude": 47.50656,
                        "longitude": -93.45399,
                    },
                    {
                        "@type": "GeoCoordinates",
                        "name": "Southeast",
                        "latitude": 47.5047,
                        "longitude": -93.45256,
                    },
                ],
            }
        ]
    )
    assert len(result) == 1
    assert result[0].min_lat == 47.5047
    assert result[0].max_lat == 47.50656
    assert result[0].min_lon == -93.45399
    assert result[0].max_lon == -93.45256

    result = _extract_geometries(
        [
            {
                "@type": "Place",
                "description": "SPRUCE Experiment Site",
                "geo": [
                    {
                        "@type": "GeoCoordinates",
                        "name": "Northwest",
                        "latitude": 47.50656,
                        "longitude": -93.45399,
                    },
                    {
                        "@type": "GeoCoordinates",
                        "name": "Southeast",
                        "latitude": 47.5047,
                        "longitude": -93.45256,
                    },
                ],
            },
            {
                "@type": "Place",
                "description": "ELM Experiment Site",
                "geo": [
                    {
                        "@type": "GeoCoordinates",
                        "name": "Northwest",
                        "latitude": 48.3,
                        "longitude": -92.4,
                    },
                    {
                        "@type": "GeoCoordinates",
                        "name": "Southeast",
                        "latitude": 48.1,
                        "longitude": -92.3,
                    },
                ],
            },
        ]
    )
    assert len(result) == 2
    assert result[0].min_lat == 47.5047
    assert result[0].max_lat == 47.50656
    assert result[0].min_lon == -93.45399
    assert result[0].max_lon == -93.45256
    assert result[1].min_lat == 48.1
    assert result[1].max_lat == 48.3
    assert result[1].min_lon == -92.4
    assert result[1].max_lon == -92.3


def test_extract_package():
    default_bbox: BBox = BBox(
        min_lat=24.3,
        max_lat=25.2,
        min_lon=108.4,
        max_lon=108.7,
    )
    result: Package = _extract_package(_PACKAGES_RESPONSE["result"][0], default_bbox)
    assert result.id == "ess-dive-b4ce9be3ed3df82-20260825T125458917"
    assert (
        result.url
        == "https://api.ess-dive.lbl.gov/packages/ess-dive-b4ce9be3ed3df82-20260825T125458917"
    )
    assert result.view_url == "https://data.ess-dive.lbl.gov/view/doi:10.25581/spruce.070/1546787"
    assert result.citation == "McPartland M Y; Falkowski M J; Reinhardt J R; Kane E S; Kolka R K"
    assert result.license == "http://creativecommons.org/licenses/by/4.0/"
    assert result.funder == (
        "U.S. DOE>Office of Science>Biological and Environmental Research;another funder"
    )
    assert result.geos == [
        BBox(
            min_lat=47.5047,
            max_lat=47.50656,
            min_lon=-93.45399,
            max_lon=-93.45256,
        )
    ]
    assert result.variables == ["reflectance"]
    assert result.techniques == [
        "Site Description\nThese data were collected at the Spruce and Peatland",
        "Methods\nThree scans were performed above each vegetation plot in the same",
    ]
    assert len(result.files) == 2
    assert result.files[0].name == "unispec_dataframe.csv"
    assert result.files[1].name == "whitereference_dataframe_parsed_dd.csv"

    result = _extract_package(_PACKAGES_RESPONSE["result"][1], default_bbox)
    assert result.id == "foo"
    assert result.geos == [
        BBox(
            min_lat=47.5047,
            max_lat=47.50656,
            min_lon=-93.45399,
            max_lon=-93.45256,
        ),
        BBox(
            min_lat=48.1,
            max_lat=48.3,
            min_lon=-92.4,
            max_lon=-92.3,
        ),
    ]

    result = _extract_package(_PACKAGES_RESPONSE["result"][2], default_bbox)
    assert result.id == ""
    assert result.url == ""
    assert result.view_url == ""
    assert result.citation == ""
    assert result.license == ""
    assert result.funder == ""
    assert result.geos == [default_bbox]
    assert result.variables == []
    assert result.techniques == []
    assert result.files == []


def test_extract_packages():
    default_bbox: BBox = BBox(
        min_lat=24.3,
        max_lat=25.2,
        min_lon=108.4,
        max_lon=108.7,
    )
    result: list[Package] = _extract_packages(_PACKAGES_RESPONSE["result"], default_bbox)
    assert len(result) == 3
    assert result[0].id == "ess-dive-b4ce9be3ed3df82-20260825T125458917"
    assert result[1].id == "foo"
    assert result[2].id == ""
    assert result[2].geos == [default_bbox]


@pytest.mark.usefixtures("_set_api_key", "_packages_mock")
def test_query_for_packages():
    client = _get_client()
    default_bbox: BBox = BBox(
        min_lat=24.3,
        max_lat=25.2,
        min_lon=108.4,
        max_lon=108.7,
    )
    result: list[Package] = _query_for_packages(client, {}, _API_KEY, default_bbox)
    assert len(result) == 3
    assert result[0].id == "ess-dive-b4ce9be3ed3df82-20260825T125458917"
    assert result[1].id == "foo"
    assert result[2].id == ""
    assert result[2].geos == [default_bbox]


# ---------------------------------------------------------------------------
# response helpers
# ---------------------------------------------------------------------------


def test_generate_geometry():
    result: dict[str, Any] = _generate_geometry(
        BBox(
            min_lat=12.4,
            max_lat=14.2,
            min_lon=119.2,
            max_lon=119.3,
        )
    )
    assert result == {
        "type": "Polygon",
        "coordinates": [
            [119.2, 12.4],
            [119.3, 12.4],
            [119.3, 14.2],
            [119.2, 14.2],
            [119.2, 12.4],
        ],
    }
    result = _generate_geometry(
        Point(
            lat=42.3,
            lon=98.6,
        )
    )
    assert result == {
        "type": "Point",
        "coordinates": [98.6, 42.3],
    }


def test_generate_response():
    result: list[dict[str, Any]] = _generate_response(
        [
            Package(
                id="foo",
                url="http://www.bar.com/baz",
                view_url="http://www.bar.com/view",
                citation="foo et al.",
                license="baz 2.0",
                funder="The Qux Institute",
                geos=[Point(13.2, 45.6)],
                variables=["quux", "corge"],
                techniques=["grault", "garply"],
                files=[
                    DataFile(
                        url="http://www.bar.com/file",
                        encoding="application/json",
                        name="waldo",
                        size_kb=24,
                    )
                ],
            ),
            Package(
                id="bar",
                url="http://www.foo.com/fred",
                view_url="http://www.foo.com/view",
                citation="bar et al.",
                license="plugh 2.0",
                funder="The Xyzzy Institute",
                geos=[BBox(42.3, 108.4, 45.6, 110.3)],
                variables=["thud", "grault"],
                techniques=["corge"],
                files=[
                    DataFile(
                        url="http://www.foo.com/file",
                        encoding="application/json",
                        name="fred",
                        size_kb=42,
                    )
                ],
            ),
        ]
    )
    assert result == [
        {
            "geometry": {"type": "Point", "coordinates": [45.6, 13.2]},
            "records": [
                {
                    "id": "foo",
                    "url": "http://www.bar.com/baz",
                    "view_url": "http://www.bar.com/view",
                    "citation": "foo et al.",
                    "license": "baz 2.0",
                    "funder": "The Qux Institute",
                    "variables": ["quux", "corge"],
                    "techniques": ["grault", "garply"],
                    "files": [
                        {
                            "url": "http://www.bar.com/file",
                            "encoding": "application/json",
                            "name": "waldo",
                            "size_kb": 24,
                        }
                    ],
                },
            ],
        },
        {
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [108.4, 42.3],
                    [110.3, 42.3],
                    [110.3, 45.6],
                    [108.4, 45.6],
                    [108.4, 42.3],
                ],
            },
            "records": [
                {
                    "id": "bar",
                    "url": "http://www.foo.com/fred",
                    "view_url": "http://www.foo.com/view",
                    "citation": "bar et al.",
                    "license": "plugh 2.0",
                    "funder": "The Xyzzy Institute",
                    "variables": ["thud", "grault"],
                    "techniques": ["corge"],
                    "files": [
                        {
                            "url": "http://www.foo.com/file",
                            "encoding": "application/json",
                            "name": "fred",
                            "size_kb": 42,
                        }
                    ],
                },
            ],
        },
    ]
