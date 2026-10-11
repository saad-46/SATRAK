"""Earth Observation HTTP API (Epic 3 Stories 17-19).

These routers live in the app.api boundary — not inside the earth_observation context —
because the "bounded contexts depend only inward" import-linter contract forbids a context
from importing app.api/app.core. Here the boundary wires the context's application services
to HTTP, reusing the shared pagination, response-envelope, and problem-details plumbing.
Namespace: /api/v1/eo/* (ADR-0010; the TDD's /satellite/* can be added as an alias later).
"""
