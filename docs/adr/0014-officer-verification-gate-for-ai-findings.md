# ADR-0014: Officer verification gate for AI-generated findings

- **Status:** Accepted as a requirement — owner decision 2026-10-10; enforcement is implemented when finding/case aggregates exist
- **Date:** 2026-10-10
- **Relates to:** PRD §§1.x, 7–8 (AI), 10–11, 32–33 (evidence/court); master prompt rule: algorithmic anomalies are never conclusive proof

## Decision

Every AI-generated candidate must be verified by an authorized officer before it may be used in
citizen-facing decisions, Revenue workflows or court packages.

1. **Candidate:** explicitly `unverified`; may be shown only to authorized reviewers, labeled non-conclusive.
2. **Evidence preparation:** source imagery, acquisition dates, processing/pipeline and model versions, confidence or
   uncertainty, relevant permit information and provenance are recorded.
3. **Officer review:** an authenticated, authorized officer (permission such as `finding:verify`, jurisdiction-scoped) records a decision.
4. **Verification record:** reviewing officer, timestamp, decision, supporting evidence and required justification.
5. **Release:** only an eligible, officer-verified finding can enter citizen, Revenue or court workflows.
6. **Corrections/reversals** append to history; original evidence and decisions are never overwritten.

## Enforcement

In the backend and the database, not the UI: direct API calls and background jobs that try to release an
unverified finding are rejected with a domain error and an audit event; the state transition is guarded
in the aggregate and by a database constraint/policy where applicable; downstream workflows accept only
a verified-finding reference. Court packages keep provenance and distinguish machine-generated analysis
from human-verified conclusions.

## Scope note

No finding or case aggregate exists yet. The access-control sprint supplies the prerequisites
(authenticated officers, jurisdiction-scoped permissions including `finding:verify`, durable audit,
append-only history pattern). The gate itself and its tests are acceptance criteria of the first
epic that introduces findings.

## Implementation note (access-control sprint)

No finding or case aggregate exists yet, so there is no verify endpoint to protect. The authorization half
is in place: `app.core.authz.verification.authorize_verification(ctx, finding_jurisdiction_id)` requires a
context for `finding:verify` **and** that permission in the finding's own jurisdiction. A role alone never
grants global verification. The future verify endpoint must call it and enforce the state transition in the
domain/database as described above.
