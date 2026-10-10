# SATRAK Documentation

| Document                                                | Purpose                                                       |
| ------------------------------------------------------- | ------------------------------------------------------------- |
| [PRD.md](../PRD.md)                                     | Product Requirements — problem, vision, users, scope          |
| [TDD.md](../TDD.md)                                     | Technical Design — architecture, services, AI/GIS, data model |
| [ENGINEERING_BLUEPRINT.md](../ENGINEERING_BLUEPRINT.md) | Buildable engineering plan — repo, modules, epics, roadmap    |
| [adr/](adr/)                                            | Architecture Decision Records                                 |

These three top-level documents are the **source of truth** and are not modified
during implementation. Significant decisions that revise them are captured as
ADRs rather than by editing their history.

## Architecture Decision Records

| ADR                                                                            | Decision                                                                   |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| [ADR-0001](adr/0001-monorepo-and-engineering-foundation.md)                    | Monorepo & engineering foundation                                          |
| [ADR-0002](adr/0002-core-domain-platform.md)                                   | Core domain platform (shared kernel + contexts)                            |
| [ADR-0003](adr/0003-modular-monolith-first.md)                                 | Modular monolith first & microservice extraction path                      |
| [ADR-0004](adr/0004-ruff-formatting-toolchain.md)                              | Ruff as the single lint/format/import toolchain                            |
| [ADR-0005](adr/0005-earth-observation-bounded-context.md)                      | Earth Observation as one bounded context (generalizes `satellite`)         |
| [ADR-0006](adr/0006-raster-references-in-db-cog-in-object-storage.md)          | Raster references in PostGIS, pixels (COG) in object storage               |
| [ADR-0007](adr/0007-capability-driven-provider-abstraction.md)                 | Capability-driven imagery-provider abstraction                             |
| [ADR-0008](adr/0008-celery-behind-taskqueue-port-for-eo-jobs.md)               | Celery (beat + chains) behind the TaskQueue port for EO jobs               |
| [ADR-0009](adr/0009-coarse-public-integration-events-for-earth-observation.md) | Coarse public integration events for Earth Observation                     |
| [ADR-0010](adr/0010-context-naming-review-earth-observation-vs-satellite.md)   | Context naming review: `earth_observation` affirmed, drone scope corrected |

Contributor and release process docs live in
[CONTRIBUTING.md](../CONTRIBUTING.md), [onboarding/](onboarding/), and
[RELEASE.md](../RELEASE.md).

## Subdirectories (populated as the platform grows)

- `architecture/` — deep-dives and diagrams beyond the TDD
- `runbooks/` — operational procedures (on-call, incident response, DR)
- `api/` — generated OpenAPI docs per service
- `onboarding/` — new-engineer setup guide
