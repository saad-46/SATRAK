# ADR-0010 (Review): Context naming — `satellite` vs `earth_observation`

- **Status:** **Accepted** — approved 2026-07-06; [ADR-0005](0005-earth-observation-bounded-context.md) amended accordingly
- **Date:** 2026-07-06
- **Deciders:** SATRAK Engineering (Principal Architect) — **owner-approved**
- **Reviews / Amends:** [ADR-0005](0005-earth-observation-bounded-context.md)
- **Type:** Architecture Decision Review (approved; the drone-scope correction is now in
  force and reflected in the ADR-0005 Amendment section)

## Purpose

Before Story 1 physically creates the context folder, renames `services/satellite`, and
bakes the name into APIs, events, storage keys, and the future service, stop and re-test
the naming decision made in ADR-0005. The name must remain correct for several years.

**This document renames nothing, moves no code, and does not modify ADR-0005.** It records
the comparison and a recommendation for the owner to accept or reject.

## The question

| Option | Context folder                |
| ------ | ----------------------------- |
| **A**  | `contexts/satellite/`         |
| **B**  | `contexts/earth_observation/` |

Both keep `drone`, `gis`, `ai`, `compliance` as separate contexts (per ADR-0003).

## What the source of truth already says

- **TDD line 35** frames the system as converting _"raw **earth-observation** data into
  actionable, legally-defensible enforcement cases."_ → "Earth observation" is **already
  the umbrella term in the ubiquitous language**, not an invention of this epic.
- **TDD §3.6/3.7 & Blueprint §2.7** name the _services_ `satellite-ingestion-service` /
  `satellite-preprocessing-service` and reserve `services/satellite`; **API paths are
  `/v1/satellite/scenes` and `/v1/satellite/tiles/{z}/{x}/{y}`.**
- **Blueprint §2.8** gives the `drone` context ownership of the **`drone_imagery`** table
  (plus `drone_missions`, `drone_flight_logs`, `photogrammetry_outputs`). Drone missions
  are **dispatched from a case** — a tactical, on-demand lifecycle, unlike scheduled
  AOI-based satellite acquisition.
- **Events are already platform-neutral**: `scene.ingested`, `tiles.ready` (not
  `satellite.*`).

The critical downstream fact for naming: **municipal illegal-construction programs
routinely use manned _aerial orthophotos_** (annual survey flights, often sub-meter and
cheaper/clearer than satellite for dense urban areas). Aerial is a realistic near-term
source, is **not** satellite, and is **not** drone — it is wide-area, scheduled,
provider/tasking-based imagery that shares the satellite acquisition & processing model.

## Evaluation (A vs B)

| Dimension                     | Option A `satellite`                                                                                                                               | Option B `earth_observation`                                                                                                                                                                                                                       | Edge                                                            |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| **DDD**                       | Names exactly today's subdomain, but the context will also hold aerial (non-satellite) imagery → the name would then under-describe its aggregate. | Names the stable domain concept (spaceborne + airborne imagery). Risk of over-breadth if it also tries to absorb drone.                                                                                                                            | **B** (with drone excluded)                                     |
| **Ubiquitous language**       | "Satellite" is the lay term; but the discipline — and the TDD — say "earth observation."                                                           | Matches the TDD's own umbrella term and industry usage (ESA/NASA/ISRO/Planet).                                                                                                                                                                     | **B**                                                           |
| **Future Drone integration**  | Drone stays cleanly in its own context; zero overlap.                                                                                              | Clean **only if** EO excludes drone imagery; ADR-0005's "drone imagery = EO provider family" conflicts with the Blueprint's `drone_imagery` ownership and is a leaky abstraction (a pilot upload tied to a mission ≠ a searchable/taskable scene). | **A**, unless B is scoped to exclude drone (see recommendation) |
| **Future AI integration**     | AI consumes `tiles.ready`; indifferent to source.                                                                                                  | Same; the platform-neutral "imagery" framing matches AI running over any source.                                                                                                                                                                   | Neutral (slight B)                                              |
| **GIS**                       | Consumes raster refs/tiles; name-agnostic.                                                                                                         | Same; GIS thinks in "imagery," not "satellite."                                                                                                                                                                                                    | Neutral (slight B)                                              |
| **Compliance**                | Evidence is "imagery at time T"; name-agnostic. Provenance records the real sensor/platform regardless.                                            | Same; evidence may include aerial + satellite.                                                                                                                                                                                                     | Neutral (slight B)                                              |
| **Long-term maintainability** | Brittle: adding aerial forces either a misnomer or a later rename (churn across folders, APIs, events, storage keys, service name).                | Adding aerial needs **no rename**. Higher discipline needed to prevent a "god context."                                                                                                                                                            | **B**                                                           |
| **Developer experience**      | Immediately concrete ("satellite stuff").                                                                                                          | Small learning curve (EO = satellite+aerial, **not** drone); mitigated by README/ADR.                                                                                                                                                              | **A** short-term, **B** long-term                               |
| **API clarity**               | Matches TDD's documented `/v1/satellite/*` exactly.                                                                                                | Requires a namespace decision: keep `/satellite/*` (mismatch with context) or adopt `/v1/eo/*` / `/imagery/*` (diverges from TDD — needs ADR).                                                                                                     | **A**                                                           |
| **Event naming**              | Would suggest `satellite.*`; but Blueprint chose neutral names.                                                                                    | Neutral names (`scene.ingested`, `tiles.ready`) align naturally with a platform-neutral context.                                                                                                                                                   | **B**                                                           |
| **Storage naming**            | Might imply `satellite/` prefixes.                                                                                                                 | Spec §7 keys are already `raw/{provider}/{sensor}/…` — platform-neutral, aligns with B.                                                                                                                                                            | **B**                                                           |
| **Microservice extraction**   | Extracts to `services/satellite` verbatim (TDD/Blueprint names).                                                                                   | Extracts to `services/earth_observation` (a rename from the reserved target — contemplated in ADR-0005).                                                                                                                                           | **A**                                                           |

