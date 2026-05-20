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

**Tool**: `soilgrids_query`  
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

**Tool**: `sentinel5p_query`  
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
