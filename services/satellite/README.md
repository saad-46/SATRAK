# satellite service (placeholder)

**Bounded context:** satellite imagery ingestion + preprocessing.

Future home of the `satellite-ingestion-service` and `satellite-preprocessing-service`
(TDD §3.6–3.7, Blueprint §2.7): scheduled scene acquisition, cloud/shadow masking,
orthorectification, and tiling into analysis-ready COGs.

**Planned stack:** Python 3.12 · FastAPI · Celery/Airflow · GDAL · Rasterio · S3/MinIO.

No implementation yet — this directory only reserves the bounded-context boundary
so imports and CI wiring have a stable home. Domain work begins in the Satellite
Engine epic.
