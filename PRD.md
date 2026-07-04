# SATRAK — Product Requirements Document (PRD)

**Status:** Draft v1.0
**Owner:** Saad Riyaz Mohammed
**Last updated:** 2026-07-05

---

## 1. Product Name

**SATRAK** — Satellite-based Tracking & Compliance platform for unauthorized construction monitoring.

---

## 2. Vision

Municipal corporations currently detect unauthorized construction through manual inspections and citizen complaints — a process that is expensive, slow, inconsistent, and impossible to scale across an entire city. SATRAK exists to change that.

SATRAK is an AI-powered urban compliance intelligence platform that continuously monitors a city using satellite imagery, automatically detects new or modified construction, cross-references it against government land records and sanctioned building plans, and surfaces a ranked, evidence-backed list of likely violations to municipal officers — turning enforcement from reactive and manual into proactive and data-driven.

SATRAK does not replace human judgment or legal authority. It is a **decision-support system**: it finds and prioritizes leads; officers verify and act. This distinction is a deliberate product principle, not a limitation — it is what makes the system legally deployable and defensible in a government context.

---

## 3. Problem Statement

- Property owners are sanctioned to build a limited structure (e.g., Ground + 2 floors) but construct additional floors without approval.
- Some structures are built with no sanction at all.
- Some structures extend beyond the approved plot boundary.
- Some structures encroach on lakes, roads, government land, or reserved/protected zones.
- Municipal bodies rely on manual, complaint-driven inspection, which cannot achieve consistent, city-wide, recurring coverage.

## 4. Goals

1. Automatically detect newly constructed or modified structures across a city using historical vs. recent satellite imagery.
2. Cross-verify detected changes against parcel boundaries, zoning layers, protected-land layers, and (where digitized) sanctioned building plans.
3. Classify each detected change into a violation category (unauthorized new construction, vertical extension, horizontal/boundary extension, encroachment on public/protected land, or land-use flag requiring field confirmation).
4. Rank detected cases by a composite risk score so limited inspection manpower is spent on the highest-priority cases first.
5. Produce an inspection-ready, evidence-backed report per case suitable as the basis for an official notice.
6. Provide a transparent, auditable trail from detection to human verdict, with officer feedback improving the system over time.

## 5. Non-Goals (explicitly out of scope for v1)

- SATRAK does **not** issue legal notices, demolition orders, or any punitive action automatically. All enforcement remains a human/administrative decision.
- SATRAK does **not** claim to determine exact floor count with certainty from satellite imagery alone — it produces a height-based *estimate* with a confidence band; exact confirmation is a field-verification step.
- SATRAK does **not** determine land-use/occupancy violations (e.g., residential plan being used commercially) from imagery — these are flagged for field/administrative follow-up only, never auto-classified as confirmed.
- SATRAK v1 does not attempt full national coverage — it targets a defined pilot city/ward.

## 6. Users & Personas

| Persona | Role | Needs from SATRAK |
|---|---|---|
| **Municipal Enforcement Officer** | Conducts site inspections | Ranked case queue, before/after imagery, GIS overlay, printable evidence report |
| **Town Planning / Building Permission Officer** | Reviews sanctioned plans | Ability to cross-check as-built vs. sanctioned footprint/floors |
| **Municipal Commissioner / Zonal Head** | Oversight and accountability | Ward-level compliance dashboards, trend/heatmap views |
| **GIS/Survey Department Staff** | Maintains land record layers | Tools to upload/update parcel, zoning, and protected-land layers |
| **Citizen (transparency portal, read-only)** | Public accountability | Redacted ward-level violation/resolution status, complaint submission |
| **System Administrator** | Platform operations | User/role management, audit logs, model retraining oversight |

## 7. Functional Requirements

### 7.1 Data Ingestion
- FR-1: Ingest satellite imagery from multiple sources (free coarse-resolution and tasked high-resolution) on a scheduled cadence.
- FR-2: Support on-demand tasking requests for high-resolution imagery over flagged hotspot areas.
- FR-3: Catalog all imagery with acquisition date, sensor, resolution, and spatial extent (STAC-compliant metadata).

