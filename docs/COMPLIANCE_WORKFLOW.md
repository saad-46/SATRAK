# Construction-compliance workflow

The first product slice built on the access-control foundation. Design decisions are in
[ADR-0015](adr/0015-construction-compliance-workflow.md); the officer-verification rule is
[ADR-0014](adr/0014-officer-verification-gate-for-ai-findings.md).

> **Scope and honesty.** No live permit system, imagery provider or detection model is connected.
> Everything the workflow ingests is supplied through the API, and fixtures are labelled
> `is_simulated`. A rule evaluation is a recommendation, not a finding. The tolerances in the rule
> engine are placeholders. An AI result never establishes illegality and never issues a notice.

## Flow

```
parcel (+ versioned geometry) ─┐
property record ───────────────┤
permit ── matched / unmatched / conflict ──┐
                                           ▼
candidate (unverified) ── evaluate ──▶ evaluation (recommendation)
        │
        ▼ officer review (finding:verify, jurisdiction-scoped)
  confirmed │ rejected │ needs_evidence        (corrections append; nothing is overwritten)
        │ only `confirmed`
        ▼
case created ─▶ assigned ─▶ under_investigation ─▶ notice_issued ─▶ resolved
        └──────────────────────────── dismissed (from any open state)
```

## API (`/api/v1`)

All routes require a bearer token and a permission; the permission yields the jurisdictions in which
the caller may act. Lists are paginated (`page`, `size`) and limited to those jurisdictions. Writes
take `jurisdiction_id` (403 when outside scope). Mutable resources return `version` and require
`expected_version` on change (409 `concurrency_conflict` when stale). Errors are RFC 9457 problem
details.

| Route                                          | Permission                              | Purpose                                                             |
| ---------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------- |
| `POST /parcels`, `GET /parcels[/{id}]`         | `parcel:write` / `parcel:read`          | Register a parcel with its first geometry; list/filter by topology  |
| `GET/POST /parcels/{id}/geometry-versions`     | `parcel:read` / `parcel:write`          | History; append a new version (older versions are kept)             |
| `POST /properties`, `GET /properties[/{id}]`   | `property:write` / `property:read`      | Property master record per parcel                                   |
| `POST /permits`, `GET /permits[/{id}]`         | `permit:write` / `permit:read`          | Register a permit; auto-match to a parcel by declared code          |
| `GET /permits/{id}/history`                    | `permit:read`                           | Append-only permit events                                           |
| `POST /permits/{id}/status`                    | `permit:write`                          | approved → suspended/revoked/closed (revoked/closed are final)      |
| `POST /permits/{id}/match`                     | `permit:write`                          | Officer resolves an unmatched/conflicting permit (reason ≥ 10)      |
| `POST /candidates`, `GET /candidates[/{id}]`   | `candidate:create` / `candidate:read`   | Register a candidate; always starts `unverified`                    |
| `POST /candidates/{id}/evaluations`, `GET …`   | `candidate:evaluate` / `candidate:read` | Run the permit rules; stores the full explanation                   |
| `POST /candidates/{id}/reviews`, `GET …`       | `finding:verify` / `candidate:read`     | Confirm, reject or request evidence (justification ≥ 10)            |
| `POST /cases`                                  | `case:create`                           | Open a case from a **confirmed** candidate (409 otherwise)          |
| `GET /cases[/{id}]`, `GET /cases/{id}/history` | `case:read`                             | Cases by priority; transitions, assignments and findings            |
| `POST /cases/{id}/assignment`                  | `case:assign`                           | Assign; assignee must hold `case:update` in the case's jurisdiction |
| `POST /cases/{id}/transitions`                 | per target (below)                      | State change                                                        |
| `POST /cases/{id}/findings`                    | `case:update`                           | Field finding: notes, measurements, hash-identified evidence        |

Transition permissions: `assigned`, `under_investigation` → `case:update`; `notice_issued` →
`case:issue_notice`; `resolved`, `dismissed` → `case:resolve`. `notice_issued` also needs at least one
recorded finding. Domain errors map to 409 (`invalid_state_transition`, `verification_required`,
`concurrency_conflict`) or 422 (`value_validation_error`, `business_rule_violation`).

### Rule evaluation (placeholder rules, version `2026-10-11.placeholder`)

parcel_resolved, within_parcel_boundary, permit_exists, permit_effective (on the observation date, FR-6.2),
footprint_within_sanctioned, floors_within_sanctioned, permit_records_resolved. Classifications:
`parcel_unresolved`, `unpermitted_construction`, `permit_not_in_effect`, `exceeds_sanctioned_plan`,
`boundary_encroachment`, `needs_manual_review`, `no_discrepancy_found`.

## Database guarantees (migration `0005`)

Forced RLS on 12 tables; INSERT-only history tables; same-jurisdiction child links; candidates start
`unverified` and change status only to the status of their latest recorded review; candidate evidence
columns are immutable; a case requires a `confirmed` candidate and an evaluation of that candidate;
a closed case is immutable; the application role holds no DELETE/TRUNCATE anywhere in the slice.

## Requirement-to-evidence record

Status key: **VL** verified locally (command output reviewed in the build session), **IP** implemented
in part (limits stated). Nothing is verified in CI yet: the branch is pushed but CI runs only for pull requests to `main`. All database
tests ran against local PostgreSQL 16 / PostGIS with Redis; no mocks stand in for the database.

