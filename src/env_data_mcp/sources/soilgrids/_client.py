"""WCS Client for accessing SoilGrids data.

Clients are used to interact with coverage classes (soil density, pH, silt content, etc.)
and give access to specific coverages (for specific depth ranges and quantiles). So, a
client for `bdod` (soil density) would give access to coverages like:
`bdod_0-5cm_mean` (mean soil density at 0-5cm depth)
`bdod_15-30cm_Q0.5` (median soil density at 15-30cm depth)
"""

from owslib.wcs import WebCoverageService

from ._constants import WEB_MAP_SERVICE_URL
from ._types import Client

# Global cache for WCS clients by coverage class
_clients: dict[str, Client] = {}


def get_client(base_variable: str) -> Client:
    """Get a WCS client for a particular coverage category."""
    global _clients
    if base_variable in _clients:
        return _clients[base_variable]

    wcs = WebCoverageService(f"{WEB_MAP_SERVICE_URL}?map=/map/{base_variable}.map", version="1.0.0")
    if not isinstance(wcs, Client):
        raise TypeError(f"Expected WCS 1.0.0 client, got {type(wcs).__name__}")

    _clients[base_variable] = wcs
    return wcs
