"""USDA SSURGO soil data adapter.

Data source: USDA Web Soil Survey Soil Data Access (SDA)
  ``https://sdmdataaccess.nrcs.usda.gov/``
Coverage: Continental US + territories; no auth required
Auth required: No

Query types provided
--------------------
+-------------------------------+----------------------------------------------------+
| Tool prefix                   | Tables / data returned                             |
+===============================+====================================================+
| ssurgo_soil_profile_*         | mapunit → component → chorizon                     |
|                               | Per-horizon physical/chemical properties:          |
|                               | texture, pH, organic matter, hydraulics.           |
+-------------------------------+----------------------------------------------------+
| ssurgo_area_summary_*         | mapunit → muaggatt                                 |
|                               | NRCS pre-aggregated map-unit summary: drainage,    |
|                               | hydrologic group, available water capacity, SOC    |
|                               | stock, crop productivity index, flood class.       |
+-------------------------------+----------------------------------------------------+
| ssurgo_subsurface_barriers_*  | mapunit → component → corestrictions               |
|                               | Depth to hard layers limiting rooting, drainage,   |
|                               | or excavation (bedrock, fragipan, duripan, etc.)   |
+-------------------------------+----------------------------------------------------+
| ssurgo_seasonal_hydrology_*   | mapunit → component → comonth → cosoilmoist        |
|                               | Monthly flooding/ponding and water table depth     |
|                               | (12 rows per component, Jan–Dec).                  |
+-------------------------------+----------------------------------------------------+
| ssurgo_soil_suitability_*     | mapunit → component → cointerp                     |
|                               | Pre-computed NRCS suitability ratings by rule.     |
|                               | Use ``rule_names`` to select interpretations.      |
+-------------------------------+----------------------------------------------------+
| ssurgo_ecological_site_*      | mapunit → component → coecoclass                   |
|                               | Ecological site IDs/names — links soil to          |
|                               | vegetation potential for range and forest land.    |
+-------------------------------+----------------------------------------------------+
| ssurgo_parent_material_*      | mapunit → component → copmgrp → copm               |
|                               | What the soil formed from (loess, alluvium,        |
|                               | glacial till, volcanic ash, etc.).                 |
+-------------------------------+----------------------------------------------------+
| ssurgo_soil_temperature_*     | mapunit → component → comonth → cosoiltemp         |
|                               | Monthly mean soil temperature by depth (°C),       |
|                               | with representative, low, and high values.         |
+-------------------------------+----------------------------------------------------+

Future query types (not yet implemented)
-----------------------------------------
+-------------------------------+----------------------------------------------------+
| ssurgo_crop_yields_*          | cocropyld / mucropyld — crop-specific yield        |
|                               | estimates, irrigated and non-irrigated.            |
+-------------------------------+----------------------------------------------------+
| ssurgo_landscape_position_*   | cogeomordesc — hillslope position and landform.    |
+-------------------------------+----------------------------------------------------+
| ssurgo_surface_cover_*        | cosurffrags + cofloorfrag — surface rock cover.    |
+-------------------------------+----------------------------------------------------+
| ssurgo_soil_narratives_*      | mutext + cotext + chtext — free-text descriptions. |
+-------------------------------+----------------------------------------------------+

More granular laboratory data: https://ncsslabdatamart.sc.egov.usda.gov/
"""

from .constants import _NO_COVERAGE_MSG, LICENSE_INFO
from .tools import (
    ssurgo_area_summary_available_variables,
    ssurgo_area_summary_bbox_query,
    ssurgo_area_summary_query,
    ssurgo_ecological_site_available_variables,
    ssurgo_ecological_site_bbox_query,
    ssurgo_ecological_site_query,
    ssurgo_parent_material_available_variables,
    ssurgo_parent_material_bbox_query,
    ssurgo_parent_material_query,
    ssurgo_seasonal_hydrology_available_variables,
    ssurgo_seasonal_hydrology_bbox_query,
    ssurgo_seasonal_hydrology_query,
    ssurgo_soil_profile_available_variables,
    ssurgo_soil_profile_bbox_query,
    ssurgo_soil_profile_query,
    ssurgo_soil_suitability_available_rule_names,
    ssurgo_soil_suitability_bbox_query,
    ssurgo_soil_suitability_query,
    ssurgo_soil_temperature_available_variables,
    ssurgo_soil_temperature_bbox_query,
    ssurgo_soil_temperature_query,
    ssurgo_subsurface_barriers_available_variables,
    ssurgo_subsurface_barriers_bbox_query,
    ssurgo_subsurface_barriers_query,
)

__all__ = [
    "LICENSE_INFO",
    "_NO_COVERAGE_MSG",
    "ssurgo_soil_profile_available_variables",
    "ssurgo_soil_profile_query",
    "ssurgo_soil_profile_bbox_query",
    "ssurgo_area_summary_available_variables",
    "ssurgo_area_summary_query",
    "ssurgo_area_summary_bbox_query",
    "ssurgo_subsurface_barriers_available_variables",
    "ssurgo_subsurface_barriers_query",
    "ssurgo_subsurface_barriers_bbox_query",
    "ssurgo_seasonal_hydrology_available_variables",
    "ssurgo_seasonal_hydrology_query",
    "ssurgo_seasonal_hydrology_bbox_query",
    "ssurgo_soil_suitability_available_rule_names",
    "ssurgo_soil_suitability_query",
    "ssurgo_soil_suitability_bbox_query",
    "ssurgo_ecological_site_available_variables",
    "ssurgo_ecological_site_query",
    "ssurgo_ecological_site_bbox_query",
    "ssurgo_parent_material_available_variables",
    "ssurgo_parent_material_query",
    "ssurgo_parent_material_bbox_query",
    "ssurgo_soil_temperature_available_variables",
    "ssurgo_soil_temperature_query",
    "ssurgo_soil_temperature_bbox_query",
]
