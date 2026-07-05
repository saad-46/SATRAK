# ADR-0001: Monorepo and engineering foundation

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** SATRAK Engineering

## Context

Epic 1 establishes the engineering skeleton before any domain logic. SATRAK is a
polyglot system (TypeScript frontend, Python backend/AI, PostGIS data layer)
whose service boundaries are still being tuned, and cross-cutting changes (a new
case status, a shared type) will touch multiple layers in year one.

## Decision

1. **Monorepo** managed with pnpm workspaces + Turborepo (JS/TS) and per-app
   `pyproject.toml` (Python), with a root `Makefile` as the cross-language entry
   surface.
2. **Single `apps/api` FastAPI application** for the foundation rather than the
   eleven separate microservices in the blueprint. The bounded contexts are
   reserved as documented `services/*` placeholders and extracted into their own
   deployables when their epics begin. This avoids standing up eleven empty
   services before any domain logic exists, while keeping the target boundaries
   explicit.
3. **Clean architecture** inside the API (`api → services → repositories → db`,
   all may depend on `domain`, `domain` depends on nothing).
4. **Infrastructure under `infra/`** (compose, k8s, terraform) per the blueprint,
   which realizes the "docker/" folder from the Epic 1 brief.

## Consequences

- One install, one CI graph, atomic cross-cutting PRs; affected-only CI keeps it
  fast.
- The `apps/api` → microservices split is a known future migration; the
  schema-per-context and clean-architecture layering are chosen now so that split
  is a deployment change, not a rewrite.
- Contributors need both Node and Python toolchains locally.

## Alternatives considered

- **Polyrepo:** rejected for year-one — coordination overhead and shared-type
  drift outweigh isolation benefits at this stage.
- **Eleven microservices from day one:** rejected — premature operational
  complexity with no domain logic to justify it.
