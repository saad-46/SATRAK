# infrastructure

Adapters and the only place heavy libraries/frameworks appear (GDAL, rasterio, GeoAlchemy2, boto3, Celery). Implements the domain **ports**; swappable without touching business logic. Reuses `packages/py-geo`, `packages/py-raster`, `packages/py-imagery`.
