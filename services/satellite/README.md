# satellite service (placeholder)

**Bounded context:** satellite imagery ingestion + preprocessing.

Future home of the `satellite-ingestion-service` and `satellite-preprocessing-service`
(TDD §3.6–3.7, Blueprint §2.7): scheduled scene acquisition, cloud/shadow masking,
orthorectification, and tiling into analysis-ready COGs.

**Planned stack:** Python 3.12 · FastAPI · Celery/Airflow · GDAL · Rasterio · S3/MinIO.

No implementation yet — this directory only reserves the bounded-context boundary
so imports and CI wiring have a stable home. Domain work begins in the Satellite
Engine epic.

---

## Status — ADR-0003 (Modular Monolith First)

This bounded context is **reserved**, not yet implemented. Its boundary is held as
a placeholder at `apps/api/app/contexts/satellite/` in the modular monolith; the domain
model is built in the context's dedicated epic (only `core`, `identity`, and
`organization` are implemented today). This directory (`services/satellite`) is the
**reserved extraction target** for the `satellite` context: when sustained load,
dedicated team ownership, or a data-residency requirement justifies a separate
deployable, it is extracted here as its own FastAPI app + `pyproject.toml` per the
strategy in [ADR-0003](../../docs/adr/0003-modular-monolith-first.md). Until then,
**`apps/api/app/contexts/satellite` is the authoritative home** for the boundary.
