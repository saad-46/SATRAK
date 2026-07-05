# drone service (placeholder)

**Bounded context:** drone mission planning + photogrammetry.

Future home of the `drone-service` (TDD §3.8, §8; Blueprint §2.8): mission planning,
flight-log ingestion, photogrammetric reconstruction (orthomosaic/DSM/point cloud),
and mission reporting.

**Planned stack:** Python 3.12 · FastAPI · OpenDroneMap-class pipeline · GPU workers · S3/MinIO.

No implementation yet — boundary reservation only. Domain work begins in the Drone
Operations epic.