**Tally:** B leads on ubiquitous language, maintainability, DDD (stable concept), event &
storage naming, and long-term DX. A leads on API clarity (TDD `/satellite/*`), microservice-
name alignment, drone separation, and short-term DX. The result turns almost entirely on
**one question: will the context ever hold non-satellite (aerial) imagery?**

## Trade-offs

- Choosing **A** optimizes for _document fidelity today_ (matches every `satellite-*` name
  in the TDD/Blueprint) and simplicity, at the cost of a **likely future rename** once
  aerial orthophotos arrive — and a rename is cheap now (no code) but expensive later
  (folders, `services/*`, API paths, event/storage conventions, client SDKs, docs).
- Choosing **B** optimizes for _the stable domain concept and the TDD's own umbrella
  language_, paying two upfront costs: (1) a documented divergence from the `satellite-*`
  service/API names, and (2) discipline to keep drone/UAV **out** of the context.
- The whole point of this review is that we are at the **free moment** to choose the
  forward-compatible name. Renaming a `satellite` context to `earth_observation` in year 2
  — after APIs, events, storage keys, and a `services/satellite` deployable exist — is
  exactly the churn a bounded-context name is supposed to avoid.

## Recommendation — **Option B (`earth_observation`)**, with two refinements to ADR-0005

Affirm the `earth_observation` name from ADR-0005 (it matches the TDD's own umbrella term
and future-proofs the realistic aerial source), **but correct the scope**, because the
review found ADR-0005 over-reached on drone:

1. **Scope EO to spaceborne + airborne imagery (satellite + future aerial).**
   **All drone/UAV imagery and missions remain wholly in the `drone` context** (per
   Blueprint §2.8's ownership of `drone_imagery`). This **reverses** ADR-0005's statement
   that "drone imagery is an EO provider family," which conflicted with the source of truth
   and was a leaky abstraction (a mission-bound pilot upload is not a searchable/taskable
   scene). The provider abstraction (ADR-0007) then generalizes cleanly across _spaceborne
   - airborne_ providers only.

2. **Put the reusable raster/COG/tiling/CRS primitives in a shared package** (e.g.,
   `packages/py-raster`, alongside the Blueprint's `py-geo`), **not inside the EO context.**
   The `drone` context reuses that package for its own imagery/photogrammetry **without
   importing the EO context** — preserving the ADR-0002/0003 dependency rule (contexts
   never import each other). This is how "the platform supports drone imagery" (original
   spec goal) is honored: drone reuses the _capability_, while the drone _context_ still
   owns drone acquisition.

This keeps `earth_observation` a cohesive, correctly-named context (satellite + aerial
acquisition & processing + primary owner of the shared raster capability) and keeps `drone`
clean — a standard, defensible **EO (spaceborne/airborne) vs UAV (drone)** industry split.

## Consequences to ratify on approval (not done in this review)

- **API namespace:** decide between retaining `/v1/satellite/*` (satellite-scoped, add
  `/v1/aerial/*` later) or adopting a neutral `/v1/eo/*` / `/v1/imagery/*`. Recommendation:
  neutral `/v1/eo/*` with `/v1/satellite/*` kept as a documented alias for continuity with
  TDD §10. **Decision deferred to Story 17 (API), recorded via ADR.**
- **Service extraction target:** `services/satellite` → `services/earth_observation`
  (already contemplated in ADR-0005; executed in Story 1 only after approval).
- **ADR hygiene:** ✅ done on approval — this document is **Accepted**, and ADR-0005's
  status header + a new Amendment section now record the drone-scope correction.
- **No new drone work:** the drone-scope correction is documentation-only; it changes no
  reserved `drone` boundary (it actually _restores_ Blueprint §2.8).

## If the owner prefers Option A instead

Then `earth_observation` should be reverted to `satellite` before Story 1: ADR-0005 would
be superseded by a new ADR, the ADR index updated, and the reusable raster capability still
factored into `packages/py-raster` (the shared-capability recommendation is independent of
the name). No code exists yet, so either choice is currently free.

## Alternatives considered

- **Keep ADR-0005 exactly as written (EO includes drone imagery as a provider family):**
  rejected — conflicts with Blueprint §2.8 `drone_imagery` ownership and models a mission-
  bound upload as a searchable scene (leaky).
- **A third name (`imagery`, `remote_sensing`, `geoimagery`):** `imagery` is vague;
  `remote_sensing` is a technique, not a domain boundary; neither matches the TDD's
  established "earth observation" term. Rejected in favor of the term already in the docs.
