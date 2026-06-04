"""Constants, enums, default variable lists, and URLs for the GBIF adapter."""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# License and metadata
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, str] = {
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


# ---------------------------------------------------------------------------
# Type 1: occurrence
# ---------------------------------------------------------------------------

_DEFAULT_OCCURRENCE_VARIABLES: list[str] = [
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


# ---------------------------------------------------------------------------
# Query type info
# ---------------------------------------------------------------------------


class _QueryType(StrEnum):
    """Identifier for each GBIF query endpoint; doubles as a cache key."""

    OCCURRENCE = "occurrence"


# Default variables by query type
_DEFAULT_VARIABLES: dict[_QueryType, list[str]] = {
    _QueryType.OCCURRENCE: _DEFAULT_OCCURRENCE_VARIABLES,
}

# Endpoints by query type
_QUERY_ENDPOINTS: dict[_QueryType, str] = {
    _QueryType.OCCURRENCE: "https://api.gbif.org/v1/occurrence/search"
}

# Results schema by query type -> { "query_type": { "url": str, "path": str } }
_QUERY_RESULT_SCHEMAS: dict[_QueryType, dict[str, str]] = {
    _QueryType.OCCURRENCE: {
        "url": "https://techdocs.gbif.org/openapi/occurrence.json",
        "path": "components.schemas.Occurrence.properties",
    },
}
