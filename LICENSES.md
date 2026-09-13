# Data Source Licenses

`env-data-mcp` retrieves data from third-party sources. The license for the
package code itself is in `LICENSE` (Apache 2.0). This file documents the
license and attribution requirements for each **upstream data source**.

Each source module contains a `LICENSE_INFO` dict constant with the same
information in machine-readable form. The `license` and `license_url` fields
are propagated in `_meta` on every tool response.

---

## NASA POWER (Prediction of Worldwide Energy Resources)

**Tool**: `nasa_power_query`  
**License**: Public domain (US Government work)  
**Terms**: https://power.larc.nasa.gov/docs/services/terms-conditions/  

Attribution requested by NASA in any publication or product:

> These data were obtained from the NASA Langley Research Center (LaRC)
> POWER Project funded through the NASA Earth Science/Applied Science Program.

---

## SSURGO (Soil Survey Geographic Database)

**Tool**: `ssurgo_query`  
**License**: Public domain (USDA government data)  
**Terms**: https://www.nrcs.usda.gov/resources/data-and-reports/ssurgo  

No formal license restrictions. Attribution to USDA Natural Resources
Conservation Service (NRCS) is good practice:

> Soil Survey Staff, Natural Resources Conservation Service, United States
> Department of Agriculture. Web Soil Survey. Available online at
> https://websoilsurvey.nrcs.usda.gov/. Accessed [date].

---

## SoilGrids v2.0

**Tool**: `soilgrids_point_query`  
**License**: Creative Commons Attribution 4.0 International (CC BY 4.0)  
**Terms**: https://creativecommons.org/licenses/by/4.0/  
**Citation**: https://www.isric.org/explore/soilgrids  

Required citation for any publication or product:

> Poggio L, de Sousa LM, Batjes NH, Heuvelink GBM, Kempen B, Ribeiro E,
> Rossiter D (2021) SoilGrids 2.0: producing soil information for the globe
> with quantified spatial uncertainty. SOIL 7: 217–240.
> https://doi.org/10.5194/soil-7-217-2021

---

## GBIF (Global Biodiversity Information Facility)

**Tool**: `gbif_occurrences`  
**License**: Mixed — CC0 1.0, CC BY 4.0, or CC BY-NC 4.0 per occurrence record  
**Terms**: https://www.gbif.org/terms  

The `license` column is present in each Parquet occurrence record.
`_meta.license` reports the unique license(s) present in the query result.

For any CC BY or CC BY-NC records, cite the GBIF occurrence download DOI
(automatically generated when downloading via the GBIF portal):

> GBIF.org (year) GBIF Occurrence Download https://doi.org/10.15468/dl.XXXXXX

---

## Sentinel-5P TROPOMI

**Tool**: `tropomi_point_query`  
**License**: ESA Copernicus Open Access  
**Terms**: https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice  

Free use, reproduction, and distribution with attribution. Required
attribution string for any publication or product:

> Contains modified Copernicus Sentinel data [year], processed by ESA.

---

## OpenAQ

**Tool**: `openaq_query`  
**License**: Creative Commons Attribution 4.0 International (CC BY 4.0)  
**Terms**: https://creativecommons.org/licenses/by/4.0/  
**Citation**: https://openaq.org  

Required attribution:

> OpenAQ (year). Open air quality data. https://openaq.org. Accessed [date].

---

## OCO-2 / OCO-3 (Orbiting Carbon Observatory)

**Tool**: `oco2_query`  
**License**: Public domain (NASA/US Government work)  
**Terms**: https://disc.gsfc.nasa.gov/information/documents  

Required acknowledgment in any publication:

> OCO-2/OCO-3 data were produced by the OCO-2/3 project at the Jet Propulsion
> Laboratory, California Institute of Technology, and obtained from the GESDISC
> data archive, maintained by the NASA Goddard Earth Sciences Data and
> Information Services Center.

---

## EMIT (Earth Surface Mineral Dust Source Investigation)

**Tool**: `emit_query`  
**License**: Public domain (NASA/US Government work)  
**Terms**: https://lpdaac.usgs.gov/data/data-citation-and-policies/  

Required acknowledgment in any publication:

> EMIT data were produced by the EMIT Science Team at the Jet Propulsion
> Laboratory, California Institute of Technology, and obtained from the
> NASA Land Processes Distributed Active Archive Center (LPDAAC).

---

## ESS-DIVE (Environmental System Science Data Infrastructure for a Virtual Ecosystem)

**Tool**: `essdive_query`  
**License**: Varies per dataset package  
**Terms**: https://data.ess-dive.lbl.gov/about  

The license for each dataset is retrieved at query time from the ESS-DIVE
metadata API and propagated in `_meta.license`. Check the per-dataset
metadata for citation requirements.

---

# The `feeds` family and the point accessors (added 2026-09)

Every feed tool returns `{data: [EventRecord, …], _meta}`; `_meta` carries `license`,
`license_url`, `citation`, plus `ttl_s`, `fetched_at`, `cached` and — for keyed or rate-limited
sources — `quota`.  Keys are read from the environment inside the tool and never appear in a
response, a log or a URL that is returned.

## NASA EONET v3

**Tool**: `eonet_events`  
**License**: Public domain (NASA)  
**Terms**: https://eonet.gsfc.nasa.gov/docs/v3  

