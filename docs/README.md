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

| ADR                                                         | Decision                                              |
| ----------------------------------------------------------- | ----------------------------------------------------- |
| [ADR-0001](adr/0001-monorepo-and-engineering-foundation.md) | Monorepo & engineering foundation                     |
| [ADR-0002](adr/0002-core-domain-platform.md)                | Core domain platform (shared kernel + contexts)       |
| [ADR-0003](adr/0003-modular-monolith-first.md)              | Modular monolith first & microservice extraction path |
| [ADR-0004](adr/0004-ruff-formatting-toolchain.md)           | Ruff as the single lint/format/import toolchain       |

Contributor and release process docs live in
[CONTRIBUTING.md](../CONTRIBUTING.md), [onboarding/](onboarding/), and
[RELEASE.md](../RELEASE.md).

## Subdirectories (populated as the platform grows)

- `architecture/` — deep-dives and diagrams beyond the TDD
- `runbooks/` — operational procedures (on-call, incident response, DR)
- `api/` — generated OpenAPI docs per service
- `onboarding/` — new-engineer setup guide
