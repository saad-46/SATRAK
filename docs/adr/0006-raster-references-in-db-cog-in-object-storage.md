# ADR-0006: Raster references in PostGIS, pixels in object storage (COG-only processed tier)

- **Status:** Accepted
- **Date:** 2026-07-06
- **Deciders:** SATRAK Engineering (Principal Architect / Lead Backend / Principal GIS)
- **Builds on:** [ADR-0002](0002-core-domain-platform.md),
  [ADR-0005](0005-earth-observation-bounded-context.md)
- **Ratifies:** ADR-EO-002 of
  [docs/epic-3-earth-observation-platform-spec.md](../epic-3-earth-observation-platform-spec.md)

## Context

At national scale the platform ingests terabytes of imagery per day (TDD §3.6). Where
pixel data lives determines the size, latency, and blast radius of the transactional
database. The Engineering Blueprint (Part 5, "Raster Data") already mandates Cloud-
Optimized GeoTIFFs (COGs) in object storage with PostGIS holding only references. This
ADR restates that constraint as an **EO-local, testable decision** so implementers cannot
reintroduce database-resident raster.

## Decision

**PostGIS stores only raster _references_; all pixels are COGs in object storage, read via
HTTP range requests.**

1. The transactional store (`satellite_scenes`, `tile_index`, and related tables) holds
   scene ids, provider ids, bounding boxes (national CRS + WGS84 interchange), acquisition
   dates, checksums, and storage URIs — **never pixel blobs**. `postgis_raster` is not
   used.
2. Processed/analysis-ready imagery is written as **COG** (internally tiled + overviews),
   enabling direct range-request serving and per-tile reads without a database round-trip.
3. Raster access goes through the existing `StorageProvider` port (S3/MinIO); the EO
   context adds only the content-addressed key scheme and tier policy (spec §7) on top —
   no new storage abstraction.
4. Integrity is carried by `checksum_sha256` on every asset (already modeled by the
   `StorageProvider` fake), stored on the reference row and in object metadata.

## Consequences

- **Positive:** The transactional database stays small and fast (references only),
  protecting the ACID store needed for legal records; imagery serves directly from object
  storage/CDN via range reads (COG's core advantage).
- **Positive:** Clean future extraction — a `services/earth_observation` deployable reads
  the same object storage without moving pixel data out of a database.
- **Neutral:** Requires object storage reachable by every imagery consumer (already true:
  MinIO in dev, S3-compatible in prod per Blueprint Part 6).
- **Negative:** Consumers must speak COG/range-reads rather than SQL for pixels; mitigated
  by the tile service and signed-URL download endpoints (spec §11, §14).

## Alternatives considered

- **PostGIS raster (`postgis_raster`) for pixel storage:** rejected — bloats the
  transactional store, couples imagery volume to DB scaling, and forfeits COG range-read
  serving. Contradicts Blueprint Part 5.
- **Store only in object storage with no DB references:** rejected — spatial/temporal
  discovery (search by AOI + date + cloud%) needs an indexed relational catalog; object
  storage listing cannot serve those queries within the performance targets (TDD §13).
