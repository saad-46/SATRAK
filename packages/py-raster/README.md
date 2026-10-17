# py-raster (scaffold)

Shared **raster-processing engine** abstractions (GDAL/rasterio) — crop, clip, merge, warp/
reproject, orthorectify, normalize, cloud-mask, histogram/stats, pyramids, COG, compression
(spec §9). Kept out of the shared kernel because GDAL/rasterio are heavy infrastructure
dependencies (the kernel is stdlib-only).

**Status — Epic 3 Story 1:** scaffold only. Contains the package structure, a **placeholder
interface** (`RasterEngine`), and a tests folder. **No implementation yet** — the concrete
GDAL/rasterio adapter lands in a later Earth Observation story. Reusable by the
`earth_observation` and `drone` contexts without cross-context imports (ADR-0010).

## Structure

```
py-raster/
├── pyproject.toml
├── src/py_raster/
│   ├── __init__.py
│   └── interfaces.py   # RasterEngine (Protocol, placeholder)
└── tests/
    └── test_smoke.py
```

Not yet wired into CI.