EONET is a curated feed of natural events and describes itself as "not an official source" of
event information; cite the linked source of each event for anything authoritative.

---

## USGS earthquakes (FDSN event service / ComCat)

**Tool**: `usgs_quakes_events`  
**License**: Public domain (USGS)  
**Terms**: https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits  

> U.S. Geological Survey, Earthquake Hazards Program, ANSS Comprehensive Earthquake Catalog
> (ComCat), https://earthquake.usgs.gov/fdsnws/event/1/

---

## NASA FIRMS (active fires)

**Tool**: `nasa_firms_fires` — needs `NASA_FIRMS_MAP_KEY` (free; 5,000 transactions / 10 min)  
**License**: NASA data policy — free and open, attribution requested  
**Terms**: https://www.earthdata.nasa.gov/data/tools/firms/faq  

Requested acknowledgement:

> We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource
> Management System (FIRMS) (https://firms.modaps.eosdis.nasa.gov), part of NASA's Earth Science
> Data and Information System (ESDIS).

The MAP_KEY is part of the request URL by FIRMS design; the adapter never returns or logs that URL.

---

## NWS alerts (api.weather.gov)

**Tool**: `nws_alerts_at`  
**License**: Public domain (NOAA / US Government work)  
**Terms**: https://www.weather.gov/disclaimer  

The NWS API requires a descriptive `User-Agent`; the adapter sends one naming this project.

---

## USGS Water Data (OGC API)

**Tool**: `usgs_water_latest` — keyless 50 requests/hour; `USGS_WATERDATA_API_KEY` (free) 1,000/hour  
**License**: Public domain (USGS)  
**Terms**: https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits  

> U.S. Geological Survey, National Water Information System, via the USGS Water Data OGC API
> (https://api.waterdata.usgs.gov/ogcapi/v0/), accessed [date].

---

## Open-Meteo (gated: non-commercial terms)

**Tool**: `open_meteo_current` — answers `gated` unless `ENV_DATA_ALLOW_NC=1`  
**License**: CC BY 4.0 data; the free API is for **non-commercial use only** (commercial use needs a
paid plan)  
**Terms**: https://open-meteo.com/en/terms  

> Weather data by Open-Meteo.com — Zippenfenig, P. (2023). Open-Meteo.com Weather API. Zenodo.
> https://doi.org/10.5281/zenodo.7970649

Setting `ENV_DATA_ALLOW_NC=1` is the operator's attestation that the deployment's use is
non-commercial.

---

## Daymet (ORNL DAAC)

**Tool**: `daymet_at`  
**License**: Open — "Data hosted by the ORNL DAAC is openly shared, without restriction"  
**Terms**: https://daac.ornl.gov/about/  

> Thornton, M.M., R. Shrestha, Y. Wei, P.E. Thornton, S-C. Kao, and B.E. Wilson. 2022. Daymet:
> Daily Surface Weather Data on a 1-km Grid for North America, Version 4 R1. ORNL DAAC, Oak Ridge,
> Tennessee, USA. https://doi.org/10.3334/ORNLDAAC/2129

---

## Macrostrat

**Tool**: `macrostrat_at`  
**License**: CC BY 4.0 (the API answers `license: "CC-BY 4.0"`)  
**Terms**: https://macrostrat.org/api/v2/meta  

> Peters, S.E., J.M. Husson, and J. Czaplewski. 2018. Macrostrat: a platform for geological data
> integration and deep-time Earth crust research. Geochemistry, Geophysics, Geosystems 19(4):
> 1393–1409. https://doi.org/10.1029/2018GC007467

---

## USGS 3DEP elevation (EPQS)

**Tool**: `elevation_3dep`  
**License**: Public domain (USGS)  
**Terms**: https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits  

---

## ARM (DOE Atmospheric Radiation Measurement)

**Tool**: `arm_nearest` (site table only; no ARM data are fetched)  
**License**: "ARM data are available to all participants on a free and open basis"; a free ARM
account is needed for the data themselves  
**Terms**: https://www.arm.gov/guidance/datause/generalguidelines  

Requested acknowledgement when ARM data are used:

> Data were obtained from the Atmospheric Radiation Measurement (ARM) user facility, a U.S.
> Department of Energy (DOE) Office of Science user facility managed by the Biological and
> Environmental Research program.

---

## EIA (API v2, Form EIA-860M)

**Tool**: `eia_plants_near` — needs `EIA_API_KEY` (free)  
**License**: Public domain (US Government publication)  
**Terms**: https://www.eia.gov/about/copyrights_reuse.php  

---

## ERA5 monthly means (Copernicus Climate Data Store)

**Tool**: `era5_monthly_at` — needs `CDS_API_KEY` (a CDS Personal Access Token) and a one-time
acceptance of the dataset licence on the CDS website  
**License**: CC BY 4.0 (the ERA5 licence was replaced with CC-BY on 2 July 2025)  
**Terms**: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels-monthly-means  

> Hersbach, H. et al. (2023): ERA5 monthly averaged data on single levels from 1940 to present.
> Copernicus Climate Change Service (C3S) Climate Data Store (CDS).
> https://doi.org/10.24381/cds.f17050d7 — "Contains modified Copernicus Climate Change Service
> information [year]".
