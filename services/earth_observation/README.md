# earth_observation service (placeholder)

**Bounded context:** Earth Observation — satellite & manned-aerial imagery platform.

Reserved microservice-extraction target for the `earth_observation` context: scheduled
scene acquisition, validation, metadata extraction, preprocessing (cloud/shadow masking,
orthorectification), and tiling into analysis-ready COGs, plus imagery storage,
time-series, and tile serving (TDD §3.6–3.7, Blueprint §2.7, and
[docs/epic-3-earth-observation-platform-spec.md](../../docs/epic-3-earth-observation-platform-spec.md)).

**Planned stack:** Python 3.12 · FastAPI · Celery (beat + chains) · GDAL · Rasterio ·
GeoAlchemy2 · S3/MinIO. See [ADR-0006](../../docs/adr/0006-raster-references-in-db-cog-in-object-storage.md),
[ADR-0007](../../docs/adr/0007-capability-driven-provider-abstraction.md),
[ADR-0008](../../docs/adr/0008-celery-behind-taskqueue-port-for-eo-jobs.md).

No implementation yet — this directory only reserves the extraction target so imports and
CI wiring have a stable home. Domain work happens inside the modular monolith first.

---

## Status — ADR-0003 (Modular Monolith First) + ADR-0005 / ADR-0010

This bounded context is **reserved for extraction**, not yet a separate deployable. Its
boundary is held at `apps/api/app/contexts/earth_observation/` in the modular monolith;
**that is the authoritative home**. This directory (`services/earth_observation`) is the
reserved extraction target: when sustained load, dedicated team ownership, or a
data-residency requirement justifies a separate deployable, the context is extracted here
as its own FastAPI app + `pyproject.toml` per the strategy in
[ADR-0003](../../docs/adr/0003-modular-monolith-first.md).

This context was originally reserved as `satellite`; it was generalized to
`earth_observation` (satellite + manned aerial imagery) per
[ADR-0005](../../docs/adr/0005-earth-observation-bounded-context.md), with the scope
affirmed and drone excluded by
[ADR-0010](../../docs/adr/0010-context-naming-review-earth-observation-vs-satellite.md).
**Drone/UAV imagery remains in the independent `drone` context.**
