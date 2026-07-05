# gis service (placeholder)

**Bounded context:** shared geospatial query engine.

Future home of the `gis-service` (TDD §3.5, §6; Blueprint §2.9): intersection/buffer
queries, spatial joins, coordinate transforms, deterministic encroachment checks,
and OGC (WFS/WMS/MVT) endpoints.

**Planned stack:** Python 3.12 · FastAPI · PostGIS · GeoAlchemy2 · Shapely · GDAL/GEOS.

No implementation yet — boundary reservation only. Domain work begins in the GIS
Engine epic.

---

## Status — ADR-0003 (Modular Monolith First)

This bounded context is **reserved**, not yet implemented. Its boundary is held as
a placeholder at `apps/api/app/contexts/gis/` in the modular monolith; the domain
model is built in the context's dedicated epic (only `core`, `identity`, and
`organization` are implemented today). This directory (`services/gis`) is the
**reserved extraction target** for the `gis` context: when sustained load,
dedicated team ownership, or a data-residency requirement justifies a separate
deployable, it is extracted here as its own FastAPI app + `pyproject.toml` per the
strategy in [ADR-0003](../../docs/adr/0003-modular-monolith-first.md). Until then,
**`apps/api/app/contexts/gis` is the authoritative home** for the boundary.
