# Earth Observation context

The reusable, provider-agnostic **imagery platform** for SATRAK: acquisition, raster
processing, storage, metadata, time-series, tile generation, and background jobs for
**satellite and manned-aerial** imagery.

This is the authoritative home of the boundary (per [ADR-0003](../../../../../docs/adr/0003-modular-monolith-first.md));
`services/earth_observation/` is its reserved microservice-extraction target. The full
design is [docs/epic-3-earth-observation-platform-spec.md](../../../../../docs/epic-3-earth-observation-platform-spec.md).

## Owns

- Satellite imagery (Sentinel, Landsat, Planet, Maxar, Airbus, Cartosat, Bhuvan, ...)
- Manned aerial imagery (orthophoto feeds)
- Imagery providers (the extension mechanism, [ADR-0007](../../../../../docs/adr/0007-capability-driven-provider-abstraction.md))
- Raster processing, image storage (COG; references-in-DB per [ADR-0006](../../../../../docs/adr/0006-raster-references-in-db-cog-in-object-storage.md))
- Metadata, tile generation, time-series imagery

## Does NOT own

- Drone missions, telemetry, mission planning, or pilot uploads
- Drone/UAV imagery and photogrammetry

These belong to the independent **`drone`** context ([ADR-0010](../../../../../docs/adr/0010-context-naming-review-earth-observation-vs-satellite.md)).
Earth Observation and Drone communicate **only** through public interfaces and integration
events — **no direct imports between contexts** (machine-enforced by import-linter).

## Layers (Clean Architecture — dependencies point inward)

| Layer          | Folder                               | Responsibility                                                                                     |
| -------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------- |
| Domain         | [`domain/`](domain/)                 | Aggregates, value objects, ports, events — pure; imports only `app.shared`                         |
| Application    | [`application/`](application/)       | Use-cases orchestrating the domain via ports + Unit of Work                                        |
| Infrastructure | [`infrastructure/`](infrastructure/) | Adapters (providers, raster, storage, tiles, persistence, jobs) — the only place heavy libs appear |
| Interfaces     | [`interfaces/`](interfaces/)         | FastAPI routers + DTOs under `/api/v1`                                                             |

Sub-domain map (spec §4): `providers` (satellite/aerial), `raster`, `storage`, `tiles`,
`persistence`, `jobs` live under `infrastructure/`; `acquisition`, `ingestion`, `metadata`,
`preprocessing`, `tiling`, `timeline`, `retention` under `application/`; `api` under
`interfaces/`.

## Reusable packages

Cross-context reuse (so `drone` and others reuse capability without importing this context):
[`packages/py-geo`](../../../../../packages/py-geo/), [`packages/py-raster`](../../../../../packages/py-raster/),
[`packages/py-imagery`](../../../../../packages/py-imagery/).

## Status — Epic 3 Story 1 (Foundation Scaffold)

Scaffold only. Folders, package `__init__` files, and READMEs exist to establish the
boundary, dependency rules, and CI wiring. **No providers, APIs, models, repositories,
services, events, or business logic are implemented yet** — those arrive in Stories 2+
per the spec's story breakdown (§19).
