# SATRAK — Technical Design Document (TDD)

**Status:** Draft v1.0
**Last updated:** 2026-07-05
**Companion documents:** [PRD.md](PRD.md), [ENGINEERING_BLUEPRINT.md](ENGINEERING_BLUEPRINT.md)

---

## 1. Purpose

This document defines the technical architecture, module boundaries, data flow, AI pipeline, technology stack, and design rationale for SATRAK. It is the engineering source of truth referenced during implementation. Product scope and requirements live in [PRD.md](PRD.md); this document assumes familiarity with it.

---

## 2. System Architecture Overview

SATRAK is organized as a set of loosely coupled services around a central spatial data store, orchestrated as a pipeline (batch/scheduled) feeding a case-management application (online/interactive).

```
                    ┌──────────────────────────┐
                    │   Imagery Sources         │
                    │  (Sentinel-1/2, Cartosat, │
                    │   PlanetScope, Pléiades)  │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  1. Data Ingestion &      │
                    │     Orchestration         │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  2. Preprocessing         │
                    │  (ortho, cloud mask,      │
                    │   co-registration,        │
                    │   radiometric norm.)      │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  3. Building Footprint    │
                    │     Extraction            │
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                                       │
   ┌──────────▼───────────┐               ┌──────────▼───────────┐
   │ 4. Height/Floor       │               │ 5. Multi-temporal     │
   │    Estimation         │               │    Change Detection   │
   └──────────┬───────────┘               └──────────┬───────────┘
              └──────────────────┬──────────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  6. GIS Overlay &         │
                    │     Rule Engine           │
                    │  (parcel/zoning/protected │
                    │   land/sanctioned plan)   │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  7. Risk Scoring &        │
                    │     Prioritization        │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  8. Human Verification    │
                    │     Workflow              │
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
   ┌──────────▼───────────┐               ┌──────────▼───────────┐
   │ 9. Case Management &  │               │ 10. Notifications &   │
   │    Reporting          │               │     Transparency      │
   │                        │               │     Portal            │
   └──────────┬───────────┘               └───────────────────────┘
              │
   ┌──────────▼───────────┐
   │ 11. MLOps / Feedback  │
   │     Loop              │
   └───────────────────────┘

Cross-cutting: 12. Security, Access Control & Audit (applies to all modules)
```

---

## 3. Module Specifications

### 3.1 Data Ingestion & Orchestration
- **Inputs:** scheduled satellite archive pulls (Sentinel-1/2), on-demand high-resolution tasking requests (Cartosat/PlanetScope/Pléiades).
- **Outputs:** raw imagery + STAC-compliant metadata records (sensor, date, extent, cloud cover %).
- **Design notes:** implemented as an orchestrated DAG (Airflow/Prefect), not ad hoc scripts, since ingestion → preprocessing → inference is a recurring, dependency-ordered pipeline. A tiered strategy is used deliberately: continuous coarse-resolution (free) coverage city-wide, with high-resolution tasking reserved for hotspots flagged by earlier stages — continuous sub-meter city-wide imagery is not cost-viable.

### 3.2 Preprocessing
- **Inputs:** raw imagery.
- **Outputs:** orthorectified, cloud/shadow-masked, co-registered, radiometrically normalized image tiles, stored as Cloud-Optimized GeoTIFFs (COG).
- **Design notes:** co-registration uses feature-based matching (SIFT/ORB + RANSAC) against a common reference DEM rather than assuming source imagery is pre-aligned — misalignment is the largest real-world source of false "change" signals. Radiometric normalization (histogram matching against pseudo-invariant features) is required to make imagery from different sensors/seasons comparable.

### 3.3 Building Footprint Extraction
- **Inputs:** preprocessed imagery tile (single epoch).
- **Outputs:** per-epoch building footprint polygons with per-polygon confidence.
- **Approach:** semantic + instance segmentation using a fine-tuned remote-sensing foundation model backbone (e.g., Prithvi/SatMAE/Clay) rather than training from scratch — labeled Indian construction data is scarce, and foundation-model fine-tuning needs far less labeled data to reach usable accuracy.

