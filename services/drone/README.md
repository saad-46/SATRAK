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

This bounded context is **currently implemented in `apps/api/app/contexts/drone/`**
(the modular monolith). This directory is its **reserved extraction target**: when
sustained load, dedicated team ownership, or a data-residency requirement justifies a
separate deployable, the context is extracted here as its own FastAPI app +
`pyproject.toml`, per the extraction strategy in
[ADR-0003](../../docs/adr/0003-modular-monolith-first.md). Until then this directory
stays intentionally empty — **`apps/api/app/contexts/drone` is authoritative.**
