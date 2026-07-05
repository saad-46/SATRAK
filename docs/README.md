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

## Subdirectories (populated as the platform grows)

- `architecture/` — deep-dives and diagrams beyond the TDD
- `runbooks/` — operational procedures (on-call, incident response, DR)
- `api/` — generated OpenAPI docs per service
- `onboarding/` — new-engineer setup guide
