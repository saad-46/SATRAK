# notifications service (placeholder)

**Bounded context:** multi-channel notification dispatch.

Future home of the `notification-service` (TDD §3.9; Blueprint §2.13): SMS / email /
push / postal-integration dispatch with delivery tracking and retry/escalation.

**Planned stack:** Python 3.12 · FastAPI · Celery · Redis · external SMS/email gateways.

No implementation yet — boundary reservation only. Domain work begins in the Reports
& Notifications epic.

---

## Status — ADR-0003 (Modular Monolith First)

This bounded context is **currently implemented in `apps/api/app/contexts/notification/`**
(the modular monolith). This directory is its **reserved extraction target**: when
sustained load, dedicated team ownership, or a data-residency requirement justifies a
separate deployable, the context is extracted here as its own FastAPI app +
`pyproject.toml`, per the extraction strategy in
[ADR-0003](../../docs/adr/0003-modular-monolith-first.md). Until then this directory
stays intentionally empty — **`apps/api/app/contexts/notification` is authoritative.**
