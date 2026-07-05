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

This bounded context is **currently implemented in `apps/api/app/contexts/gis/`**
(the modular monolith). This directory is its **reserved extraction target**: when
sustained load, dedicated team ownership, or a data-residency requirement justifies a
separate deployable, the context is extracted here as its own FastAPI app +
`pyproject.toml`, per the extraction strategy in
[ADR-0003](../../docs/adr/0003-modular-monolith-first.md). Until then this directory
stays intentionally empty — **`apps/api/app/contexts/gis` is authoritative.**
