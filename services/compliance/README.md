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