### 7.2 Detection Pipeline
- FR-4: Extract building footprints per imagery epoch.
- FR-5: Detect change between epochs across a time series (not limited to a single before/after pair) and classify change type.
- FR-6: Estimate height/floor-count delta for vertical-extension candidates, with an explicit confidence range.
- FR-7: Intersect detected changes with parcel boundary, zoning, protected/water/government-land, and sanctioned-plan layers (where available) to classify violation type.
- FR-8: Compute a composite risk/priority score per case.

### 7.3 Verification Workflow
- FR-9: Present each flagged case to a human officer with before/after imagery, overlays, and supporting data before any status is marked "confirmed violation."
- FR-10: Allow officers to confirm, reject (false positive), or escalate a case, with mandatory reason capture.
- FR-11: Route confirmed cases into a case-management workflow with status tracking (flagged → under review → field-verified → notice issued → resolved).

### 7.4 Reporting & Transparency
- FR-12: Auto-generate an inspection-ready report per case (location, coordinates, imagery evidence, violation classification, confidence score, applicable rule/bylaw reference).
- FR-13: Provide ward-level and city-level compliance dashboards.
- FR-14: Provide a public-facing, privacy-redacted transparency portal showing aggregate violation/resolution statistics and allowing citizen complaint submission.

### 7.5 Feedback & Improvement
- FR-15: Capture officer verdicts as labeled feedback for periodic model retraining.
- FR-16: Track model performance/drift over time and surface it to administrators.

### 7.6 Integration
- FR-17: Expose APIs for integration with existing municipal e-governance systems (e.g., DIGIT/NUDM-aligned platforms) for building-permission and property-tax data exchange.

## 8. Non-Functional Requirements

- **NFR-1 Legal defensibility:** every automated flag must retain a full evidentiary trail (source imagery, model version, confidence, timestamps) sufficient to support administrative/legal review.
- **NFR-2 Human-in-the-loop by design:** no case may transition to "confirmed violation" without an explicit officer action.
- **NFR-3 Data sovereignty:** the platform must be deployable within India-hosted infrastructure (e.g., NIC/MeghRaj or state data centers) to satisfy government data-residency requirements.
- **NFR-4 Auditability:** all state transitions on a case must be logged immutably (who, what, when).
- **NFR-5 Privacy:** access to high-resolution imagery of private property must be role-restricted and logged; the public transparency portal must never expose raw high-resolution imagery of individual properties.
- **NFR-6 Scalability:** the pipeline must be able to scale from a single pilot ward to a full city without architectural rework.
- **NFR-7 Explainability:** every classification must be traceable to the specific rule/layer intersection or model confidence that produced it.
- **NFR-8 Availability:** core dashboard and case-management services should target standard government-application uptime (99.5%+), acknowledging batch imagery-processing jobs are not real-time.

## 9. Success Metrics

- Reduction in average time from unauthorized-construction onset to first official flag.
- Officer-confirmed true-positive rate on flagged cases (precision), tracked over successive model iterations.
- Percentage of city area under active recurring monitoring (coverage).
- Reduction in manual inspection hours per confirmed violation.
- Number of confirmed violations resolved (notice issued/regularized/demolished) per quarter.

## 10. Key Assumptions & Constraints

- Sanctioned building-plan data is, in most Indian cities, **not** available in digitized/georeferenced form today. SATRAK must function usefully (boundary and encroachment detection) even without it, and treat sanctioned-plan matching as an enhanced capability activated where data exists.
- Cadastral/parcel boundary data may be outdated or imprecisely georeferenced; the rule engine must tolerate reasonable positional error rather than assuming pixel-perfect alignment.
- Continuous city-wide sub-meter imagery is cost-prohibitive; the product relies on a tiered strategy (coarse city-wide screening → targeted high-resolution tasking).
- Monsoon cloud cover materially limits optical imagery availability for parts of the year; the product must not depend solely on optical sensors.

## 11. Risks (product-level)

- Data-availability gap (sanctioned plans, accurate cadastral layers) may limit v1 capability in some cities — mitigated by scoping v1 around a pilot city/ward with reasonable data access.
- False positives eroding officer trust — mitigated by conservative confidence thresholds and mandatory human confirmation before any downstream action.
- Perception of surveillance/privacy overreach — mitigated by strict access control and a redacted public portal.

## 12. Related Documents

- [TDD.md](TDD.md) — Technical Design Document
- [ENGINEERING_BLUEPRINT.md](ENGINEERING_BLUEPRINT.md) — Engineering standards, workflow, and roadmap