### 3.4 Height/Floor Estimation
- **Inputs:** footprint polygons + stereo image pairs (where available) or single-image + sun-angle metadata.
- **Outputs:** estimated height delta per building, converted to an approximate floor-count delta using an assumed per-floor height (~3–3.5m), with an explicit uncertainty range.
- **Design notes:** this is deliberately framed as an estimate, not a fact. Nadir satellite imagery shows rooftops, not building elevations — exact floor count requires field verification or oblique/street-level imagery. The system must never present this figure without its confidence band.

### 3.5 Multi-temporal Change Detection
- **Inputs:** footprint polygons across a *time series* of epochs (not a single before/after pair — sparse two-date comparison is noisy and undermines timeline reconstruction).
- **Outputs:** change polygons tagged with type (`new-construction`, `vertical-extension`, `horizontal-extension`, `demolished`, `no-change`) and confidence.
- **Approach:** Siamese/transformer-style change-detection architecture (e.g., FC-Siam-diff-style or BIT-style) using the same foundation-model backbone as footprint extraction, more robust to residual misalignment than raw pixel differencing.

### 3.6 GIS Overlay & Rule Engine
- **Inputs:** change polygons + parcel boundary layer + zoning layer + protected/water/government-land layer + sanctioned-plan layer (where digitized).
- **Outputs:** structured violation classification per case (boundary violation, vertical/floor violation, unauthorized new construction, encroachment on public/protected land, or land-use flag requiring field confirmation).
- **Design notes:** this is a deterministic, explainable rule layer (spatial intersection + threshold rules), not a black-box model — every classification must be traceable to the specific layer/rule that triggered it (legal defensibility requirement, see PRD NFR-1/NFR-7). Must tolerate imprecise/outdated cadastral geometry via buffer tolerances rather than exact-match intersection.

### 3.7 Risk Scoring & Prioritization
- **Inputs:** violation classification, model confidence, affected area, sensitivity multipliers (e.g., protected/heritage/water-body zone, high public visibility).
- **Outputs:** a ranked case queue.
- **Design notes:** this is what actually saves inspector time in practice — prioritization matters as much as detection accuracy.

### 3.8 Human Verification Workflow
- **Inputs:** ranked case with all supporting evidence (before/after imagery, overlays, confidence, classification).
- **Outputs:** officer verdict (confirmed / rejected / escalated) with mandatory reason, recorded immutably.
- **Design notes:** no case may progress to "confirmed violation" without this step (PRD NFR-2). This is a structural requirement, not a UI nicety, given the legal weight of downstream enforcement action.

### 3.9 Case Management & Reporting
- **Inputs:** confirmed/escalated cases.
- **Outputs:** auto-generated, inspection-ready evidence report (PDF/print) — imagery, coordinates, overlay maps, rule reference, confidence — plus case status tracking (flagged → under review → field-verified → notice issued → resolved).

### 3.10 Notifications & Transparency Portal
- **Outputs:** internal alerts to ward officers for new high-confidence cases; public-facing, privacy-redacted ward/city aggregate statistics and citizen complaint intake.
- **Design notes:** the public portal must never expose raw high-resolution imagery of an individual private property (PRD NFR-5).

### 3.11 MLOps / Feedback Loop
- **Inputs:** officer verdicts (labeled ground truth over time).
- **Outputs:** retrained/recalibrated models, drift monitoring reports.

### 3.12 Security, Access Control & Audit (cross-cutting)
- Role-based access control across all modules; immutable audit log of all case-state transitions; restricted access to high-resolution private-property imagery.

---

## 4. Technology Stack & Rationale

