# compliance service (placeholder)

**Bounded context:** case lifecycle + compliance enforcement workflow.

Future home of the `case-service` (TDD §3.3, §4; Blueprint §2.11): the central
lifecycle of a detected-violation case (Detected → Under Review → Drone Dispatched →
Inspected → Notice Issued → Resolved/Escalated), officer review, SLA tracking, and
the case-status event stream that Notification/Reporting/Analytics/Audit subscribe to.

**Planned stack:** Python 3.12 · FastAPI · PostgreSQL/PostGIS · event bus.

This is the orchestration heart of the platform. No implementation yet — boundary
reservation only; the human-in-the-loop review gate (TDD ADR-04) is designed in from
the first line of code. Domain work begins in the Case Management epic.

---

## Status — ADR-0003 (Modular Monolith First)

This bounded context is **reserved**, not yet implemented. Its boundary is held as
a placeholder at `apps/api/app/contexts/compliance/` in the modular monolith; the domain
model is built in the context's dedicated epic (only `core`, `identity`, and
`organization` are implemented today). This directory (`services/compliance`) is the
**reserved extraction target** for the `compliance` context: when sustained load,
dedicated team ownership, or a data-residency requirement justifies a separate
deployable, it is extracted here as its own FastAPI app + `pyproject.toml` per the
strategy in [ADR-0003](../../docs/adr/0003-modular-monolith-first.md). Until then,
**`apps/api/app/contexts/compliance` is the authoritative home** for the boundary.