| Feature                                             | PRD                                | TDD / ADR     | Code                                                                          | Migration | Routes                                    | Tests                                                                                                 | Status  | Limits                                                                                                |
| --------------------------------------------------- | ---------------------------------- | ------------- | ----------------------------------------------------------------------------- | --------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------- | ----------------------------------------------------------------------------------------------------- |
| F1 Parcel + versioned geometry + spatial validation | FR-4.1, FR-4.4                     | ADR-0012      | `property/domain/parcel.py`, `shared/value_objects/polygon.py`, store parcels | 0005      | `/parcels*`                               | `test_polygon`, `test_parcel_and_permit_domain`, `test_compliance_api` (geometry, overlap, versions)  | VL / IP | Gaps between parcels not detected; self-intersection and overlaps are                                 |
| F2 Property master record                           | FR-5.1, FR-5.2                     | —             | `PropertyRecord`, store properties                                            | 0005      | `/properties*`                            | `test_compliance_api`                                                                                 | IP      | No ownership history, no property versioning (FR-5.1), no ownership graph                             |
| F3 Permit + approval records, history               | FR-5.1                             | —             | `permit/domain/permit.py`                                                     | 0005      | `/permits*`                               | `test_parcel_and_permit_domain`, `test_compliance_api`, `test_compliance_schema`                      | VL      | Fed by API only; no source-system connector                                                           |
| F4 Permit-to-parcel matching + discrepancy handling | FR-5.3                             | —             | `assess_parcel_match`, `resolve_permit_match`                                 | 0005      | `POST /permits`, `/permits/{id}/match`    | `test_compliance_api::test_permit_matching…`                                                          | VL      | 10 % plot-area tolerance is a placeholder                                                             |
| F5 Construction-change candidates + provenance      | FR-6.3                             | ADR-0014 §1–2 | `compliance/domain/candidate.py`                                              | 0005      | `/candidates*`                            | `test_candidate_and_case_domain`, `test_compliance_api`, `test_compliance_schema`                     | VL      | No detection pipeline; candidates are posted via API; fixtures simulated                              |
| F6 Deterministic evaluation (permit rules)          | FR-6.2, FR-6.3, FR-6.7             | —             | `compliance/domain/evaluation.py`                                             | 0005      | `/candidates/{id}/evaluations`            | `test_evaluation_domain`, `test_compliance_api`                                                       | IP      | Rules are code constants, not versioned configuration (FR-6.1); thresholds unapproved                 |
| F7 Officer verification + mandatory release gate    | —                                  | ADR-0014      | `decide_review`, `require_verified`, triggers                                 | 0005      | `/candidates/{id}/reviews`, `POST /cases` | `test_compliance_api` (gate, authz, reversal), `test_compliance_schema` (triggers)                    | VL      | Four-eyes / second approver not modelled                                                              |
| F8 Cases, assignment, lifecycle, findings           | FR-10.1, 10.3 (manual), 10.5, 10.6 | —             | `inspection/domain/case.py`                                                   | 0005      | `/cases*`                                 | `test_candidate_and_case_domain`, `test_compliance_api`                                               | VL / IP | No SLA (10.4), no auto-assign, no risk score in priority (10.2), no photo upload or drone request     |
| F9 Audit + immutability + provenance                | FR-20.1, FR-20.2, FR-27.5          | ADR-0011/0013 | `security_audit.py`, append-only triggers                                     | 0005      | all writes                                | `test_compliance_api` (events + chain), `test_compliance_schema`                                      | VL / IP | Audit events carry scalar ids only; evidence hashes are client-supplied, no WORM store (FR-27.1–27.3) |
| F10 Jurisdiction isolation (RLS)                    | NFR security                       | ADR-0011      | `tenancy.py`, policies                                                        | 0005      | all                                       | `test_compliance_schema`, `test_compliance_api::test_other_jurisdictions…`, `test_row_level_security` | VL      | Network isolation and IdP revocation timing remain unevidenced (R1–R8 open)                           |

An officer-facing web interface was **not** built in this phase; the API is the contract for it.

## Terminology and requirement-to-test traceability (ADR-0014 Amendment 1)

Candidate = unverified AI output; verified candidate = `confirmed` after an authorized review; inspection case = opened only from a verified candidate; case finding = inspector's site-visit record.

| Requirement (D1)                                              | Enforced in                              | Tests                                                                                                                                                                                                    |
| ------------------------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Candidates start `unverified`                                 | domain, `candidate_guard`                | `test_a_candidate_cannot_start_in_any_state_but_unverified`                                                                                                                                              |
| Status changes only via a recorded review                     | `candidate_guard`, review append-only    | `test_candidate_status_changes_only_through_a_matching_recorded_review`                                                                                                                                  |
| Candidate evidence is immutable                               | trigger                                  | `test_candidate_evidence_is_immutable`                                                                                                                                                                   |
| Only a confirmed candidate may create a case                  | service, domain, `inspection_case_guard` | `test_release_gate_rejects_a_case_for_a_candidate_not_confirmed`, `test_a_case_cannot_be_opened_from_an_unconfirmed_candidate`, `test_release_gate_accepts_a_confirmed_evaluated_candidate_exactly_once` |
| Verification needs permission in the candidate's jurisdiction | `authorize_verification`                 | `test_verification_requires_the_verify_permission_in_the_jurisdiction`                                                                                                                                   |
| Confirmation needs evaluation, provenance, justification      | domain, service                          | `test_confirmation_needs_an_evaluation_provenance_and_a_justification`                                                                                                                                   |
| No reversal while a case is open; one case per candidate      | trigger, service                         | `test_a_confirmed_candidate_with_an_open_case_cannot_be_un_confirmed`, `test_a_confirmation_cannot_be_reversed_while_its_case_is_open`, `test_only_one_case_per_candidate`                               |
| Concurrency, isolation, audit                                 | `expected_version`, RLS, audit           | `test_stale_case_versions_are_rejected`, RLS tests in `test_compliance_schema.py`, `test_full_workflow_from_parcel_to_closed_case`                                                                       |
