# SATRAK

**AI-Powered Government Urban Compliance Intelligence Platform**

SATRAK monitors cities using satellite imagery and GIS data to automatically detect unauthorized construction — additional unsanctioned floors, boundary/setback violations, and encroachment on public or protected land — and turns it into a ranked, evidence-backed queue for municipal enforcement officers.

## Vision

Municipal corporations today rely on manual inspections and citizen complaints to catch unauthorized construction: expensive, slow, inconsistent, and impossible to run consistently across an entire city. SATRAK replaces reactive, manual enforcement with proactive, data-driven monitoring — comparing historical and recent satellite imagery, verifying findings against government land records, and generating inspection-ready reports.

SATRAK is built as a **decision-support system**, not an automated enforcement system: it detects and prioritizes leads; a human officer always verifies before any action is taken. See [PRD.md](PRD.md) for the full product rationale behind this and other design principles.

## Architecture Overview

```
Satellite Imagery → Ingestion → Preprocessing → Building Footprint Extraction
        → Height/Floor Estimation + Multi-temporal Change Detection
        → GIS Overlay & Rule Engine (parcel / zoning / protected-land / sanctioned-plan)
        → Risk Scoring & Prioritization → Human Verification Workflow
        → Case Management & Reporting → Notifications & Transparency Portal
                    ↑___________ MLOps / Feedback Loop ___________↓
```

Full module-by-module design is documented in [TDD.md](TDD.md).

## Technology Stack

| Layer | Technology |
|---|---|
| ML / Detection | PyTorch, torchgeo, fine-tuned remote-sensing foundation models (Prithvi/SatMAE/Clay) |
| Geospatial processing | GDAL, Rasterio, GeoPandas, Shapely, Google Earth Engine, QGIS |
| Backend | Python, FastAPI, Airflow/Prefect, Celery/Redis |
| Spatial database | PostgreSQL + PostGIS |
| Imagery storage | S3-compatible object storage (Cloud-Optimized GeoTIFF), STAC catalog |
| Frontend | React, MapLibre GL JS, deck.gl, Cesium |
| Mobile | React Native / Flutter (field-officer app) |
| Deployment | Docker, Kubernetes — portable to India-hosted infrastructure (NIC/MeghRaj) |

Full rationale for each choice is in [TDD.md](TDD.md#4-technology-stack--rationale).

## Repository Structure

```
satrak/
├── apps/            # Frontend (web) and mobile applications
├── services/         # Ingestion, preprocessing, detection, rules-engine, risk-scoring, case-management, notifications
├── ml/               # Model definitions, training, evaluation
├── infra/            # Docker, Kubernetes, deployment configuration
├── docs/             # Architecture decision records, runbooks, API specs
└── scripts/
```

See [ENGINEERING_BLUEPRINT.md](ENGINEERING_BLUEPRINT.md) for the full repository layout, branching strategy, and development workflow.

## Getting Started

> Implementation has not yet started. This section will be filled in as services are scaffolded (see [ENGINEERING_BLUEPRINT.md](ENGINEERING_BLUEPRINT.md) for the milestone roadmap).

```bash
# placeholder — setup instructions will be added starting with milestone M0/M1
```

## Documentation

- [PRD.md](PRD.md) — Product Requirements Document (problem, vision, users, requirements, success metrics)
- [TDD.md](TDD.md) — Technical Design Document (architecture, module specs, tech stack, data sources)
- [ENGINEERING_BLUEPRINT.md](ENGINEERING_BLUEPRINT.md) — Engineering standards, workflow, branching, roadmap

## License

Licensed under the [MIT License](LICENSE).
