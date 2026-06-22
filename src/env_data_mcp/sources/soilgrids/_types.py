"""Types for SoilGrid adapter."""

from typing import TypeAlias

from owslib.coverage.wcs100 import WebCoverageService_1_0_0

# type alias in case we want to change versions in the future
Client: TypeAlias = WebCoverageService_1_0_0
