# drone service (placeholder)

**Bounded context:** drone mission planning + photogrammetry.

Future home of the `drone-service` (TDD §3.8, §8; Blueprint §2.8): mission planning,
flight-log ingestion, photogrammetric reconstruction (orthomosaic/DSM/point cloud),
and mission reporting.

**Planned stack:** Python 3.12 · FastAPI · OpenDroneMap-class pipeline · GPU workers · S3/MinIO.

No implementation yet — boundary reservation only. Domain work begins in the Drone
Operations epic.

---

## Status — ADR-0003 (Modular Monolith First)

This bounded context is **reserved**, not yet implemented. Its boundary is held as
a placeholder at `apps/api/app/contexts/drone/` in the modular monolith; the domain
model is built in the context's dedicated epic (only `core`, `identity`, and
`organization` are implemented today). This directory (`services/drone`) is the
**reserved extraction target** for the `drone` context: when sustained load,
dedicated team ownership, or a data-residency requirement justifies a separate
deployable, it is extracted here as its own FastAPI app + `pyproject.toml` per the
strategy in [ADR-0003](../../docs/adr/0003-modular-monolith-first.md). Until then,
**`apps/api/app/contexts/drone` is the authoritative home** for the boundary.
