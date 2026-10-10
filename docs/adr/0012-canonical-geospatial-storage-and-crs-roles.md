# ADR-0012: Canonical geospatial storage and CRS roles

- **Status:** Accepted — owner decision 2026-10-10
- **Date:** 2026-10-10
- **Deciders:** Saad (owner), SATRAK Engineering
- **Relates to:** PRD §38.2; Engineering Blueprint (Coordinate Systems); TDD §6; Epic 3 spec §6

## Context

PRD §38.2: store EPSG:4326, project for area/distance, EPSG:3857 for web tiles, never calculate area
on unprojected coordinates silently. Blueprint/TDD/Epic 3: normalize to a "national projected CRS
configured per deployment". No document names a country or a specific CRS (India appears only as an
example). **No national CRS is hard-coded.**

## Decision

| Role                     | Rule                                                                                                                                                                                                                                               |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Authoritative vector CRS | EPSG:4326 (lon, lat) stored in PostGIS `geometry`/`geography` with explicit SRID                                                                                                                                                                   |
| Source-native raster CRS | Preserved as delivered (`crs_native`) in the COG and its metadata; originals are never resampled for evidence. Provider CRS (e.g. per-tile UTM) is recorded, not normalized away                                                                   |
| Analysis CRS             | A projected CRS configured per jurisdiction (`analysis_crs`, EPSG code, validated against an allow-list) used for area, distance, FAR/setback and other jurisdiction-specific analysis. Derived outputs record the CRS and the transformation used |
| Web display              | EPSG:3857 for tiles only                                                                                                                                                                                                                           |

Rules: all CRS identifiers are explicit (no implicit default); the transform boundary lives in one
place (`py-geo`); API coordinates are always `[longitude, latitude]` in EPSG:4326 with units
documented; geometries are validated (valid, in range, non-empty, expected dimension, axis order);
area/distance functions require an analysis CRS or a named geodesic method and report which was
used; altitudes carry a vertical datum; transformation round-trip accuracy is tested per configured
analysis CRS; PostGIS columns declare SRID, GiST-indexed.

## Consequences

- The Epic 3 field `crs_processed` ("national projected CRS after ortho") is reinterpreted as a
  _derived_ product CRS, not an authoritative one; the spec text is preserved.
- No schema or data change is implemented by this ADR; implementation accompanies the GIS/Property
  and EO-persistence stories.
- If a deployment country and its mandated CRS are later established, they become the default
  `analysis_crs` for that jurisdiction without changing stored vectors.
