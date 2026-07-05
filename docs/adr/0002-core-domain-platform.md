# ADR-0002: Core domain platform (shared kernel + bounded contexts)

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Principal Architect / Lead Backend

## Context

Epic 2 builds the reusable business platform every future SATRAK module
(Authentication, GIS, Satellite, AI, Drone, Compliance, Reporting, Analytics)
depends on. It must serve hundreds of municipalities and millions of properties,
so the domain model and platform abstractions have to be correct, testable, and
stable _before_ feature work begins. Epic 1 left thin placeholder stubs
(`app/domain`, `app/repositories`, `app/services`) that were insufficient for a
DDD design.

## Decision

Adopt Clean Architecture + DDD with a **pure-Python shared kernel** and
**bounded contexts**:

1. **`app/shared/`** — the shared kernel: base entities (`Entity`,
   `StatefulEntity`, `AggregateRoot`), value objects, domain events + an
   `EventBus` abstraction, `Repository`/`UnitOfWork` abstractions, platform
   service **ports** (clock, id, cache, storage, audit, file, notification,
   search, background-task, validation, configuration, logging), and pagination.
   It imports only the standard library — no FastAPI, SQLAlchemy, or pydantic.
2. **`app/contexts/<name>/`** — one package per bounded context. `core`,
   `identity`, and `organization` ship domain models now; the remaining feature
   contexts are reserved as boundaries so ownership and dependency rules exist
   from day one.
3. **Audit envelope on every entity** — UUIDv4 id, created/updated timestamps and
   actors, an optimistic-concurrency `version`, and soft-delete. Mirrored by ORM
   mixins (`BaseEntity` / `AuditEntity` / `VersionedEntity`).
4. **Events dispatched by the Unit of Work** after a successful commit, never from
   inside the domain model — avoiding the dual-write problem.
5. **RFC 9457 Problem Details** for all error responses, with `code` and
   `request_id` extensions.
6. Superseded Epic-1 stubs (`app/domain`, `app/repositories`, `app/services`) were
   removed; their concepts now live in the shared kernel and per-context layers.

The dependency rule: `api`/`db` → `contexts` → `shared`. Inner layers never import
outer ones.

## Consequences

- **Positive:** the domain layer is framework-free and unit-testable in
  milliseconds (no DB needed); external systems (brokers, object storage, search)
  plug in behind existing ports without touching domain code; every module
  inherits consistent pagination, errors, and auditing.
- **Positive:** business workflows are deliberately excluded, keeping this epic a
  stable backbone rather than a moving target.
- **Negative / cost:** more indirection (ports + adapters) than a CRUD app needs;
  contributors must respect the dependency rule (to be enforced later with an
  import linter).
- **Neutral:** concrete SQLAlchemy repositories and feature tables are deferred to
  each feature epic; only in-memory implementations exist now.

## Alternatives considered

- **Anemic/CRUD models with services doing everything** — rejected: does not scale
  to the compliance workflow complexity SATRAK needs and scatters invariants.
- **Framework-coupled domain (pydantic/SQLAlchemy entities)** — rejected: couples
  the core to infrastructure, slows tests, and leaks persistence concerns into
  business rules.
- **A single flat module instead of bounded contexts** — rejected: would not hold
  up across a dozen teams/epics building on the same core.