| Layer | Choice | Rationale |
|---|---|---|
| ML framework | PyTorch + `torchgeo` | `torchgeo` is purpose-built for geospatial ML; most current remote-sensing foundation models (Prithvi, SatMAE, Clay) target PyTorch |
| Segmentation/detection | `segmentation-models-pytorch`, MMSegmentation, fine-tuned RS foundation models | Best accuracy achievable with the limited labeled Indian imagery realistically available |
| Geospatial processing | GDAL/OGR, Rasterio, GeoPandas, Shapely, Fiona | Industry-standard, mature, interoperable with QGIS/PostGIS |
| Large-scale imagery access | Google Earth Engine | Free, large historical Sentinel/Landsat archive with server-side processing — avoids storing full raw history ourselves |
| GIS authoring/QA | QGIS | Analyst-facing tool for verifying/curating layers |
| Backend services | Python + FastAPI | Async-friendly, strong typing, natural fit for ML-serving endpoints |
| Pipeline orchestration | Airflow or Prefect | Ingestion → preprocessing → inference is a scheduled, dependency-ordered DAG, not ad hoc scripts |
| Async jobs/queue | Celery/RQ + Redis | Standard, well-understood task-queue pattern |
| Spatial database | PostgreSQL + PostGIS | Industry standard for spatial system-of-record; supports complex intersection queries the rule engine depends on |
| Imagery storage | S3-compatible object storage, Cloud-Optimized GeoTIFF (COG) | Enables partial/range reads of large rasters without full download |
| Imagery cataloging | STAC (SpatioTemporal Asset Catalog) | Standard way to index imagery by time/location/sensor |
| Frontend | React + MapLibre GL JS | MapLibre (open-source Mapbox fork) avoids vendor lock-in on a government-facing platform |
| Large-scale map rendering | deck.gl (as needed) | Performant rendering of large polygon volumes |
| 3D visualization | Cesium (as needed) | Compelling visualization of height/floor violations |
| Mobile (field officer app) | React Native or Flutter, offline-first sync | Officers frequently work in low-connectivity areas |
| Deployment | Docker/Kubernetes, portable to NIC/MeghRaj or state data centers | Government data-sovereignty requirements (PRD NFR-3); avoids cloud vendor lock-in |
| Integration | REST/GraphQL APIs, DIGIT/NUDM-compatible where possible | Maximizes real-world municipal adoption by aligning with the common GoI e-governance stack |

---

## 5. Data Sources

- **Imagery:** Sentinel-2 (10m, free, frequent revisit), Sentinel-1 SAR (all-weather, critical for monsoon cloud cover), Landsat 8/9 (30m), ISRO/NRSC Cartosat-2/3 (via Bhuvan, request-based), PlanetScope (~3m, commercial), Pléiades (sub-meter, commercial) for confirmed hotspots.
- **Training/benchmark datasets:** Microsoft Global ML Building Footprints, Google Open Buildings, OpenStreetMap building layer, LEVIR-CD, S2Looking, OSCD, SECOND, WHU Building Change Dataset, SpaceNet (1/2/4), Massachusetts Buildings Dataset, INRIA Aerial Image Labeling.
- **Indian GIS/land records:** SVAMITVA drone-surveyed property records, Bhuvan Panchayat/Urban portals, DILRMP cadastral data, state ULB GIS portals, Survey of India toposheets, Development Authority Master Plans (typically requires digitization).

**Known constraint:** sanctioned building-plan data is rarely available in digitized/georeferenced form today in most Indian cities. This is a genuine data-availability gap, not an AI limitation, and the rule engine (§3.6) is designed to degrade gracefully (boundary/encroachment detection still functions) when sanctioned-plan data is unavailable.

---

## 6. Cross-Cutting Design Principles

1. **Human-in-the-loop is structural, not optional.** No automated flag becomes a "confirmed violation" without explicit officer sign-off (PRD NFR-2).
2. **Every automated output must be explainable.** Classifications trace to specific rule/layer intersections; confidence scores are always shown alongside estimates (§3.4, §3.6).
3. **Tiered imagery strategy, not uniform high-resolution coverage.** Coarse city-wide screening → targeted high-resolution tasking on flagged hotspots (§3.1).
4. **Time-series over two-date comparison.** Enables timeline reconstruction and reduces false positives from seasonal/illumination noise (§3.5).
5. **Optical + SAR fusion**, not optical-only, to remain functional through monsoon cloud cover.
6. **Data sovereignty by design.** Containerized, portable to India-hosted government infrastructure (PRD NFR-3).

---

## 7. Open Design Questions (to resolve during implementation)

- Exact composite risk-scoring formula and weight tuning (confidence × severity × sensitivity) — needs pilot-data calibration.
- Buffer-tolerance thresholds for parcel/zoning intersection given cadastral positional inaccuracy — needs ground-truth calibration per pilot city.
- Choice of specific foundation-model checkpoint (Prithvi vs. SatMAE vs. Clay) — needs a bake-off on available labeled data.
- Final selection of pilot city/ward and its available GIS data quality, which determines how much of §3.6's sanctioned-plan matching is usable at launch vs. deferred.
