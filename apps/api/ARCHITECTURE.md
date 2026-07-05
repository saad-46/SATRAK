# SATRAK API — Architecture

This document describes the domain platform introduced in **Epic 2** (Core Domain
& Platform Foundation): the reusable backbone every future SATRAK module builds
on. It complements [README.md](README.md) (how to run) with _how the code is
organized and why_.

## Layers & the dependency rule

Clean Architecture. Dependencies point **inward**; inner layers never import outer
ones.

```
            ┌─────────────────────────────────────────────┐
            │  api/           HTTP boundary (FastAPI)       │  ← outermost
            │  db/            SQLAlchemy, sessions, ORM     │
            ├─────────────────────────────────────────────┤
            │  contexts/*/    bounded-context domain models │
            ├─────────────────────────────────────────────┤
            │  shared/        shared kernel (pure Python)    │  ← innermost
            │    domain · value_objects · events ·          │
            │    persistence · services · pagination        │
            └─────────────────────────────────────────────┘
        core/  = cross-cutting infra (config, logging, errors, metrics)
```

- **`shared/`** depends on nothing else in `app`. Pure Python — no FastAPI, no
  SQLAlchemy, no pydantic. Fully unit-testable in microseconds.
- **`contexts/<name>/domain/`** depend only on `shared`. They never import each
  other (contexts collaborate via ids + domain events, not direct references).
- **`db/`** and **`api/`** are infrastructure/boundary: they depend inward on
  domain + shared, and are the only places frameworks appear.
- **`core/`** holds cross-cutting concerns (config, logging, error mapping,
  metrics) used by the boundary layers.

The rule is enforceable with an import linter as the codebase grows; today it is
maintained by construction (the shared kernel imports only the standard library).

## Folder structure

```
app/
├── shared/                     # SHARED KERNEL (pure, reusable)
│   ├── domain/                 # Entity, AggregateRoot, ValueObject, events, errors, specification
│   ├── value_objects/          # Email, Money, Coordinates, GeoPoint, BoundingBox, Area, ...
│   ├── events/                 # EventBus (in-memory now, broker-backed later)
│   ├── persistence/            # Repository + UnitOfWork abstractions (+ in-memory)
│   ├── services/               # platform ports: clock, id, cache, storage, audit, ...
│   └── pagination.py           # PageRequest / Page / Sort / Filter
├── contexts/                   # BOUNDED CONTEXTS
│   ├── core/domain/            # generic entities: Document, Tag, Comment, Task, Notification, ...
│   ├── identity/domain/        # UserProfile, Role, Permission
│   ├── organization/domain/    # Organization, Department
│   └── {property,permit,inspection,satellite,gis,drone,
│        compliance,analytics,reporting,administration,notification}/   # reserved
├── db/                         # Base + ORM mixins (BaseEntity/AuditEntity/VersionedEntity), session
├── core/                       # config, logging, middleware, errors, problem_details, metrics, openapi
├── api/                        # routers, deps, response schemas, pagination params, v1 endpoints
├── testing/                    # factories + fakes (shipped for reuse by every context's tests)
└── main.py                     # app factory
```

## Domain model

Every entity carries the same audit envelope: `id` (UUID), `created_at`,
`updated_at`, `created_by`, `updated_by`, `version` (optimistic lock),
`is_deleted` / `deleted_at` (soft delete). Three base types:

- **`Entity`** — identity + lifecycle (`touch`, `soft_delete`, `restore`), equality
  by type + id.
- **`StatefulEntity`** — adds a generic `EntityStatus`.
- **`AggregateRoot`** — the consistency boundary; the only entity that records
  `DomainEvent`s (`record_event` / `pull_events`).

Aggregates expose a `create(...)` factory that records an `EntityCreated` event and
enforce invariants via `_check_invariants()` — the single chokepoint that keeps an
aggregate from ever being observed in an invalid state. **Business workflows are
intentionally not implemented in Epic 2** — only lifecycle mechanics.

### Value objects

