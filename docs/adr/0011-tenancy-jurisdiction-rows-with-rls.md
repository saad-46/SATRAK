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
