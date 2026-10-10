# ADR-0011: Tenancy — jurisdiction rows with PostgreSQL RLS (documented exception to PRD §3.3.2)

- **Status:** Accepted — owner decision 2026-10-10
- **Date:** 2026-10-10
- **Deciders:** Saad (owner), SATRAK Engineering
- **Relates to:** PRD §3.3 and §36.4 (schema-per-tenant default); Engineering Blueprint Part 10 #7;
  [ADR-0003](0003-modular-monolith-first.md)

## Context

The PRD (§3.3.2) states the **default** isolation pattern: _schema-per-tenant within a shared
PostgreSQL cluster_, tenant = city/ULB, state tenants may receive a dedicated cluster, wards are row
partitioning only, and cross-tenant cases are explicit and logged (§3.3.3). The Blueprint (Part 10 #7)
notes the mechanism was never designed and recommends row-level `jurisdiction_id` with RLS first,
deferring physical sharding. The documents were not aware of each other on this point. The code has
only an optional `AreaOfInterest.jurisdiction_id`.

**The PRD requirement is preserved unchanged.** This ADR records an approved _exception_ to its default
mechanism, not an edit of the PRD. A PRD change request should reference this ADR.

## Decision

1. Every tenant-owned table has a **non-null `jurisdiction_id`** with a foreign key and index.
   Child tables carry it too (no relying on joins for isolation).
2. **PostgreSQL Row-Level Security** is enabled and `FORCE`d on every such table. The application
   connects as a **non-owner, non-superuser, non-`BYPASSRLS`** role.
3. **Application authorization and RLS are complementary.** The application decides what a principal may
   do; RLS bounds which rows can ever be read or written. Neither replaces the other.
4. The jurisdiction context (permitted jurisdiction ids, derived server-side from the authenticated
   principal's assignments — never from client headers or parameters) is set per transaction with
   `SET LOCAL`. Connections returned to the pool must hold no context; a test proves no leakage
   between requests, including under concurrency and after exceptions/rollbacks.
5. **Cross-jurisdiction access is denied by default.** It exists only as explicit, time-bound,
   audited grants, and has negative tests.
6. **Background workers** receive an explicit, minimal jurisdiction scope per job; there is no
   ambient bypass. **Administrative and migration roles** are separate, not used by the web
   application, and every use of a bypass-capable role is logged.
7. **Residency/isolation requirements** are met by deploying the same schema and code into a
   dedicated database cluster per state or jurisdiction. Per-ULB schemas are not used by default.
8. Alembic remains one migration chain; every new tenant-owned table's migration includes its RLS
   policies, and a CI check fails if a table with `jurisdiction_id` lacks RLS.

## Trade-offs

| Aspect                   | Consequence                                                                                                                                                    |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Isolation strength       | Weaker than a schema wall by construction; compensated by FORCE RLS, a restricted role and negative tests. A missed table is a leak, hence the CI policy check |
| Operations               | One migration chain and one set of indexes instead of N schemas (PRD scale of 1,000+ ULBs makes schema fan-out costly — inference, not a measured figure)      |
| Cross-jurisdiction cases | Rows and grants instead of cross-schema calls; matches time-bound grants (FR-18.5)                                                                             |
| Residency                | Separate cluster per mandating state; same artefacts                                                                                                           |
| Reversibility            | Hard isolation can be added per jurisdiction later without changing the column                                                                                 |

## Consequences

- Identity/organization tables and a `jurisdiction` hierarchy (parent/child) are introduced in the
  access-control sprint.
- Persisted EO tables (future) must carry non-null `jurisdiction_id`.
- Open items: cross-tenant analytics (PRD L3969 vs AP1), the audit store's tenant scope, and
  tenant-less tables in the PRD (`model_version`, `evidence_package`, `physical_asset`) need explicit
  classification as global or tenant-owned.

## Implementation notes (access-control sprint, Story 7)

- **Mechanism.** Migration `0004` adds `app_permitted_jurisdictions()` and `app_current_user_id()`
  (read the transaction-local settings `app.jurisdiction_ids` / `app.user_id`). `organization` and
  `role_assignment` have RLS enabled and forced with a `tenant_isolation` policy (`USING` and
  `WITH CHECK`). `role_assignment` also has `own_assignments_read` (SELECT only), so a user's
  permissions can be resolved before any jurisdiction context exists. No setting means no rows.
- **Roles** (`infra/db/roles.sql`, cluster-level, created by a DBA, never by migrations):
  `satrak_migrator` (owner, runs Alembic via `migration_database_url`), `satrak_app` (API; not owner,
  no DDL, no `BYPASSRLS`, no UPDATE/DELETE on `audit_event`), `satrak_admin` (`BYPASSRLS`, break-glass).
- **Context helpers** in `app/db/rls.py`: `tenant_session` (request), `worker_session` (requires a
  non-empty explicit scope). `app/db/privileged.py::privileged_session` writes a `privileged_db.used`
  audit event first and fails closed if that cannot be recorded; an import-linter contract keeps the
  web layer from importing it.
- **Global (RLS-exempt) tables** are listed with reasons in `tests/db/test_row_level_security.py`;
  a test fails when a new table is not classified, or a table with `jurisdiction_id` is not protected.
- **Test finding:** pooled connections must not lose a `SET ROLE` on rollback-on-return; the test
  helper commits it. Production uses a login role, so this affects test infrastructure only.
- Still open: classification of the PRD's tenant-less tables and cross-tenant analytics.

## Table classification policy (owner decision 2026-10-10)

Every table is either **jurisdiction-owned** (non-null `jurisdiction_id`, forced RLS) or **system-global**.
Global tables are an explicit, reviewed allow-list with a stated reason in
`tests/db/test_row_level_security.py`; a new table in neither list fails that test, so new business tables
default to jurisdiction isolation. The PRD's tenant-less tables (`model_version`, `evidence_package`,
`physical_asset`) are not created yet and must be classified when they are.

## Hardening phase (owner approval 2026-10-10)

- **Repository scope fails closed.** `SceneQuery` and the timeline port take a required `AccessScope`.
  `TenantScope(ids)` matches only those jurisdictions (an empty set matches nothing); there is no default,
  so omitting it is a type error. `AccessContext.scope` builds it from the caller's permitted jurisdictions.
  The all-tenants `SystemScope(reason)` lives in `app.shared.domain.system_scope`, requires a non-empty
  reason, logs each creation, and an import-linter contract keeps `app.api` and `app.main` from importing it.
  Lookup by id still returns the aggregate; the endpoint authorizes it (403 contract).
- **Startup role validation.** The API refuses to start (`database_role_check=enforce`, the default; `warn`
  is rejected in staging and production) when its role is a superuser, has `BYPASSRLS`, inherits from such a
  role, can create roles or databases, owns tables, or when a jurisdiction table lacks enabled and forced
  RLS. In staging and production an unverifiable role also stops startup. Table classification lives in
  `app.db.tenancy`.
- **RLS verification.** `tests/db/test_row_level_security.py` runs as `satrak_app` and `satrak_admin` and covers
  the persisted tenant tables (`organization`, `role_assignment`): default deny, scoped reads, `WITH CHECK`
  on writes, forced RLS, pool-leak cases, policy coverage, role privileges, and the startup check.
- **Limitation.** Earth Observation data is still in memory (`InMemorySceneRepository`, AOI repository), so
  there are no persisted EO tables to put under RLS yet. Today EO isolation rests on `access.require`, the
  endpoint filters and the fail-closed repository scope. When SQL repositories replace them they must run in
  `tenant_session`, and new tables must be classified in `app.db.tenancy`.

### Hardening phase: known limits

- The startup role check inspects the `public` schema and only tables that have a
  `jurisdiction_id` column; tenant tables elsewhere would need the check extended.
- Earth Observation data is in memory today, so no persisted EO table exists to put under RLS;
  isolation there is enforced by the required repository `AccessScope`. Moving EO to PostgreSQL
  must add its tables to `TENANT_TABLES` with policies (the coverage test fails otherwise).
- The raw EO repositories (`get`, `list`, `add`, `update`, `get_by_provider_scene_id`) are unscoped and
  reserved for trusted pipeline code and tests. Request handlers must use `EarthObservationApi.scoped_scenes`
  / `scoped_aois` (a `ScopedRepository` that requires a scope: foreign reads raise `OutOfScopeError`, which
  the endpoint turns into the audited 403, and writes into or over a foreign jurisdiction are refused) or the
  scope-taking collection methods. An AST test fails if an endpoint touches `eo.scenes`/`eo.aois` otherwise.
  Pipeline services still receive the raw repositories, so a job handed a wrong id acts on it; those paths
  are not request-reachable but are not tenant-checked either.
- The deployment must ensure only the trusted proxy can reach the API port; `X-Forwarded-For`
  is honoured only from `trusted_proxy_cidrs`.

### Pre-publication pass: classification

The startup check now fails on (a) any table outside the extension-owned ones that is in neither
`TENANT_TABLES` nor `GLOBAL_TABLES`, in `public` or any other schema; (b) a table that is tenant-owned
(declared, or carrying `jurisdiction_id`) without enabled **and** forced RLS; (c) a declared tenant table that
is missing, has a nullable or absent `jurisdiction_id`, or has no policy; plus the role checks above, with
role membership tested via `MEMBER` (inherited privileges included). Extension tables (PostGIS) are exempt
through `pg_depend`. Nothing here verifies what a policy _says_; that is covered by the RLS tests.
