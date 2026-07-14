"""Full set of adapter specs for live integration tests."""

from .common import AdapterSpec
from .test_nasa_power_live import MERRA2_SPEC, SYN1DEG_SPEC

ALL_ADAPTER_SPECS: list[AdapterSpec] = [
    # NASA POWER specs
    MERRA2_SPEC,
    SYN1DEG_SPEC,
]
