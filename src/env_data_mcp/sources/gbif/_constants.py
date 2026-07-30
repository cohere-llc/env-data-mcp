"""Constants, enums, default variable lists, and URLs for the GBIF adapter."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

# ---------------------------------------------------------------------------
# License and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: MappingProxyType[str, str] = MappingProxyType(
    {
        "license": "Varies by dataset. See query results for license information.",
        "citation": "Varies by dataset. See query results for citation information.",
        "description": (
            "GBIF—the Global Biodiversity Information Facility—is an international "
            "network and data infrastructure funded by the world's governments and "
            "aimed at providing anyone, anywhere, open access to data about all "
            "types of life on Earth."
        ),
        "description_url": "https://www.gbif.org/what-is-gbif",
    }
)


# ---------------------------------------------------------------------------
# Type 1: occurrence
# ---------------------------------------------------------------------------

DEFAULT_OCCURRENCE_VARIABLES: frozenset[str] = frozenset(
    [
        "key",
        "datasetKey",
        "datasetName",
        "publishingOrgKey",
        "license",
        "basisOfRecord",
        "occurrenceStatus",
        "scientificName",
        "acceptedScientificName",
        "taxonRank",
        "taxonKey",
        "acceptedTaxonKey",
        "kingdom",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
        "species",
        "decimalLatitude",
        "decimalLongitude",
        "coordinateUncertaintyInMeters",
        "countryCode",
        "stateProvince",
        "eventDate",
        "year",
        "month",
        "individualCount",
        "recordedBy",
        "identifiedBy",
        "issues",
        "isSequenced",
    ]
)


# ---------------------------------------------------------------------------
# Query type info
# ---------------------------------------------------------------------------


class QueryType(StrEnum):
    """Identifier for each GBIF query endpoint; doubles as a cache key."""

    OCCURRENCE = "occurrence"


# Default variables by query type
DEFAULT_VARIABLES: MappingProxyType[QueryType, frozenset[str]] = MappingProxyType(
    {
        QueryType.OCCURRENCE: DEFAULT_OCCURRENCE_VARIABLES,
    }
)

# Endpoints by query type
QUERY_ENDPOINTS: MappingProxyType[QueryType, str] = MappingProxyType(
    {QueryType.OCCURRENCE: "https://api.gbif.org/v1/occurrence/search"}
)

# Results schema by query type -> { "query_type": { "url": str, "path": str } }
QUERY_RESULT_SCHEMAS: MappingProxyType[QueryType, dict[str, str]] = MappingProxyType(
    {
        QueryType.OCCURRENCE: {
            "url": "https://techdocs.gbif.org/openapi/occurrence.json",
            "path": "components.schemas.Occurrence.properties",
        },
    }
)

API_PAGE_SIZE = 300  # max records that can be returned for a single query
