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

## Amendment 1 (2026-10-11): candidate/case model approved (Option A)

Decision D1, approved by the product owner on 2026-10-11. This amendment fixes the terminology; the
title keeps "findings" for link stability only.

**Terminology (used consistently across code, API and docs)**

| Term               | Meaning                                                                                       |
| ------------------ | --------------------------------------------------------------------------------------------- |
| Candidate          | AI-generated (or imported/reported) potential construction change; always starts `unverified` |
| Verified candidate | Candidate with an authorized, recorded `confirm` review (status `confirmed`)                  |
| Inspection case    | Official workflow opened only from a verified candidate                                       |
| Case finding       | Field inspector's site-visit record (PRD `case_finding`, FR-10.5); never AI output            |

"Finding" alone is not used. Where §§1–6 above say "finding", read "candidate" (before review) or
"verified candidate" (after). The `finding:verify` permission code is kept (it is seeded and
referenced by `authorize_verification`); it verifies **candidates**.

**Lifecycle.** `unverified` → (`needs_evidence` ↔ `unverified`) → `confirmed` | `rejected`, each
transition following a recorded, append-only review. A case (`created` → `assigned` →
`under_investigation` → `notice_issued` → `resolved` | `dismissed`) can exist only for a `confirmed`,
evaluated candidate, one case per candidate. The Blueprint's "Detected" state is the unverified
candidate; its "Under Review" is the candidate in review; the case lifecycle starts after verification.

**Release gate.** Unchanged and enforced independently of any UI: service (`verification_required`,
409, audited `release.denied`), domain, and database triggers (`inspection_case_guard`,
`candidate_guard`). Citizen, Revenue and court workflows must reference a verified candidate or a case
opened from one; an unverified candidate is never an established finding.

**Event contract.** Candidate creation emits `candidate.created` (replacing the Blueprint's
`case.candidate_created`, which implied a case existed). Verification emits `candidate.verified`
(decision `confirm`) or `candidate.rejected`. Only `candidate.verified` / the case-create API may lead
to `case.created`. **Status of implementation:** no event bus or outbox exists in the codebase yet;
the in-process equivalents are the audit events `candidate.registered`, `candidate.reviewed` and
`case.created`. Publishing to a broker is future work and is not claimed.

**Schema.** Migration 0005 already implements this model (separate `construction_change_candidate`,
`candidate_review`, `inspection_case`, `case_finding` tables); no rename or migration is required.

**Still open (policy decisions; safe defaults in force, nothing invented)**

| Decision                                    | Safe default in force today                                                      |
| ------------------------------------------- | -------------------------------------------------------------------------------- |
| Second officer (four-eyes) for verification | Single authorized officer; the verifier is recorded; no self-verification rule   |
| Reversal, correction, superseding rules     | Append-only; a confirmation cannot be reversed while its case is open            |
| Justification rules per decision            | Minimum 10 characters, all decisions; confirm also needs evaluation + provenance |
| FR-6.1/FR-6.5 thresholds                    | Placeholder defaults, `RULES_VERSION` stamped, labelled non-final                |
