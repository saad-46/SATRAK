# ADR-0008: Celery (beat + chains) behind the TaskQueue port for Earth Observation jobs

- **Status:** Accepted
- **Date:** 2026-07-06
- **Deciders:** SATRAK Engineering (Principal Architect / Principal Data Platform)
- **Builds on:** [ADR-0002](0002-core-domain-platform.md),
  [ADR-0003](0003-modular-monolith-first.md)
- **Ratifies:** ADR-EO-004 of
  [docs/epic-3-earth-observation-platform-spec.md](../epic-3-earth-observation-platform-spec.md)

## Context

The EO pipeline is background-heavy: scheduled discovery per AOI revisit cadence, streamed
downloads, validation, metadata extraction, preprocessing, and tiling. The source
documents disagree on the scheduler technology: **TDD §3.6 names Apache Airflow**, while
**Blueprint §2.7 names Celery beat + Celery task chains**. This inconsistency (finding F-4
in the Epic 3 spec) must be resolved before implementation.

The shared kernel already provides a `TaskQueue` port (`app/shared/services/background_task.py`)
with an `InlineTaskQueue` fake, precisely so the executor choice is an infrastructure
detail, not a domain dependency.

## Decision

**Standardize Earth Observation background work on Celery (beat for scheduling, chains for
the pipeline), wired behind the existing `TaskQueue` port.**

1. Celery **beat** drives per-AOI discovery polling; a Celery **chain** implements
   `download → validate → metadata → preprocess → tile`.
2. Two queues by resource profile: `eo_io` (discovery, download, validation, thumbnail,
   metadata, cleanup, retention) and `eo_cpu` (preprocessing, tiling, pyramids,
   reprocessing, mosaicking); plus `eo_schedule` (beat) and `eo_dlq` (dead-letter).
3. The Celery adapter lives in `earth_observation/infrastructure/tasks/`; application code
   depends only on the `TaskQueue` port. Tests use `InlineTaskQueue`.
4. **Airflow remains a documented future option** for complex cross-service DAGs; because
   scheduling sits behind the port and the `EventBus` seam, switching later requires no
   change to publishers/handlers (consistent with the ADR-0003 extraction strategy).

## Consequences

- **Positive:** Resolves the Airflow-vs-Celery inconsistency in favor of the newer,
  more specific Blueprint guidance; one scheduling stack for the pilot.
- **Positive:** No new abstraction introduced — reuses the shared `TaskQueue` port, so the
  domain/application layers stay executor-agnostic and unit-testable with the inline fake.
- **Positive:** Backlog-priority reordering (Blueprint §2.7) and autoscale-by-backlog
  (TDD §3.7) are queue policies over Celery, not bespoke infrastructure.
- **Negative:** Celery does not model long, branching DAGs as expressively as Airflow;
  acceptable for the linear EO pipeline, and reversible via the port if that changes.

## Alternatives considered

- **Apache Airflow now (TDD §3.6):** rejected for the pilot — heavier operational
  footprint than the EO pipeline's mostly-linear chain needs; kept as a future option.
- **A bespoke scheduler in application code:** rejected — reinvents Celery/beat, couples
  scheduling to domain logic, and bypasses the existing port.
- **RQ / Arq:** viable behind the same port, but Celery is the Blueprint's named choice and
  has the richer beat/chains/priority ecosystem the pipeline uses.
