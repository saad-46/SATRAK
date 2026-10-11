# ADR-0005: Earth Observation as a single bounded context (generalizes reserved `satellite`)

- **Status:** Accepted — **Amended 2026-07-06 by [ADR-0010](0010-context-naming-review-earth-observation-vs-satellite.md)** (drone scope corrected; see the Amendment section below)
- **Date:** 2026-07-06
- **Deciders:** SATRAK Engineering (Principal Architect / Lead Backend)
- **Extends:** [ADR-0003](0003-modular-monolith-first.md) ·
  **Builds on:** [ADR-0002](0002-core-domain-platform.md)
- **Ratifies:** ADR-EO-001 of
  [docs/epic-3-earth-observation-platform-spec.md](../epic-3-earth-observation-platform-spec.md)

## Context

The Epic 3 design sprint produced the Earth Observation (EO) Platform specification.
The platform must serve **satellite, drone, and future aerial imagery** through a
_single_ reusable set of raster/storage/tile/metadata/time-series machinery.

ADR-0003's authoritative context list reserves `satellite` and `drone` as **separate**
bounded contexts, and there is no `earth_observation` context. The Blueprint (Part 2.7)
and TDD (§3.6–3.7) likewise describe the imagery capability under a satellite-only name.
This is a naming/granularity gap, not a conflict: the reserved `satellite` context is
exactly the imagery-platform boundary, but its name excludes the drone/aerial imagery the
platform is required to serve, and splitting ingestion/preprocessing/tiling into separate
contexts would fracture a single aggregate lifecycle.

## Decision

**Adopt one bounded context, `earth_observation`, as the reusable imagery platform, and
treat the reserved `satellite` placeholder as its acquisition sub-domain.**

1. `apps/api/app/contexts/earth_observation/` is the authoritative home for the boundary
   (per ADR-0003, contexts are authoritative; `services/*` are reserved extraction
   targets).
2. The reserved extraction target `services/satellite/` is **renamed** to
   `services/earth_observation/`. This ADR ratifies the decision; the physical rename +
   context scaffold are executed in **Epic 3 Story 1** (scaffold), not here.
3. Satellite and **manned aerial** imagery are modeled as **provider families** inside the
   one context. **All drone/UAV imagery, missions, telemetry, and photogrammetry remain in
   the separate `drone` context** (see the Amendment below and
   [ADR-0010](0010-context-naming-review-earth-observation-vs-satellite.md)); the `drone`
   context reuses the shared imagery/raster packages, not the EO context, and collaborates
   via public interfaces + integration events.
4. The context obeys the ADR-0002 dependency rule unchanged: it imports only
   `app.shared`, never another context, and collaborates via ids + domain events.

This **extends** ADR-0003's authoritative context list: `earth_observation` is added;
`satellite` is subsumed as its acquisition sub-domain; `drone` and `gis` remain separate
peer contexts.

## Consequences

- **Positive:** Maximum reuse of raster/storage/tile/metadata code across all imagery
  sources — the central goal of the platform. One aggregate (`Scene`) owns the full
  lifecycle, avoiding chatty cross-context calls.
- **Positive:** Compute-heavy drone photogrammetry stays isolated in its own context/node
  pool, unaffected by imagery-platform changes.
- **Neutral / governance cost:** ADR-0003's context list is amended by this ADR rather
  than edited in place (ADRs are immutable; later decisions extend earlier ones). The
  `services/satellite → services/earth_observation` rename is deferred to Story 1.
- **Negative:** A single larger context is more internally complex than three micro-
  contexts; mitigated by the sub-domain package structure (`providers/raster/metadata/
storage/timeline/tiles/jobs`) defined in the spec (§4) and by import-linter enforcement.

## Alternatives considered

- **Three contexts (`ingestion`, `preprocessing`, `tiles`) mirroring TDD §3.6/3.7
  services:** rejected — those are _deployment_ splits, not _domain_ boundaries; they
  share one aggregate lifecycle. They remain independently extractable as modules later
  under ADR-0003 without being separate contexts now.
- **Keep the `satellite` name as-is:** rejected — excludes drone/aerial imagery the
  platform must serve.
- **Put the raster engine in the shared kernel:** rejected — the kernel imports only the
  standard library (import-linter); GDAL/rasterio are heavy infrastructure dependencies
  and belong in `earth_observation/infrastructure/`, exposed to inner layers as a port.

## Amendment — 2026-07-06 (per [ADR-0010](0010-context-naming-review-earth-observation-vs-satellite.md))

The pre-implementation architecture review ([ADR-0010](0010-context-naming-review-earth-observation-vs-satellite.md))
**affirmed** the `earth_observation` context name but **corrected its scope**. This ADR's
original wording that "drone imagery is an EO provider family" is **superseded**:

- **Earth Observation owns spaceborne + airborne imagery only** — satellite and manned
  aerial. It does **not** own drone missions, telemetry, mission planning, or uploads.
- **Drone/UAV imagery stays wholly in the `drone` context** (per Blueprint §2.8, which owns
  the `drone_imagery` table). A mission-bound pilot upload is not a searchable/taskable
  scene; modeling it as an EO "provider" was a leaky abstraction.
- **DRY is achieved via shared packages** — `packages/py-geo`, `packages/py-raster`, and
  `packages/py-imagery` hold the reusable CRS/raster/imagery-provider abstractions. The
  `drone` context reuses those **packages** without importing the EO **context**, preserving
  the ADR-0002/0003 dependency rule (contexts never import each other).

The clean split is therefore **EO (spaceborne/airborne) vs UAV (drone)**, communicating
only through public interfaces and integration events.
