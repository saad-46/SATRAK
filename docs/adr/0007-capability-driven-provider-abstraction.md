# ADR-0007: Capability-driven imagery-provider abstraction

- **Status:** Accepted
- **Date:** 2026-07-06
- **Deciders:** SATRAK Engineering (Principal Architect / Principal EO Engineer)
- **Builds on:** [ADR-0002](0002-core-domain-platform.md),
  [ADR-0005](0005-earth-observation-bounded-context.md)
- **Ratifies:** ADR-EO-003 of
  [docs/epic-3-earth-observation-platform-spec.md](../epic-3-earth-observation-platform-spec.md)

## Context

The platform must integrate a heterogeneous set of imagery sources: Sentinel-2 (optical,
free, high-revisit), Sentinel-1 (**SAR** — no cloud%, has polarization), Landsat, Planet,
Maxar, Airbus, Cartosat, Bhuvan, and Google Earth Engine (a **compute-side** platform, not
a file feed). These differ in authentication, tasking, delivery format, band layout, and
licensing. A fixed provider enum in the core would force a code change in shared logic
every time a source is added — the opposite of the reusable-platform goal.

## Decision

**Providers implement an `ImageryProvider` port and declare their `ProviderCapabilities`;
a registry resolves the best provider for a request by matching required capabilities.**

1. `ImageryProvider` is a domain-level `Protocol` (mirroring the existing `StorageProvider`
   / `TaskQueue` ports), with `capabilities()`, `search()`, `task()`, `fetch()`, and
   `normalize()`.
2. `ProviderCapabilities` is a value object describing sensor type(s) (optical/SAR/
   hyperspectral), resolution range, bands, revisit cadence, tasking support, delivery
   format, licensing tier, auth scheme, and sync-vs-compute-side fetch. Consumers branch
   on **capability**, never on provider name.
3. `normalize()` maps provider-native metadata to the canonical `SceneMetadata` value
   object; where a field is absent (e.g., cloud% for SAR) the canonical model uses `None`
   plus a `sensor_type` discriminator. STAC is preferred where a provider exposes it.
4. Google Earth Engine is modeled as a provider with `compute_side=True`: its `fetch()`
   triggers a server-side export to object storage, then ingests through the normal
   lifecycle — no special-casing in the core.
5. **Isolation invariant:** adding a provider touches only
   `infrastructure/providers/<name>/` plus config/secret keys. Any change required outside
   that folder is treated as a design defect (leaked abstraction).

## Consequences

- **Positive:** New providers (including future ones) are additive and isolated; the core,
  application, tiling, storage, and API layers are untouched. This is the platform's
  acceptance test for extensibility (spec §5.8).
- **Positive:** SAR, optical, and compute-side sources coexist behind one abstraction.
- **Negative / cost:** Requires upfront modeling of a capability vocabulary rather than a
  simple enum; justified by the breadth of required providers.
- **Neutral:** Provider credentials, rate limiting, retries, and circuit breaking live in
  a shared `providers/base.py` client, keeping each adapter thin.

## Alternatives considered

- **Fixed provider enum + per-provider `if/elif` in core services:** rejected — every new
  source edits shared code, violating the open/closed principle and the reuse goal.
- **One adapter interface without capability descriptors:** rejected — the scheduler and
  registry need machine-readable capabilities to route "sub-meter optical, cloud<10%,
  ≤48h" style requests and to fail over between capable providers.
