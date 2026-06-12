"""WCS Client for accessing SoilGrids data."""

from owslib.coverage.wcs100 import WebCoverageService_1_0_0
from owslib.wcs import WebCoverageService

from .constants import _QUANTILES, _WEB_MAP_SERVICE_URL

_clients: dict[str, WebCoverageService_1_0_0] = {}


def get_client(base_variable: str) -> WebCoverageService_1_0_0:
    global _clients
    if base_variable in _clients:
        return _clients[base_variable]
    wcs = WebCoverageService(
        f"{_WEB_MAP_SERVICE_URL}?map=/map/{base_variable}.map", version="1.0.0"
    )
    if not isinstance(wcs, WebCoverageService_1_0_0):
        raise TypeError(f"Expected WCS 1.0.0 client, got {type(wcs).__name__}")
    _client = wcs
    return _client


def get_specific_variable_info(base_variable: str) -> dict[str, tuple[str, str]]:
    """Get specifc variables for a base variable with depth interval and quantile."""
    client = get_client(base_variable=base_variable)
    result: dict[str, tuple[str, str]] = {}
    for var in list(client.contents):
        parts = var.split("_")
        if len(parts) != 3:
            msg = f"Error parsing variable: {var}"
            raise ValueError(msg)
        result[var] = parts[1], _QUANTILES.get(parts[2]) or parts[2]
    return result
