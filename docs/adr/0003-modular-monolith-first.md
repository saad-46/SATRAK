# ADR-0003: Modular Monolith First

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** SATRAK Engineering (Principal Architect / Lead Backend)
- **Extends:** [ADR-0001](0001-monorepo-and-engineering-foundation.md) ·
  **Builds on:** [ADR-0002](0002-core-domain-platform.md)

## Context

The Engineering Blueprint (Part 1–2) describes the **target** production topology
as eleven independently deployable microservices (`services/auth-service`,
`services/case-service`, `services/gis-service`, …), schema-per-service, wired by
an event bus. The TDD (§1–3) likewise assumes a microservice architecture at
national scale.

Epic 1 (ADR-0001) already chose **not** to stand up eleven empty services before
any domain logic existed, and instead build a single `apps/api` FastAPI
application with the target boundaries reserved as `services/*` placeholders. Epic
2 (ADR-0002) then implemented the reusable domain platform **inside** that app as
`app/shared` (shared kernel) + `app/contexts/*` (bounded contexts).

The Epic 2 release audit flagged an apparent ambiguity: bounded-context names
exist in **two** places — `apps/api/app/contexts/<ctx>` (real code) and
`services/<ctx>` (empty placeholders) — with no single document stating which is
authoritative or how one becomes the other. This ADR removes that ambiguity by
making the strategy explicit and defining the migration path. It does not change
code; it ratifies and documents the direction ADR-0001 started.

## Decision

**Adopt a Modular Monolith as the deployment unit for the MVP and early
jurisdictions, structured so that extraction to the Blueprint's microservices is
a deployment change, not a rewrite.**

Concretely:

1. **One deployable today** — `apps/api` is the single FastAPI process. All
   bounded contexts live in `apps/api/app/contexts/<ctx>` and share one database
   (schema-per-context logically) and one process.
2. **Microservice-ready boundaries** — each `app/contexts/<ctx>` is a strict
   bounded context: it depends only on the shared kernel, never on another
   context's internals, and communicates via ids + domain events. This is the
   same boundary a future `services/<ctx>` will own.
3. **`services/*` are the reserved extraction targets** — they remain as
   documented placeholders (a `README` each) naming the future home of the
   corresponding `app/contexts/<ctx>`. They are intentionally empty until a
   context's load, team ownership, or data-residency need justifies extraction.
   **`app/contexts/<ctx>` is authoritative; `services/<ctx>` is its future
   address.**
4. **The event bus is the seam** — contexts already publish/consume via the
   `EventBus` abstraction (ADR-0002). In-process today (`InMemoryEventBus`);
   swapping to Kafka/RabbitMQ at extraction time requires no publisher/handler
   changes.

## Why a modular monolith wins for this stage

| Concern                  | Modular monolith                                                                                                     | Eleven microservices now                                         |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| **MVP speed**            | One deploy, one pipeline, one DB — ship the pilot fast                                                               | 11 deploys, 11 pipelines, cross-service infra before any feature |
| **Maintainability**      | Boundaries enforced in-code (import-linter) with the option to refactor a boundary cheaply while it's still settling | A wrong boundary is a cross-repo/deploy migration                |
| **Testing**              | In-process integration tests hit real collaborators; no network mocks                                                | Contract/integration tests need a running mesh                   |
| **Performance**          | In-process calls, no network hops for the MVP's modest load                                                          | Network + serialization overhead with no scale benefit yet       |
| **Developer experience** | One clone, one `make dev`, atomic cross-context PRs                                                                  | Multi-repo coordination, version skew                            |
| **National scaling**     | Extract the hot contexts (satellite/AI/case) to services when load demands, along the seams already in place         | Full operational complexity from day one                         |

This is the well-trodden "monolith first" path (Fowler): microservices earn their
operational cost only once boundaries are proven and load is real — exactly the
Blueprint's own Part 1 note that "boundaries are still being tuned in year one."

## Tradeoffs (accepted)

- **Shared database / blast radius** — a bad migration or a runaway query can
  affect all contexts. Mitigated by schema-per-context discipline, connection
  pooling, and the ability to extract a context to its own DB later.
- **Single scaling unit** — the whole app scales together until a context is
  extracted. Acceptable for the pilot; the CPU/GPU-heavy work (satellite/AI) is
  already destined for `services/` + separate node pools per the Blueprint.
- **Team scaling** — one codebase can bottleneck many teams. Not a constraint at
  current team size; extraction relieves it when it becomes one.
- **Discipline dependency** — the boundaries are only as real as they're
  enforced. **Mitigated concretely by import-linter in CI** (contracts in
  `pyproject.toml`), which fails the build on any outward dependency.

## Service extraction strategy (monolith → microservice)

When a context needs its own deployable (triggers: sustained load requiring
independent scaling, a dedicated team, a data-residency/WORM requirement, or a
GPU/compute profile), extract it in this order:

1. **Confirm the seam is clean** — import-linter already guarantees the context
   imports only `app.shared` and talks to peers via events. No code detangling
   needed.
2. **Package the shared kernel** — publish `app/shared` as an installable Python
   package the new service depends on (see the "Shared-kernel packaging path" in
   [ARCHITECTURE.md](../../apps/api/ARCHITECTURE.md)). Until then, no context may
   be extracted.
3. **Move the context** into `services/<ctx>/` as its own FastAPI app + its own
   `pyproject.toml`, importing the shared-kernel package.
4. **Split the schema** — move the context's tables to its own database/schema;
   its Alembic history moves with it (schema-per-context makes this a
   connection-string change, per ADR-0001).
5. **Promote the event bus** — point the `EventBus` port at the real broker.
   Publishers/handlers are unchanged.
6. **Route at the gateway** — the API gateway routes `/api/v1/<ctx>/*` to the new
   service; the monolith stops mounting that router.

Each step is independently shippable and reversible.

## Context boundaries (authoritative list)

Implemented now: `core` (shared generic entities), `identity`, `organization`.
Reserved (empty `app/contexts/<ctx>` + `services/<ctx>`): `property`, `permit`,
`inspection`, `satellite`, `gis`, `drone`, `compliance`, `analytics`,
`reporting`, `administration`, `notification`. These map 1:1 to the Blueprint
Part 2 modules and the TDD §3 microservices.

## Future evolution

The likely first extractions, by the Blueprint's own risk analysis (Part 10), are
**satellite** and **AI/inference** (compute profile) and **case/compliance**
(load + event volume) — not auth or organization, which stay in the monolith
longest. The monolith may itself split into a small number of "modular
services" (e.g. an identity+org service, a case+property service) before, or
instead of, a full eleven-way split — the boundaries permit any grouping.

## Consequences

- The `services/*` vs `app/contexts/*` ambiguity is resolved: **contexts are
  authoritative, services are reserved addresses**, documented in each
  `services/<ctx>/README.md`.
- A new hard CI gate (import-linter) prevents boundary erosion, making the
  "extraction is cheap" promise enforceable rather than aspirational.
- No code moved in this ADR; it is a documentation + governance decision.

## Alternatives considered

- **Eleven microservices now (literal Blueprint):** rejected for the MVP —
  premature operational complexity, slower delivery, boundaries not yet proven.
- **Unstructured monolith:** rejected — would forfeit the cheap-extraction
  property; the whole point is monolith _with enforced seams_.
- **Delete `services/*` placeholders:** rejected — they encode the Blueprint's
  target and the extraction addresses; keeping them (documented) is less
  ambiguous than removing the target topology entirely.
