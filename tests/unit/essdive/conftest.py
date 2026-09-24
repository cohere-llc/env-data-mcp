"""Shared fixtures and mock endpoints for ESS-DIVE unit tests."""

from __future__ import annotations

import re
import sqlite3

import pytest
from hishel import FilterPolicy, SyncSqliteStorage
from hishel.httpx import SyncCacheClient

from env_data_mcp.sources.essdive._constants import ESSDIVE_BASE_URL
from env_data_mcp.sources.essdive._query import _SuccessOnlyFilter

_LAT = 46.2531882
_LON = -119.4768203
_API_KEY = "test-api-key-1234"

_PACKAGES_RESPONSE = {
    "nextCursor": False,
    "result": [
        {
            "id": "ess-dive-b4ce9be3ed3df82-20260825T125458917",
            "viewUrl": "https://data.ess-dive.lbl.gov/view/doi:10.25581/spruce.070/1546787",
            "url": "https://api.ess-dive.lbl.gov/packages/ess-dive-b4ce9be3ed3df82-20260825T125458917",
            "next": None,
            "previous": "https://api.ess-dive.lbl.gov/packages/ess-dive-f021c132e173963-20260817T172433443",
            "dateUploaded": "2026-08-25T12:55:01.554Z",
            "dateModified": "2026-08-25T12:55:01.646Z",
            "isPublic": True,
            "citation": "McPartland M Y; Falkowski M J; Reinhardt J R; Kane E S; Kolka R K",
            "dataset": {
                "@context": "http://schema.org/",
                "@type": "Dataset",
                "@id": "doi:10.25581/spruce.070/1546787",
                "name": "SPRUCE Hyperspectral Remote Sensing of Vegetation Communities in SPRUCE",
                "description": [
                    "This dataset consists of reflectance observations from hyperspectral remote",
                    "Data collection was performed using a PP Systems UniSpec-DC spectroradiometer",
                    "This dataset contains 4 data files in comma-separate values (*.csv) format",
                ],
                "alternateName": ["10.25581/spruce.070/1546787", "spruce.070", "OSTI ID: 1546787"],
                "creator": [
                    {
                        "@type": "Person",
                        "@id": "https://orcid.org/0000-0002-1242-0438",
                        "givenName": "Mara Y.",
                        "familyName": "McPartland",
                        "affiliation": "University of Minnesota, Saint Paul, MN (United States)",
                        "email": "mara.mcpartland@uni-leipzig.de",
                    },
                    {
                        "@type": "Person",
                        "givenName": "Michael J.",
                        "familyName": "Falkowski",
                        "affiliation": "Colorado State University, Fort Collins, CO",
                    },
                ],
                "datePublished": "2019-07-27",
                "keywords": [
                    "Peatland",
                    "species diversity",
                    "remote sensing",
                    "Spruce and Peatland Responses Under Changing Environments",
                    "SPRUCE Experiment",
                    "land cover",
                    "Marcell Experimental Forest",
                    "boreal",
                    "hyperspectral",
                    "ESS-DIVE File Level Metadata Reporting Format",
                    "ESS-DIVE CSV File Formatting Guidelines Reporting Format",
                ],
                "variableMeasured": ["reflectance"],
                "license": "http://creativecommons.org/licenses/by/4.0/",
                "spatialCoverage": [
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
                ],
                "award": ["DEAC0500OR22725"],
                "funder": [
                    {
                        "@type": "Organization",
                        "@id": "http://dx.doi.org/10.13039/100006206",
                        "name": "U.S. DOE>Office of Science>Biological and Environmental Research",
                    },
                    {"name": "another funder"},
                ],
                "temporalCoverage": {
                    "startDate": "2016-09-22",
                    "endDate": "2016-09-22",
                    "@type": "DateTime",
                },
                "editor": {
                    "@type": "Person",
                    "@id": "https://orcid.org/0000-0002-1242-0438",
                    "givenName": "Mara Y.",
                    "familyName": "McPartland",
                    "affiliation": "University of Minnesota, Saint Paul, MN (United States)",
                    "email": "mara.mcpartland@uni-leipzig.de",
                },
                "citation": [
                    "McPartland, Mara Y., Falkowski, Michael J., Reinhardt, Jason R., Kane,",
                    "Hanson, P.J., J.S. Riggs, W.R. Nettles, J.R. Phillips, M.B. Krassovski,",
                    "McPartland, Mara Y., Falkowski, Michael J., Reinhardt, Jason R., Kane,",
                    "Harris, A.; Gamon, J.A.; Pastorello, G.;Wong, C. Retrieval of the",
                    "Wang, R.; Gamon, J.A.; Emmerton, C.A.; Li, H.; Nestola, E.; Pastorello, G.Z",
                ],
                "provider": {
                    "@type": "Organization",
                    "identifier": {
                        "@type": "PropertyValue",
                        "propertyID": "ess-dive",
                        "value": "1e6d50d3-9532-43fb-a63f-bdcb4350bf0c",
                    },
                    "name": "ORNL Terrestrial Ecosystem Science SFA",
                    "member": {
                        "@type": "Person",
                        "givenName": "Melanie",
                        "familyName": "Mayes",
                        "jobTitle": "Principal Investigator",
                        "affiliation": "Oak Ridge National Laboratory",
                        "email": "mayesma@ornl.gov",
                    },
                },
                "measurementTechnique": [
                    "Site Description\nThese data were collected at the Spruce and Peatland",
                    "Methods\nThree scans were performed above each vegetation plot in the same",
                ],
                "distribution": [
                    {
                        "contentUrl": "https://data.ess-dive.lbl.gov/catalog/d1/mn/v2/object/ess-dive-d7f15d062eda7fd-20260805T151737331",
                        "encodingFormat": "application/octet-stream",
                        "identifier": "ess-dive-d7f15d062eda7fd-20260805T151737331",
                        "name": "unispec_dataframe.csv",
                        "contentSize": 1402.1103515625,
                    },
                    {
                        "contentUrl": "https://data.ess-dive.lbl.gov/catalog/d1/mn/v2/object/ess-dive-89993e6d09b78f2-20260805T151737340",
                        "encodingFormat": "text/csv",
                        "identifier": "ess-dive-89993e6d09b78f2-20260805T151737340",
                        "name": "whitereference_dataframe_parsed_dd.csv",
                        "contentSize": 0.5400390625,
                    },
                ],
            },
        },
        {
            "id": "foo",
            "dataset": {},
            "spatialCoverage": [
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
            ],
        },
        {
            "dataset": {},
        },
    ],
}


@pytest.fixture(autouse=True)
def _result_client_cache(monkeypatch):
    monkeypatch.setattr(
        "env_data_mcp.sources.essdive._query._client",
        SyncCacheClient(
            policy=FilterPolicy(response_filters=[_SuccessOnlyFilter()]),
            storage=SyncSqliteStorage(
                connection=sqlite3.connect(":memory:", check_same_thread=False)
            ),
            timeout=30.0,
        ),
    )


@pytest.fixture
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ESSDIVE_TOKEN", _API_KEY)


@pytest.fixture
def _unset_api_key(monkeypatch):
    monkeypatch.delenv("ESSDIVE_TOKEN", raising=False)


@pytest.fixture
def _packages_mock(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(rf"^{re.escape(ESSDIVE_BASE_URL)}packages(\?.*)?$"),
        json=_PACKAGES_RESPONSE,
        is_reusable=True,
    )
