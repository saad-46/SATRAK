# ADR-0015: Construction-compliance workflow (parcel → permit → candidate → verification → case)

- **Status:** Accepted for implementation — local branch `claude/satrak-compliance-workflow`, not merged
- **Date:** 2026-10-11
- **Relates to:** PRD modules 4, 5, 6, 10, 20, 27 (FR-4.1/4.4, 5.1–5.3, 6.2/6.3/6.7, 10.1/10.3/10.5/10.6, 20.1/20.2); ADR-0011 (tenancy), ADR-0012 (geometry), ADR-0014 (officer verification)

## Context

Access control, tenancy and the officer-verification _requirement_ existed (ADR-0011, 0013, 0014) but
no product aggregate used them: ADR-0014 said enforcement would be built "when finding/case
aggregates exist". This ADR records how the first end-to-end product slice does that, and the
choices where the source documents were silent or disagreed.

## Decisions

1. **Layering.** Pure domain rules live in the bounded contexts (`property`, `permit`, `compliance`,
   `inspection`; no framework or database imports). Persistence is one PostGIS store
   (`app/db/compliance_store.py`). A service layer (`app/services/compliance_workflow.py`) applies the
   rules, authorization and audit; routes (`app/api/v1/endpoints/compliance.py`) only translate HTTP.
   Import-linter contracts forbid contexts from importing `app.services` and services from importing
   the web layer or the all-tenants scope.
2. **The finding model (ADR-0014 vs Blueprint) is not reopened.** The unverified output of AI, a field
   report or an import is a **construction-change candidate**. A **case** is a different aggregate that
   can only exist for a candidate an officer has confirmed. We did not introduce a separate "finding"
   aggregate; the open question of whether the Blueprint's finding should be that candidate or a
   case-level record is listed under _Unresolved_ below.
3. **The release gate is enforced three times.** (a) the service refuses with `verification_required`
   (409) and records `release.denied`; (b) the review and case rules live in the domain; (c) database
   triggers reject a case for a candidate that is not `confirmed` and evaluated, reject a candidate
   status that does not follow a recorded review, and make candidate evidence immutable. A direct SQL
   `INSERT` as the table owner therefore fails too.
4. **Append-only history.** Geometry versions, permit events, reviews, evaluations, case transitions,
   assignments and findings accept INSERT only; triggers reject UPDATE, DELETE and TRUNCATE for every
   role (FR-20.2 spirit). Corrections append (a reversal review) and never overwrite.
5. **Tenancy.** All twelve new tables carry `jurisdiction_id`, are `FORCE ROW LEVEL SECURITY`, and
   are listed in `TENANT_TABLES`. A trigger requires a child row to share the jurisdiction of the row it
   references, so no cross-tenant link can be stored. Objects in other jurisdictions are invisible
   (404, same as a missing id); writing into a jurisdiction outside the caller's scope is 403 and
   audited. (The 403-vs-404 choice for _foreign_ objects remains the open decision recorded earlier.)
6. **Audit-before-commit.** The audit event is recorded inside the request's transaction scope, but the
   audit log commits independently. A refused action stays recorded though its transaction rolls back;
   an audit outage fails the request (503) instead of letting an unaudited decision through. If the
   business commit then fails after the audit write, the log over-reports an action that did not happen,
   which is the safe direction for an append-only log.
7. **Evaluation is a recommendation.** The deterministic rule engine (seven rules, explained one by
   one, parameters and `RULES_VERSION` stored with each result) classifies a candidate; the result is
   stored as a `candidate_evaluation`. It never changes the candidate's status and never opens a case
   (FR-6.7). The thresholds (10 % footprint, 5 % boundary, 10 % plot-area tolerance) are **placeholders**
   pending an approved municipal rule set (FR-6.1/6.5) and are labelled as such in every result.
8. **Simulated data.** Candidates and permits carry `is_simulated`. There is no live permit system,
   imagery provider or model behind this slice; `source_system`, `model_name` and `model_version` are
   recorded exactly as supplied. Nothing here claims an integration is operational.
9. **Areas** are computed with PostGIS on the `geography` type (square metres on the spheroid) so they
   do not depend on a per-jurisdiction projection that has not been chosen yet (ADR-0012 leaves
   `jurisdiction.working_crs` for later).
10. **Audit log downgrade.** `0004`/`0005` downgrades restore the narrower event-type check `NOT VALID`,
    because audit rows cannot be deleted and a validating check would make the migration irreversible
    once a workflow event exists.

## Consequences

- Operators must grant the new permission codes to roles (the migration seeds the catalogue only, no
  role mapping): `parcel:*`, `property:*`, `permit:*`, `candidate:read|create|evaluate`,
  `finding:verify`, `case:read|create|assign|update|resolve|issue_notice`.
- `case:update` is also the eligibility test for an assignee.
- Test fixtures that truncate tenant tables go through `tests/db_reset.py`, which disables the
  append-only triggers inside one owner transaction and re-enables them before commit.

## Unresolved (need a decision; nothing was assumed)

- Whether ADR-0014's "finding" and the Blueprint's finding are the candidate or a later record.
- Permit-to-parcel matching tolerance, boundary tolerance and severity mapping (FR-6.1).
- Whether supervisors may assign without the assignee consenting, SLA clocks (FR-10.4), automatic
  assignment (FR-10.3), and priority from the risk score (FR-10.2, module 14 does not exist).
- Server-side hashing and WORM storage of evidence files (FR-27.1–27.3): evidence is recorded by
  reference and client-supplied SHA-256 only.
