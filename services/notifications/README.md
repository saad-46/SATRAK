# notifications service (placeholder)

**Bounded context:** multi-channel notification dispatch.

Future home of the `notification-service` (TDD §3.9; Blueprint §2.13): SMS / email /
push / postal-integration dispatch with delivery tracking and retry/escalation.

**Planned stack:** Python 3.12 · FastAPI · Celery · Redis · external SMS/email gateways.

No implementation yet — boundary reservation only. Domain work begins in the Reports
& Notifications epic.

---

## Status — ADR-0003 (Modular Monolith First)

This bounded context is **reserved**, not yet implemented. Its boundary is held as
a placeholder at `apps/api/app/contexts/notification/` in the modular monolith; the domain
model is built in the context's dedicated epic (only `core`, `identity`, and
`organization` are implemented today). This directory (`services/notifications`) is the
**reserved extraction target** for the `notification` context: when sustained load,
dedicated team ownership, or a data-residency requirement justifies a separate
deployable, it is extracted here as its own FastAPI app + `pyproject.toml` per the
strategy in [ADR-0003](../../docs/adr/0003-modular-monolith-first.md). Until then,
**`apps/api/app/contexts/notification` is the authoritative home** for the boundary.
