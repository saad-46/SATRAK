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

This bounded context is **currently implemented in `apps/api/app/contexts/satellite/`**
(the modular monolith). This directory is its **reserved extraction target**: when
sustained load, dedicated team ownership, or a data-residency requirement justifies a
separate deployable, the context is extracted here as its own FastAPI app +
`pyproject.toml`, per the extraction strategy in
[ADR-0003](../../docs/adr/0003-modular-monolith-first.md). Until then this directory
stays intentionally empty — **`apps/api/app/contexts/satellite` is authoritative.**
