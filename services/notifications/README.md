# notifications service (placeholder)

**Bounded context:** multi-channel notification dispatch.

Future home of the `notification-service` (TDD §3.9; Blueprint §2.13): SMS / email /
push / postal-integration dispatch with delivery tracking and retry/escalation.

**Planned stack:** Python 3.12 · FastAPI · Celery · Redis · external SMS/email gateways.

No implementation yet — boundary reservation only. Domain work begins in the Reports
& Notifications epic.
