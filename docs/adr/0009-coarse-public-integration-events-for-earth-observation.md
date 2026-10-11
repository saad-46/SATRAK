# ADR-0009: Coarse public integration events for Earth Observation

- **Status:** Accepted
- **Date:** 2026-07-06
- **Deciders:** SATRAK Engineering (Principal Architect / Lead Backend)
- **Builds on:** [ADR-0002](0002-core-domain-platform.md),
  [ADR-0005](0005-earth-observation-bounded-context.md)
- **Ratifies:** ADR-EO-005 of
  [docs/epic-3-earth-observation-platform-spec.md](../epic-3-earth-observation-platform-spec.md)

## Context

The EO lifecycle emits many fine-grained domain events (`ImageDiscovered`,
`ImageDownloaded`, `ImageValidated`, `MetadataExtracted`, `ImageStored`, `SceneProcessed`,
`TileGenerated`, …). Downstream contexts (AI Orchestration, GIS, Property) need to react to
imagery becoming available, but should not couple to every internal step — otherwise every
EO pipeline refinement becomes a breaking change for consumers. The Blueprint (§2.7) names
exactly two integration events for this boundary: `scene.ingested` and `tiles.ready`.

Per ADR-0002, events are recorded on aggregates and dispatched by the Unit of Work after a
successful commit; the `EventBus` is broker-agnostic (in-memory now, Kafka later).

## Decision

**Expose `scene.ingested` and `tiles.ready` as the stable _public_ integration contract;
keep the granular lifecycle events _internal_ to the EO context.**

1. `tiles.ready` (a rollup emitted when a scene's tiles are complete) is the trigger for
   AI Orchestration; `scene.ingested` signals a scene is fully available for GIS/property
   correlation. These two names match the Blueprint verbatim.
2. Fine-grained events remain for intra-context orchestration and observability but are not
   part of the cross-context contract; consumers must not subscribe to them.
3. Both public events carry stable, minimal payloads (ids + URIs + key metadata), so the EO
   context can evolve its internals freely without breaking subscribers.

## Consequences

- **Positive:** Downstream contexts couple to a small, stable contract; EO internals
  (extra pipeline stages, provider changes) evolve without downstream breakage.
- **Positive:** Matches the Blueprint's named events, preserving continuity with the TDD
  data-flow (§4) and the AI trigger contract.
- **Neutral:** Requires discipline (and code review) to keep granular events private; the
  bounded-context boundary and event naming make the intent explicit.
- **Negative:** A rollup event (`tiles.ready`) needs a completion check across a scene's
  tiles; a modest amount of aggregation logic in the tiling application service.

## Alternatives considered

- **Publish all granular events as the public contract:** rejected — couples consumers to
  EO internals; every pipeline change risks a cross-context breaking change.
- **A single "scene.available" event only:** rejected — AI needs the tile-level trigger
  (`tiles.ready`) distinct from general availability (`scene.ingested`) per the Blueprint
  data flow; collapsing them loses that distinction.