Immutable (`frozen` dataclasses), compared by value, self-validating on
construction (raising `ValueValidationError`). Geospatial ones (`Coordinates`,
`GeoPoint`, `BoundingBox`) are storage-agnostic and default to WGS84; `Money` uses
`Decimal` with currency-safe arithmetic; measurements normalize to SI base units.

## Events & the unit of work

Aggregates raise events; the **Unit of Work** owns dispatch. On `commit()` it
persists, then collects events from tracked aggregates and publishes them via the
**EventBus** — so no event escapes for a rolled-back change (no dual-write
problem), and event publishing stays out of the domain model. The bus is
broker-agnostic: `InMemoryEventBus` today, Kafka/RabbitMQ later, with zero changes
to publishers or handlers.

## Persistence

`Repository[T]` and `UnitOfWork` are protocols. Application services depend on the
abstraction; concrete SQLAlchemy adapters and `InMemoryRepository`/
`InMemoryUnitOfWork` both satisfy it. ORM tables map to `VersionedEntity` (the full
audit envelope). No feature tables exist yet (Epic 2 scope).

## Errors → Problem Details

Domain errors (`DomainError` and subclasses) are transport-agnostic. The API
boundary maps them — and deliberate `AppError`s, validation failures, and
unhandled exceptions — into **RFC 9457 `application/problem+json`** responses with
stable `code` and `request_id` extensions, so every client handles failures
uniformly.

## Extension points (how a new module plugs in)

1. Add a bounded context under `contexts/<name>/domain/`, depending only on
   `shared`.
2. Model aggregates on `AggregateRoot`; reuse value objects; raise domain events.
3. Define a `Repository`/`UnitOfWork` implementation in `db/` mapping to
   `VersionedEntity`.
4. Add application services depending on the `shared.services` ports; wire real
   adapters (storage, search, notification) behind those same interfaces.
5. Expose endpoints under `api/v1/`, reusing `PageParams`, `PageResponse`, and the
   problem-details error handling.
6. Test with `app.testing.factories` and `app.testing.fakes`.

## Deployment topology (modular monolith → services)

SATRAK ships as a **modular monolith**: one `apps/api` process today, with every
bounded context under `app/contexts/<ctx>` built as a strict, independently
extractable seam. The Blueprint's target is eleven microservices; the top-level
`services/<ctx>/` directories are the **reserved extraction addresses** for each
context — intentionally empty until load, ownership, or data-residency justifies a
split. **`app/contexts/<ctx>` is authoritative; `services/<ctx>` is its future
home.** The rationale, tradeoffs, and step-by-step extraction strategy are in
[ADR-0003](../../docs/adr/0003-modular-monolith-first.md).

The dependency rule that keeps extraction cheap is **machine-enforced by
import-linter** (`[tool.importlinter]` in `pyproject.toml`, run in CI): the shared
kernel and each context are contractually forbidden from depending outward.

### Shared-kernel packaging path

Today `app/shared` is imported in-process. It cannot be imported by a future
`services/<ctx>` (separate deployable) as-is. The prepared — but **not yet
executed** (no premature extraction) — path is:

1. When the first context is extracted, move `app/shared` into an installable
   Python package (e.g. `packages/python/satrak-core` with its own
   `pyproject.toml`), published to the internal index.
2. `apps/api` and each `services/<ctx>` add it as a normal dependency; imports
   change from `app.shared.*` to `satrak_core.*` (a mechanical rename).
3. Because the shared kernel is pure-Python with zero framework/app dependencies
   (enforced by import-linter), it packages cleanly with no untangling.

Until step 1's trigger, keeping the kernel in `app/shared` avoids the overhead of
versioning/publishing a package that has exactly one consumer.

## Related decisions

- [ADR-0001](../../docs/adr/0001-monorepo-and-engineering-foundation.md) — monorepo & foundation
- [ADR-0002](../../docs/adr/0002-core-domain-platform.md) — core domain platform (this design)
- [ADR-0003](../../docs/adr/0003-modular-monolith-first.md) — modular monolith first & extraction strategy
- [ADR-0004](../../docs/adr/0004-ruff-formatting-toolchain.md) — Ruff lint/format toolchain
