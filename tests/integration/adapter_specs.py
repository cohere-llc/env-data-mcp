"""Full set of adapter specs for live integration tests."""

from .common import AdapterSpec
from .test_gbif_live import OCCURRENCE_SPEC as GBIF_OCCURRENCE_SPEC
from .test_nasa_power_live import MERRA2_SPEC, SYN1DEG_SPEC
from .test_soilgrids_live import SOILGRIDS_SPEC
from .test_ssurgo_live import ALL_SSURGO_SPECS

ALL_ADAPTER_SPECS: list[AdapterSpec] = [
    # NASA POWER specs
    MERRA2_SPEC,
    SYN1DEG_SPEC,
    # GBIF specs
    GBIF_OCCURRENCE_SPEC,
    # SoilGrids specs
    SOILGRIDS_SPEC,
    # SSURGO specs (7 variable-based query types; soil_suitability excluded — uses rule_names)
    *ALL_SSURGO_SPECS,
]
