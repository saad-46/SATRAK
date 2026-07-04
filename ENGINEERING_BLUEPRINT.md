# SATRAK — Implementation Blueprint
### Engineering Handbook for Building the Platform (Post-TDD, Pre-Code)

**Status:** Source-of-truth references — PRD (product), TDD (architecture, `SATRAK_Technical_Design_Document.md`). This document does not modify either; it translates the approved architecture into a buildable engineering plan.
**Audience:** Every engineer joining the project — backend, frontend, AI/ML, GIS, DevOps.
**Rule for this document:** No application code. No placeholders standing in for real decisions. Every structural choice below is one a team could start implementing from tomorrow.

---

## Table of Contents
1. Repository Architecture
2. Backend Modules
3. Frontend Architecture
4. AI Architecture
5. GIS Architecture
6. Project Bootstrap
7. Epics
8. Features → Tasks → Subtasks
9. Development Roadmap (Sprints)
10. Architecture Review — Weaknesses, Risks, Recommendations

---

# Part 1 — Repository Architecture

SATRAK is built as a **monorepo** managed with a workspace tool (pnpm workspaces for JS/TS packages, uv/poetry workspace for Python services), orchestrated by Turborepo (frontend build graph) and a root `Makefile` (cross-language tasks). A monorepo is chosen over polyrepo because: (a) the GIS/AI/backend/frontend boundary is still being tuned in year one and cross-cutting changes (e.g., a new case status) touch every layer, (b) shared types (OpenAPI-generated TS clients, shared Zod schemas) need a single source of truth, and (c) CI can gate on affected-package builds rather than each repo maintaining its own drifting copy of shared config.

```
satrak/
├── apps/
│   ├── web/                     # Officer + Commissioner + Admin web app (Next.js 15)
│   ├── citizen-portal/          # Public-facing citizen app (Next.js 15, separate deploy target)
│   └── mobile-drone-pilot/      # Drone pilot mission app (React Native/Expo) — future
│
├── services/                    # Independently deployable backend services (one FastAPI app each)
│   ├── auth-service/
│   ├── property-service/
│   ├── case-service/
│   ├── gis-service/
│   ├── satellite-ingestion-service/
│   ├── satellite-preprocessing-service/
│   ├── drone-service/
│   ├── ai-orchestration-service/
│   ├── notification-service/
│   ├── reporting-service/
│   └── audit-service/
│
├── ai/                           # Model code, training pipelines, and served inference — separate from services/ because model artifacts, training data, and notebook-driven work have a different lifecycle (versioned in a model registry, not deployed via the same CI as API services)
│   ├── models/
│   │   ├── building-detection/
│   │   ├── change-detection/
│   │   ├── road-detection/
│   │   ├── risk-scoring/
│   │   └── llm-assistant/       # prompt templates + retrieval config, not a trained model
│   ├── training/                # training scripts, experiment configs (Hydra/OmegaConf), data loaders
│   ├── evaluation/               # benchmark harnesses, regional test-set runners
│   └── serving/                 # KServe/Ray Serve wrapper code shared across model services
│
├── packages/                    # Shared code, importable by apps/ and services/ (language-appropriate)
│   ├── ts-api-client/            # Auto-generated TS client from OpenAPI specs (one per service)
│   ├── ts-ui/                    # Shared shadcn/ui-based component library + design tokens (consumes the Figma variables as a single JSON source of truth)
│   ├── ts-map-kit/                # MapLibre/CesiumJS wrapper components (layer switcher, drawing tools, time slider) shared between web and citizen-portal
│   ├── ts-schemas/                # Zod schemas shared between frontend forms and (via codegen) backend Pydantic models
│   ├── py-common/                 # Shared Python: auth middleware, structured logging, tracing, base repository classes
│   ├── py-geo/                    # Shared GeoPandas/Shapely/GDAL helpers (CRS transforms, buffer/intersection utilities) used by gis-service and ai pipelines
│   └── py-events/                 # Shared event schema definitions (Pydantic models mirrored to Avro/JSON Schema for Kafka)
│
├── database/
│   ├── migrations/                # Alembic migration chains, one directory per service's schema (schema-per-service, shared PostGIS instance initially)
│   ├── seeds/                     # Deterministic seed data for local/dev/staging (fake parcels, fake officers, fake case history)
│   └── erd/                       # Generated entity-relationship diagrams, checked in as versioned artifacts
│
├── infra/
│   ├── docker/                    # Dockerfiles per service, organized as docker/<service-name>/Dockerfile
│   ├── docker-compose/            # docker-compose.yml + override files for local dev, integration testing
│   ├── terraform/                 # IaC for cloud resources — modules/ (reusable) + environments/{dev,staging,prod}
│   ├── k8s/                       # Kustomize/Helm charts per service, environment overlays
│   └── nginx/                     # Reverse proxy / gateway config for local + non-managed deployments
│
├── docs/
│   ├── architecture/              # This blueprint, the TDD, ADRs (one markdown file per ADR, numbered)
│   ├── runbooks/                  # Operational runbooks: on-call, incident response, DR drill procedure
│   ├── api/                       # Rendered OpenAPI docs per service (generated, not hand-written)
│   └── onboarding/                 # New-engineer setup guide, local dev environment steps
│
├── scripts/                       # One-off and recurring operational scripts (data backfills, model rollout scripts, jurisdiction onboarding scripts)
│
├── tools/                         # Internal developer tooling: codegen scripts (OpenAPI → TS client), lint config packages, custom CLI for scaffolding a new service/module
│
├── .github/
│   └── workflows/                 # CI/CD pipelines, one workflow per deployable unit plus shared reusable workflows
│
├── turbo.json                     # Turborepo pipeline definition (frontend build graph, caching)
├── pnpm-workspace.yaml
├── Makefile                       # Cross-language entrypoints: make dev, make test, make migrate
└── README.md
```

### Why this shape, specifically

- **`services/` is per-bounded-context, not per-technical-layer.** Each service owns its own database schema, migrations, and API — mirroring the microservice boundaries in TDD Section 3. A developer working on drone missions never needs to check out or understand the AI orchestration service's internals.
- **`ai/` is separated from `services/`** even though `ai-orchestration-service` lives in `services/`. The orchestration service is a thin API/queue-consumer; the actual model code, training loops, and evaluation harnesses in `ai/` have a fundamentally different release cadence (model versions ship independently of API deploys) and are owned by the ML team, not the backend team.
- **`packages/ts-ui` consumes design tokens as data, not as hardcoded values.** The Figma variable collections (`SATRAK/Color · Light`, `SATRAK/Color · Dark`, `SATRAK/Dimension`) are the source of truth; a sync script (in `tools/`) exports them to a JSON/TS token file that `ts-ui` builds Tailwind config from. This keeps design and code from drifting.
- **`database/migrations` is organized schema-per-service** even though all services currently point at one PostGIS instance. This is deliberate: it means a future split (e.g., moving `audit-service`'s schema to its own WORM-compliant database) is a connection-string change, not a migration-history untangling exercise.
- **No `apps/mobile-drone-pilot` build gates the rest of CI.** It's included in the monorepo for shared type/API-client reuse, but its pipeline is independent — a broken mobile build should never block a backend deploy.

---

# Part 2 — Backend Modules

Each module below corresponds to a bounded context. Where a module maps directly to a TDD microservice, the service name is noted. Modules follow the same internal layering throughout: **API layer** (FastAPI routers, request/response Pydantic schemas) → **Service layer** (business logic, orchestration, transaction boundaries) → **Repository layer** (SQLAlchemy queries, no business logic) → **Database**. This layering is enforced by lint rule (import-linter or similar) so a router can never import SQLAlchemy models directly.

## 2.1 Authentication (`auth-service`)
- **Responsibilities:** SSO/OIDC login, JWT issuance/refresh, MFA enrollment/verification, session revocation, jurisdiction-scoped RBAC policy evaluation.
- **Dependencies:** Government identity provider (OIDC), `py-common` (shared JWT middleware).
- **Database Tables:** `users`, `roles`, `permissions`, `role_permissions`, `user_roles`, `jurisdictions`, `sessions`, `mfa_devices`, `login_audit`.
- **Services:** `AuthService` (login/refresh flow), `RbacService` (permission checks), `MfaService`.
- **API Layer:** `POST /auth/login`, `POST /auth/refresh`, `POST /auth/mfa/verify`, `GET /auth/me`, `POST /auth/logout`.
- **Repository Layer:** `UserRepository`, `SessionRepository`, `RoleRepository`.
- **Background Jobs:** Expired-session cleanup (Celery beat, hourly); stale MFA-device pruning.
- **Events Published:** `user.logged_in`, `user.login_failed`, `session.revoked` (consumed by `audit-service`).

## 2.2 Users (`auth-service`, shared schema)
- **Responsibilities:** User profile CRUD, invitation flow, jurisdiction/role assignment, deactivation.
- **Dependencies:** Authentication module, Notification module (invite emails).
- **Database Tables:** `users` (shared with 2.1), `user_invitations`, `user_profile_metadata`.
- **Services:** `UserService`, `InvitationService`.
- **API Layer:** `GET/POST/PATCH /users`, `POST /users/{id}/invite`, `POST /users/{id}/deactivate`.
- **Repository Layer:** `UserRepository`, `InvitationRepository`.
- **Background Jobs:** Invitation-expiry sweep.
- **Events Published:** `user.created`, `user.deactivated`, `user.role_changed`.

## 2.3 Organizations (`auth-service`, shared schema)
- **Responsibilities:** Manage the hierarchy of government entities (State → Department → Municipal Corporation → Ward) that jurisdictions and users attach to; org-level configuration (feature flags, SLA policy per org).
- **Dependencies:** Authentication module.
- **Database Tables:** `organizations`, `organization_hierarchy` (adjacency list or ltree), `organization_settings`.
- **Services:** `OrganizationService`, `OrgSettingsService`.
- **API Layer:** `GET/POST/PATCH /organizations`, `GET /organizations/{id}/hierarchy`.
- **Repository Layer:** `OrganizationRepository`.
- **Background Jobs:** None recurring; org-hierarchy cache invalidation on write.
- **Events Published:** `organization.created`, `organization.updated`.

## 2.4 Properties (`property-service`)
- **Responsibilities:** Canonical property/building registry — the entity a case ultimately attaches to (distinct from a raw cadastral parcel, since one parcel can carry multiple buildings over time).
- **Dependencies:** Parcels module (a property belongs to a parcel), GIS Query Service (for geometry validation).
- **Database Tables:** `properties`, `property_ownership_history`, `property_documents`.
- **Services:** `PropertyService`, `OwnershipHistoryService`.
- **API Layer:** `GET/POST/PATCH /properties`, `GET /properties/{id}/history`, `GET /properties/search`.
- **Repository Layer:** `PropertyRepository`.
- **Background Jobs:** Nightly reconciliation against Revenue Department ownership feed (where available).
- **Events Published:** `property.created`, `property.ownership_changed`.

## 2.5 Parcels (`property-service`, shared with GIS)
- **Responsibilities:** Cadastral parcel geometry and survey-number registry; the authoritative spatial boundary layer.
- **Dependencies:** GIS Query Service for spatial operations; ingested from government cadastral data imports.
- **Database Tables:** `parcels` (PostGIS geometry column), `parcel_survey_numbers`, `parcel_boundary_versions` (tracks subdivisions/merges over time).
- **Services:** `ParcelService`, `ParcelImportService`.
- **API Layer:** `GET /parcels/{id}`, `GET /parcels/search`, `POST /parcels/import` (admin-only, batch cadastral import).
- **Repository Layer:** `ParcelRepository` (PostGIS-aware queries via GeoAlchemy2).
- **Background Jobs:** Batch cadastral import job (Celery, triggered by admin upload); boundary-version diffing.
- **Events Published:** `parcel.imported`, `parcel.boundary_updated`.

## 2.6 Permits (`property-service`)
- **Responsibilities:** Building-permit and approval record management, cross-referenced during automated verification (TDD Section 4, step 6).
- **Dependencies:** Properties/Parcels modules; external Urban Development Authority permit feed where integrated.
- **Database Tables:** `permits`, `permit_documents`, `permit_conditions`.
- **Services:** `PermitService`, `PermitMatchService` (matches a detected structure against a permit by parcel + footprint overlap).
- **API Layer:** `GET/POST /permits`, `GET /permits/match?parcelId=...`.
- **Repository Layer:** `PermitRepository`.
- **Background Jobs:** Nightly sync from external permit systems (per-jurisdiction adapter).
- **Events Published:** `permit.issued`, `permit.revoked`.

## 2.7 Satellite (`satellite-ingestion-service` + `satellite-preprocessing-service`)
- **Responsibilities:** Scene acquisition scheduling, download, cloud/shadow masking, orthorectification, tiling into analysis-ready COGs.
- **Dependencies:** Satellite provider APIs/contracts; Object Storage; AOI definitions from Organizations/Jurisdictions.
- **Database Tables:** `satellite_scenes`, `aoi_definitions`, `acquisition_schedule`, `tile_index` (maps tiles to scene + AOI + zoom level).
- **Services:** `AcquisitionSchedulerService`, `PreprocessingService`, `TilingService`.
- **API Layer:** `GET /satellite/scenes`, `GET /satellite/tiles/{z}/{x}/{y}`, `POST /satellite/aoi` (admin).
- **Repository Layer:** `SceneRepository`, `TileIndexRepository`.
- **Background Jobs:** Scheduled acquisition polling (Celery beat), preprocessing pipeline (Celery task chain: download → mask → orthorectify → tile), backlog-priority reordering during cloud-heavy periods.
- **Events Published:** `scene.ingested`, `tiles.ready` (triggers AI Orchestration).

## 2.8 Drone (`drone-service`)
- **Responsibilities:** Mission planning, flight log ingestion, photogrammetry orchestration, 3D product generation.
- **Dependencies:** Case Service (missions are dispatched from a case), Object Storage, GPU photogrammetry worker pool.
- **Database Tables:** `drone_missions`, `drone_flight_logs`, `drone_imagery`, `photogrammetry_outputs` (orthomosaic/DSM/point-cloud references).
- **Services:** `MissionPlanningService`, `PhotogrammetryService`, `MissionReportService`.
- **API Layer:** `POST /drone/missions`, `GET /drone/missions/{id}`, `POST /drone/missions/{id}/upload`, `GET /drone/missions/{id}/report`.
- **Repository Layer:** `MissionRepository`, `ImageryRepository`.
- **Background Jobs:** Photogrammetry processing (GPU Celery queue), mission-report auto-generation on processing completion.
- **Events Published:** `mission.dispatched`, `mission.completed`, `photogrammetry.ready`.

## 2.9 GIS (`gis-service`)
- **Responsibilities:** All spatial query operations — intersection, buffer, spatial joins, coordinate transforms — as a shared internal API rather than every service embedding its own PostGIS logic.
- **Dependencies:** PostGIS cluster; consumed by nearly every other service.
- **Database Tables:** Owns `jurisdiction_boundaries`, `road_network`, `waterbody_boundaries`, `forest_boundaries`, `zoning_layers`; reads (does not own) `parcels`.
- **Services:** `SpatialQueryService`, `EncroachmentService` (deterministic polygon-intersection logic per TDD ADR-03), `BoundaryDataQualityService`.
- **API Layer:** `POST /gis/query/intersects`, `POST /gis/query/buffer`, `POST /gis/encroachment-check`, OGC-compliant `WFS`/`WMS` endpoints for GIS-client interoperability.
- **Repository Layer:** `BoundaryRepository`, built on GeoAlchemy2 + raw PostGIS function calls for performance-critical paths.
- **Background Jobs:** Boundary-layer freshness scoring (nightly), spatial index maintenance (VACUUM/REINDEX scheduling).
- **Events Published:** `encroachment.flagged`, `boundary_data.stale` (data-quality alert per TDD Section 14).

## 2.10 AI (`ai-orchestration-service`)
- **Responsibilities:** Coordinates the full model pipeline per tile/parcel (building detection → change detection → risk scoring), version routing, confidence thresholding before case creation.
- **Dependencies:** Satellite/Drone modules (inputs), GIS module (parcel correlation), model-serving infrastructure in `ai/serving`.
- **Database Tables:** `inference_runs` (model version, input tile ID, output reference, confidence — the audit trail described in TDD Section 5), `model_versions`, `model_rollout_config`.
- **Services:** `InferenceOrchestratorService`, `ModelRegistryService`, `ConfidenceThresholdService`.
- **API Layer:** `GET /ai/detections/{tileId}`, `GET /ai/risk-score/{caseId}`, `POST /ai/models/{id}/rollout` (admin).
- **Repository Layer:** `InferenceRunRepository`, `ModelVersionRepository`.
- **Background Jobs:** Batch inference consumer (reads from `tiles.ready`/`photogrammetry.ready` queue), nightly model-drift monitoring job.
- **Events Published:** `detection.completed`, `case.candidate_created` (consumed by Case Service).

## 2.11 Inspection / Case (`case-service`)
- **Responsibilities:** Owns the case lifecycle end-to-end (Detected → Under Review → Drone Dispatched → Inspected → Notice Issued → Resolved/Escalated); the central orchestration point of the whole platform.
- **Dependencies:** AI module (candidate cases), Drone module (dispatch), GIS module (parcel context), Notification module, Audit module.
- **Database Tables:** `cases`, `case_status_history`, `case_assignments`, `case_evidence` (references to satellite/drone imagery + AI outputs), `officer_reviews`.
- **Services:** `CaseLifecycleService`, `AssignmentService`, `SlaTrackingService`.
- **API Layer:** `GET/POST/PATCH /cases`, `POST /cases/{id}/assign`, `POST /cases/{id}/dispatch-drone`, `POST /cases/{id}/review`.
- **Repository Layer:** `CaseRepository`, `CaseHistoryRepository`.
- **Background Jobs:** SLA-breach detection (Celery beat), stale-case escalation.
- **Events Published:** `case.created`, `case.status_changed`, `case.escalated` — the most heavily consumed event stream in the system (Notification, Reporting, Analytics, Audit all subscribe).

## 2.12 Reports (`reporting-service`)
- **Responsibilities:** Structured report generation (inspection reports, compliance reports, court evidence reports), LLM-assisted drafting with mandatory officer review.
- **Dependencies:** Case Service (source data), AI module (LLM Assistant, report-generation), Audit module (evidence bundling).
- **Database Tables:** `reports`, `report_templates`, `report_generation_log` (tracks LLM prompt/response for auditability).
- **Services:** `ReportGenerationService`, `TemplateService`, `ExportService` (PDF/Word rendering).
- **API Layer:** `GET /reports/{caseId}`, `POST /reports/{caseId}/generate`, `GET /reports/{caseId}/export`.
- **Repository Layer:** `ReportRepository`.
- **Background Jobs:** Scheduled aggregate report generation (ward/city/executive dashboards), PDF rendering queue.
- **Events Published:** `report.generated`, `report.exported`.

## 2.13 Notifications (`notification-service`)
- **Responsibilities:** Multi-channel dispatch (SMS/email/push/postal-integration) with delivery tracking.
- **Dependencies:** Case Service, User module, external SMS/email gateways.
- **Database Tables:** `notifications`, `notification_templates`, `delivery_receipts`.
- **Services:** `NotificationDispatchService`, `TemplateRenderService`, `DeliveryTrackingService`.
- **API Layer:** `POST /notifications/send` (internal), `GET /notifications/{id}/status`.
- **Repository Layer:** `NotificationRepository`.
- **Background Jobs:** Dispatch queue consumer, retry-on-failure with backoff, non-delivery escalation.
- **Events Published:** `notification.sent`, `notification.failed`, `notification.delivered`.

## 2.14 Analytics (`reporting-service`, separate read-path)
- **Responsibilities:** Aggregated, denormalized views over case/property/AI data for dashboards — deliberately decoupled from transactional services so heavy analytical queries never compete with case-processing load.
- **Dependencies:** Analytics Warehouse (ETL'd from all transactional services via CDC or scheduled export).
- **Database Tables:** Warehouse-side fact/dimension tables (`fact_cases`, `dim_jurisdiction`, `dim_officer`, `fact_ai_inference`) — not part of the transactional schema.
- **Services:** `AnalyticsQueryService`, `ETLOrchestrationService`.
- **API Layer:** `GET /analytics/ward/{id}`, `GET /analytics/officer-performance`, `GET /analytics/ai-performance`.
- **Repository Layer:** `WarehouseQueryRepository` (read-only, warehouse-specific).
- **Background Jobs:** Nightly ETL/CDC sync from transactional services into the warehouse.
- **Events Published:** None (pure consumer of events for warehouse population).

## 2.15 Administration (`auth-service` + cross-cutting)
- **Responsibilities:** System configuration surface for org/role/permission management, AI model rollout control, API key management, storage/retention policy configuration.
- **Dependencies:** Nearly every module (it is the control plane).
- **Database Tables:** `api_keys`, `system_settings`, `feature_flags`, `retention_policies`.
- **Services:** `AdminConfigService`, `ApiKeyService`, `FeatureFlagService`.
- **API Layer:** `GET/POST /admin/users`, `GET/POST /admin/jurisdictions`, `POST /admin/models/{id}/rollout`, `GET/POST /admin/api-keys`.
- **Repository Layer:** `AdminConfigRepository`.
- **Background Jobs:** API-key expiry sweep, feature-flag cache invalidation broadcast.
- **Events Published:** `config.changed` (broadcast to all services for cache invalidation).
---

# Part 3 — Frontend Architecture

Applies to `apps/web` (officer/commissioner/admin) primarily; `apps/citizen-portal` reuses `packages/ts-ui` and `ts-map-kit` but has its own simplified routing tree and a separate, lighter auth flow.

### Routing
Next.js 15 App Router, organized by **role-scoped route groups** rather than by feature, since access control is the primary navigation axis:
```
app/
├── (auth)/                 # login, MFA, forgot-password — no shell layout
├── (officer)/              # officer dashboard, case queue, inspection flow
│   ├── dashboard/
│   ├── cases/[caseId]/
│   ├── map/
│   └── inspections/
├── (commissioner)/         # ward/city rollups, executive dashboard
├── (admin)/                # org/user/role/model management
└── (citizen)/              # only present in apps/citizen-portal
```
Route groups map directly to RBAC roles; a middleware-level guard (see Authentication below) checks role membership before a route group's layout renders, so an officer can never even code-split-load the admin bundle.

### Layouts
Three-tier layout composition: **Root layout** (fonts, theme provider, global error boundary) → **Role shell layout** (per route group: top app bar, role-specific side nav, notification tray) → **Page layout** (per-page composition of panels, e.g., the GIS map screen's three-pane layout). Layouts are server components where possible; only the interactive shell chrome (nav state, notification polling) is a client component.

### Shared Components (`packages/ts-ui`)
Built on shadcn/ui as the primitive layer (unstyled, accessible Radix primitives), themed via the Tailwind config generated from Figma variables. Organized as: `primitives/` (Button, Input, Badge, Dialog — direct shadcn wrappers), `patterns/` (CaseCard, PropertyCard, EvidenceViewer, ImageComparisonSlider — SATRAK-specific compositions), `layout/` (AppShell, SidePanel, Toolbar). Every component in `patterns/` requires a Storybook story and an axe-core accessibility test before merge.

### State Management
Split by data ownership, not a single global store:
- **Server state** (cases, properties, AI results): TanStack Query exclusively. No server data is ever duplicated into Zustand.
- **Client/UI state** (selected map layer, side panel open/closed, draft form state before submission): Zustand, one small store per feature module, not a single monolithic app store.
- **Form state**: React Hook Form + Zod resolver, with the Zod schema shared from `packages/ts-schemas` so frontend validation and backend Pydantic validation stay derived from the same source where the schema can be shared (numeric ranges, required fields); backend remains the authority for anything security-sensitive.

### API Layer
`packages/ts-api-client` is generated (via `openapi-typescript` + a thin fetch wrapper) from each backend service's OpenAPI spec — never hand-written. TanStack Query hooks wrap the generated client per feature (`useCaseQuery`, `useDispatchDroneMutation`), centralizing cache-key conventions and optimistic-update logic. A single `apiClient` instance handles auth-token attachment and 401-triggered refresh, shared across all generated clients.

### Feature Modules
Each feature (`case-queue`, `gis-map`, `drone-missions`, `inspection-form`, `reports`, `analytics`) is a self-contained directory under `apps/web/src/features/<feature>/` with its own `components/`, `hooks/`, `api/` (TanStack Query hooks specific to the feature), and `store.ts` (Zustand, if needed). Route files in `app/` import from features, not the reverse — features never import Next.js routing primitives, keeping them portable and independently testable.

### Maps
`packages/ts-map-kit` wraps MapLibre GL (2D — parcel/case/layer views) and CesiumJS (3D — drone photogrammetry/digital-twin views) behind a shared interface (`MapProvider`, `useMapLayers`, `useMapSelection`) so feature code doesn't need to know which underlying engine renders a given view. Layer definitions (parcel, road, waterbody, AI-detection overlays) are data-driven — a layer registry config, not hardcoded per screen — so the same layer switcher component works across the GIS Dashboard, Satellite Monitoring, and Drone Command Center screens.

### Authentication
Session/JWT handled via HttpOnly cookies (not localStorage, to reduce XSS token-theft surface) set by the backend on login; a Next.js middleware (`middleware.ts`) validates the session cookie and role claim on every request before a route group renders, redirecting unauthenticated/unauthorized requests before any page code executes. Token refresh is handled transparently by the API client on 401.

### Permissions
A `usePermission(action, resource)` hook checks against the role/permission claims decoded from the session — used to conditionally render action buttons (e.g., "Dispatch Drone" only visible to roles with `case:dispatch_drone`), while the backend independently re-checks every permission server-side (frontend checks are UX-only, never the security boundary).

### Theme
Light/Dark theme driven by CSS variables mapped 1:1 from the Figma `SATRAK/Color · Light` and `SATRAK/Color · Dark` variable collections (synced via the `tools/design-token-sync` script), toggled via a `ThemeProvider` respecting system preference by default with a manual override persisted per-user.

### Error Handling
Three layers: (1) a root `error.tsx` boundary per route group catching render-time errors with a role-appropriate fallback UI, (2) TanStack Query's `onError` centralized handler mapping API error codes to user-facing messages (never raw stack traces), (3) a global toast system for transient/non-fatal errors (failed notification send, stale data warning). All caught errors are reported to the observability stack (Section 6) with request-correlation IDs, never silently swallowed.
---

# Part 4 — AI Architecture (Implementation View)

This extends TDD Section 5 with the concrete tooling/lifecycle decisions needed to actually build and operate each model.

| Model | Input | Output | Training | Inference | Deployment | Versioning | Monitoring |
|---|---|---|---|---|---|---|---|
| **Building Detection** | Analysis-ready tile (GeoTIFF, 3-4 band) | Building footprint masks + confidence | PyTorch, U-Net/SegFormer backbone; `ai/training/building_detection/train.py`, Hydra config per region | Batched GPU inference via `ai/serving`, ONNX-exported for throughput | KServe `InferenceService` behind `ai-orchestration-service`, GPU node pool | Semantic version tag + weight checksum stored in `model_versions` table; every inference row in `inference_runs` references the exact version | Per-region IoU/F1 tracked nightly against a held-out labeled sample; drift alert if F1 drops >5pts vs. baseline |
| **Building Segmentation (instance)** | Footprint mask + tile | Per-instance polygons | Detectron2/Mask R-CNN, fine-tuned on instance-labeled sets | Chained after Building Detection in the same orchestration DAG | Same KServe pool, separate `InferenceService` | Same pattern | Instance-level mAP tracked per region |
| **Height Estimation** | Tile + sun-angle metadata, or drone DSM | Height estimate (m) + confidence interval | Shadow-geometry regression (scikit-learn) for satellite path; refined via drone DSM ground truth when available | CPU-only for shadow-geometry; lightweight, runs synchronously in orchestration | Packaged as a `py-geo` library function, not a separate service, given low compute cost | Library version pinned per orchestration release | MAE tracked against drone-verified ground truth post-inspection |
| **Floor Count Detection** | Drone facade imagery, or height/floor-height ratio | Estimated floor count + confidence | CNN classifier (PyTorch) on labeled facade datasets | GPU, small model, runs only when drone imagery available | KServe, low-priority GPU pool (can queue behind higher-priority models) | Same pattern | Accuracy within ±1 floor tracked post-drone-inspection |
| **Construction Stage Detection** | Time-series of tiles for one parcel | Stage label (foundation/structure/roofing/finishing/complete) + confidence | Temporal CNN/transformer, PyTorch | GPU, requires multi-tile fetch from `satellite-preprocessing-service` | KServe | Same pattern | Confusion matrix tracked quarterly |
| **Change Detection** | Co-registered tile pair | Change polygons + change-type classification | Siamese CNN, PyTorch, bi-temporal labeled datasets | GPU, the highest-volume inference workload in the system | KServe, dedicated high-throughput GPU pool with autoscaling tied to queue depth | Same pattern; this is the model most likely to need frequent regional retraining | F1 on change/no-change tracked per revisit cycle; false-positive rate is the primary trust metric surfaced to officers |
| **Road Detection** | Tile | Road centerline/polygon | D-LinkNet, PyTorch, OSM weak supervision | GPU, runs in parallel with Building Detection | KServe | Same pattern | IoU tracked; falls back to cached OSM/government layer on low confidence (implemented as an orchestration-level rule, not a model behavior) |
| **Encroachment Detection** | Building/change polygons + GIS boundary layers | Encroachment flag + overlapping area + boundary type | **No training — deterministic GeoPandas/Shapely logic** (ADR-03) | CPU, runs inside `gis-service`, not the AI orchestration pipeline | Standard service deploy, not model-serving infra | Code-versioned via normal service releases, not model-version tracking | Correctness tested via unit tests against known boundary/parcel fixtures, not accuracy metrics |
| **Risk Prediction** | Change/encroachment/permit-match/zoning/historical-density features | Risk score (0–100) + SHAP contribution breakdown | XGBoost/LightGBM, scikit-learn-compatible API, trained on historical officer-labeled outcomes | CPU, runs synchronously in orchestration after upstream detections | Packaged as a versioned model artifact (joblib/ONNX) loaded by `ai-orchestration-service`, not a separate KServe deployment (low compute cost, needs low latency) | Model artifact version in `model_versions`; SHAP explainer versioned alongside the model | AUC-ROC and calibration tracked monthly; cold-start jurisdictions flagged to use the rule-based fallback score |
| **Priority Classification** | Risk score + policy inputs | Priority tier | Rule-based (per-jurisdiction configurable weights), optional learned re-ranking later | CPU, synchronous | Config-driven, part of `case-service`, not model-serving infra | Config version tracked in `model_rollout_config` | Queue-clearance-time correlation reviewed quarterly |
| **Report Generation** | Full case data (structured) | Draft report (template-constrained) | N/A — prompted generation against a hosted LLM, grounded via retrieval, never fine-tuned initially | API call to hosted foundation model via `ai/models/llm-assistant` prompt templates | Called from `reporting-service`; templates versioned in the repo like code | Prompt-template version tracked in `report_generation_log` | Officer edit-rate and factual-consistency spot-checks tracked monthly |
| **LLM Assistant** | Natural-language query + retrieved case context | Grounded natural-language answer with field citations | N/A — RAG only | API call, retrieval layer queries Case/Property/GIS services directly (read-only) | Thin service wrapper in `ai-orchestration-service`; provider abstracted behind an interface so the backing model can be swapped | Retrieval-config and prompt versioned in repo | Groundedness rate and officer satisfaction sampled monthly |

### Cross-cutting AI implementation notes
- **Every inference call writes to `inference_runs`** (model version, weight checksum, input reference, output reference, confidence) before its result is allowed to influence a case — this is the concrete implementation of the audit requirement in TDD Section 11, and it means the AI Orchestration Service's write to this table is a hard dependency in the pipeline, not an optional logging side effect.
- **Model rollout is staged and reversible**: a new model version is deployed to a "shadow" `InferenceService` that runs alongside production, its outputs logged but not acted on, for a configurable evaluation window before an admin promotes it via `POST /admin/models/{id}/rollout`. Rollback is switching the routing config back, not redeploying.
- **Region-stratified evaluation is a release gate**, not a nice-to-have: `ai/evaluation` includes per-jurisdiction benchmark runners, and a model version cannot be promoted to a jurisdiction it hasn't been evaluated against (addresses the AI bias risk in TDD Section 14).
---

# Part 5 — GIS Architecture (Implementation View)

Extends TDD Section 6 with concrete library/schema decisions.

### Spatial Layers
Implemented as separate PostGIS tables rather than a single generic "layers" table, because each layer has different write patterns and different owners:
- `parcels` (owned by `property-service`) — cadastral boundaries, versioned.
- `jurisdiction_boundaries`, `road_network`, `waterbody_boundaries`, `forest_boundaries`, `zoning_layers` (owned by `gis-service`) — regulatory/base layers, updated infrequently, read-heavy.
- `case_geometries`, `drone_flight_footprints` (owned by `case-service`/`drone-service`) — operational layers, written frequently.
- `ai_detection_polygons` (owned by `ai-orchestration-service`) — analytical/derived layer, regenerated per revisit cycle, never hand-edited.

### Raster Data
Stored as Cloud-Optimized GeoTIFFs (COGs) in object storage, never as PostGIS raster blobs — this keeps the transactional database small and lets imagery be served directly via range requests (COG's core advantage) without a database round-trip. PostGIS holds only **references** (scene ID, storage path, bounding box, acquisition date) via the `tile_index` and `satellite_scenes` tables from Part 2.7; actual pixel data is read with `rasterio`/GDAL directly from object storage.

### Vector Data
All vector geometry uses **GeoAlchemy2** as the SQLAlchemy extension (not raw `psycopg2` PostGIS calls) so that Python-side business logic can work with Shapely geometry objects consistently across services, while performance-critical spatial joins (encroachment checks, large-area intersection queries) drop to raw SQL via `func.ST_Intersects` etc. rather than round-tripping full geometries into Python.

### Parcel Management
Parcels are **append-versioned, not mutated in place**: a boundary change (subdivision, merge, government correction) creates a new row in `parcel_boundary_versions` with a `valid_from`/`valid_to` range, and the `parcels` table always reflects the current version. This is required because a case created against a parcel boundary that was later corrected must still show what boundary existed *at the time of detection* — a legal-defensibility requirement, not just a nice history feature.

### Coordinate Systems
Ingestion normalizes everything to a national projected CRS (configured per deployment, e.g., a local UTM zone) for accurate area/distance math; all API responses and map-rendering use WGS84 (EPSG:4326) GeoJSON. The CRS transform boundary lives entirely inside `py-geo` (`to_projected()` / `to_wgs84()` helpers) so no service ever hand-rolls a `pyproj` call — one implementation, one place to fix if the national CRS choice ever changes.

### Spatial Indexing
GiST indexes on every geometry column, `CREATE INDEX ... USING GIST` in the relevant Alembic migration for that table — indexing is not an afterthought added post-launch, it's part of the initial migration for any geometry column. Tile-index lookups additionally use a covering B-tree index on `(z, x, y, scene_id)` since tile fetches are the highest-QPS spatial-adjacent query in the system.

### Map Rendering
Vector tiles (MVT) served from `gis-service` for parcel/road/boundary layers (via `ST_AsMVT`, generated on the fly with a short cache TTL rather than pre-baked, since boundary edits — though infrequent — must show up without a rebuild step); raster tiles (COG-backed) served directly from object storage/CDN for satellite imagery. `packages/ts-map-kit` composes both into MapLibre's layer stack; CesiumJS handles the separate 3D rendering path for drone point-clouds/DSMs, which are too heavy to route through the 2D vector-tile pipeline.

---

# Part 6 — Project Bootstrap

### Docker Compose (local development)
A single root `infra/docker-compose/docker-compose.yml` brings up: `postgis` (PostgreSQL 16 + PostGIS 3.4), `redis`, `kafka` + `zookeeper` (or `redpanda` as a lighter local alternative), `minio` (S3-compatible object storage for local dev), and one container per backend service with hot-reload volumes mounted. An `docker-compose.override.yml` adds GPU passthrough for AI services only when a local GPU is available, so the default `make dev` works on a laptop without one (AI services fall back to CPU-mode stub inference locally).

### Environment Variables
Managed via `.env.example` checked into the repo (never real secrets) with one file per service (`services/case-service/.env.example`), consumed via `pydantic-settings` `BaseSettings` classes so every service validates its required env vars at startup and fails fast with a clear error rather than a runtime `KeyError` three requests in. Naming convention: `SATRAK_<SERVICE>_<VAR>` (e.g., `SATRAK_CASE_SERVICE_DATABASE_URL`) to avoid collisions when services share a compose network namespace.

### Configuration Structure
Layered config resolution per service: defaults in code → `.env` file → environment variables → (in deployed environments) secrets-manager-injected values, in that precedence order. No service reads a secrets manager directly in local dev — that path only activates when `SATRAK_ENV=staging|production`.

### Secrets Management
Local/dev: `.env` files (gitignored). Staging/Production: cloud KMS-backed secrets manager (e.g., AWS Secrets Manager/GCP Secret Manager/Azure Key Vault depending on final cloud selection per TDD Open Question #10), injected as environment variables at container start via the orchestration platform's native secrets integration — never baked into container images, never logged (structured logging config includes a redaction filter for known secret-shaped keys as a safety net).

### Logging
Structured JSON logging (via `structlog` in Python, `pino` in Node/Next.js) with a mandatory `request_id`/`trace_id` field propagated via middleware across service boundaries (W3C Trace Context headers), so a single citizen-facing request can be followed through gateway → case-service → gis-service → audit-service in the log aggregator. Log level per environment: `DEBUG` local, `INFO` staging/production, with sensitive fields (PII, tokens) redacted at the logging-middleware layer, not left to individual call sites to remember.

### Monitoring
OpenTelemetry SDK in every service (traces + metrics), exported to Prometheus (metrics) and a tracing backend (e.g., Tempo/Jaeger). Standard RED metrics (Rate, Errors, Duration) auto-instrumented at the FastAPI/Next.js middleware level; business metrics (cases created/hour, AI confidence distribution, drone missions in flight) emitted explicitly from service code as custom Prometheus counters/histograms. Grafana dashboards are defined as code (`infra/monitoring/dashboards/*.json`, checked in) not click-ops'd in the UI.

### Error Handling (backend)
A shared FastAPI exception-handling middleware in `py-common` maps domain exceptions (`CaseNotFoundError`, `PermissionDeniedError`) to consistent HTTP status codes and a standard error-response envelope (`{error_code, message, request_id}`), so frontend error handling (Part 3) can pattern-match on `error_code` rather than parsing message strings. Unhandled exceptions are caught at the outermost middleware layer, logged with full stack trace + trace ID, and returned to the client as a generic 500 with no internal detail leaked.

### Testing Strategy
- **Unit tests** (pytest / Vitest): service-layer and repository-layer logic, run on every commit, required to pass before merge.
- **Contract tests**: OpenAPI schema validation against actual responses (Schemathesis or similar) — catches drift between a service's implementation and its published spec before it breaks the generated TS client.
- **Integration tests**: spin up the real `docker-compose` stack (or a scoped subset) in CI, test cross-service flows (e.g., case creation → notification dispatch) against real PostGIS/Redis/Kafka, not mocks.
- **E2E tests** (Playwright): critical officer workflows (login → review case → dispatch drone → approve report) run against a staging-like environment nightly and on release-candidate branches, not on every PR (too slow).
- **AI evaluation tests**: `ai/evaluation` regional benchmark suite, run on every model-version candidate before rollout — a release gate, not a CI check on every commit (too expensive to run per-PR).

### CI/CD Strategy
GitHub Actions, with a **path-filtered, affected-only** pipeline (Turborepo's affected-graph for frontend, a custom changed-files matrix for `services/*`): a PR touching only `services/drone-service` triggers drone-service's unit/contract/integration tests and its container build, not the entire monorepo's suite. Merge to `main` triggers: build → push to container registry → deploy to `staging` automatically (GitOps, ArgoCD watching a `staging` overlay) → manual promotion gate → deploy to `production`. Database migrations run as a separate, explicit pipeline step (`alembic upgrade head` against the target environment) gated behind a manual approval in production, never auto-applied on deploy.
---

# Part 7 — Epics

Epics are sequenced to respect real dependency order (you cannot build Case Management before Authentication and Properties exist), not by perceived importance. Priority reflects what unblocks the most downstream work, not business value in isolation.

## Epic 1 — Authentication & Access Control
- **Objectives:** Stand up SSO/OIDC login, JWT session handling, MFA, and jurisdiction-scoped RBAC as the foundation every other epic depends on.
- **Deliverables:** `auth-service` deployed; login/refresh/MFA flows working end-to-end; RBAC middleware usable by all other services; admin UI for role/permission assignment.
- **Dependencies:** None — this is the starting point.
- **Acceptance Criteria:** A user can log in via government SSO, complete MFA, receive a scoped JWT, and be denied access to a jurisdiction they're not assigned to; all events (login, login-failure, permission-denied) are captured in the audit log.
- **Estimated Complexity:** Medium (well-understood problem, but SSO integration with a specific government IdP is often the long pole).
- **Priority:** P0 — blocks everything.

## Epic 2 — Organizations & Users
- **Objectives:** Model the government org hierarchy and user/role/jurisdiction assignment on top of Epic 1.
- **Deliverables:** Organization CRUD + hierarchy API; user invitation flow; admin console screens for org/user management.
- **Dependencies:** Epic 1.
- **Acceptance Criteria:** An admin can create a jurisdiction hierarchy (State → Dept → Corporation → Ward), invite an officer, and assign them to a Ward-scoped role, and that officer's session reflects the correct scope.
- **Estimated Complexity:** Low–Medium.
- **Priority:** P0.

## Epic 3 — Property & Parcel Management
- **Objectives:** Stand up the canonical parcel/property registry, including cadastral import.
- **Deliverables:** `property-service` deployed; parcel import pipeline (batch cadastral upload → validated PostGIS records); property search/profile API and UI.
- **Dependencies:** Epic 1 (auth), Epic 6 (GIS Engine, for spatial validation on import — see note on parallelization below).
- **Acceptance Criteria:** A cadastral shapefile/GeoJSON import creates correctly indexed parcel records; a property profile screen shows parcel geometry, ownership, and permit status.
- **Estimated Complexity:** Medium–High (real-world cadastral data is messy; expect significant data-cleaning tooling).
- **Priority:** P0.

## Epic 4 — GIS Engine
- **Objectives:** Deliver the shared spatial-query service every other epic depends on.
- **Deliverables:** `gis-service` deployed; boundary-layer ingestion (roads, water bodies, forest, zoning); intersection/buffer query API; encroachment-check API (deterministic logic).
- **Dependencies:** Epic 1. Note: Epic 3 and Epic 4 have a circular-looking dependency (parcels need GIS validation, GIS needs parcel data to be useful) — resolve by building Epic 4's query engine against a minimal boundary-layer dataset first, then integrating full parcel data once Epic 3 lands. These two epics should run in parallel with weekly integration checkpoints, not strictly sequentially.
- **Acceptance Criteria:** Given two polygons, the intersection/buffer API returns correct results within the performance targets (TDD Section 13); an encroachment check against a known test fixture correctly flags/clears as expected.
- **Estimated Complexity:** Medium–High.
- **Priority:** P0 (parallel with Epic 3).

## Epic 5 — Satellite Engine
- **Objectives:** Automated satellite scene acquisition and preprocessing into analysis-ready tiles.
- **Deliverables:** `satellite-ingestion-service` + `satellite-preprocessing-service` deployed; at least one satellite provider integrated end-to-end; tile-serving API; AOI configuration UI.
- **Dependencies:** Epic 4 (tiles need to correlate with jurisdiction boundaries).
- **Acceptance Criteria:** A scheduled acquisition for a configured AOI produces analysis-ready, correctly-tiled COGs within the processing-time target (TDD Section 13), with provenance metadata attached.
- **Estimated Complexity:** High (external provider integration + distributed raster processing is genuinely hard).
- **Priority:** P0.

## Epic 6 — AI Detection Pipeline
- **Objectives:** Deliver the building detection → change detection → risk scoring pipeline against real tiles.
- **Deliverables:** `ai-orchestration-service` deployed; Building Detection and Change Detection models trained and serving; Risk Prediction model (rule-based baseline acceptable at launch); `inference_runs` audit trail working.
- **Dependencies:** Epic 5 (needs tiles to run against), Epic 4 (needs parcel correlation).
- **Acceptance Criteria:** A processed tile produces a building-footprint mask, a change polygon (against a baseline), and a risk score, each traceable to a specific model version in the audit trail; region-stratified evaluation meets the F1 targets in TDD Section 1.6 before this epic is considered launch-ready for a given jurisdiction.
- **Estimated Complexity:** Very High — this is the epic most likely to run over initial estimates; budget for iteration.
- **Priority:** P0.

## Epic 7 — Case Management
- **Objectives:** Build the central case lifecycle service that ties AI output, officer review, and downstream action together.
- **Deliverables:** `case-service` deployed; case queue UI; officer review workflow; SLA tracking; case-status event stream.
- **Dependencies:** Epic 6 (candidate cases originate from AI), Epic 2 (assignment needs users/roles).
- **Acceptance Criteria:** A high-risk AI detection creates a candidate case visible in the correct jurisdiction's officer queue; an officer can approve/reject with the decision captured in the audit trail.
- **Estimated Complexity:** Medium–High.
- **Priority:** P0.

## Epic 8 — Drone Operations
- **Objectives:** Mission planning, dispatch, and photogrammetry processing triggered from an approved case.
- **Deliverables:** `drone-service` deployed; mission planner UI; pilot upload flow; photogrammetry pipeline (orthomosaic/DSM/point cloud); mission report generation.
- **Dependencies:** Epic 7 (missions are dispatched from cases).
- **Acceptance Criteria:** An officer can dispatch a drone mission from a case, a pilot can upload flight imagery, and the system produces a viewable orthomosaic/3D model attached back to the case within the processing-time target.
- **Estimated Complexity:** High (photogrammetry infra + GPU processing pipeline).
- **Priority:** P1.

## Epic 9 — Reports & Notifications
- **Objectives:** Structured report generation (including LLM-assisted drafting) and multi-channel citizen/officer notification.
- **Deliverables:** `reporting-service` and `notification-service` deployed; report templates for inspection/compliance/court-evidence reports; SMS/email dispatch integrated with at least one provider.
- **Dependencies:** Epic 7 (reports summarize case data), Epic 8 (drone evidence feeds final reports).
- **Acceptance Criteria:** A resolved case can generate a legally-formatted report requiring officer approval before export, and trigger a citizen notification with delivery tracking.
- **Estimated Complexity:** Medium.
- **Priority:** P1.

## Epic 10 — Analytics & Administration
- **Objectives:** Aggregate dashboards (ward/city/executive) and the admin control plane (model rollout, feature flags, API keys).
- **Deliverables:** Analytics Warehouse ETL pipeline; ward/city/executive dashboard UIs; admin console for model version rollout and system configuration.
- **Dependencies:** Epic 7, Epic 6 (needs case + AI data to aggregate).
- **Acceptance Criteria:** A commissioner can view ward-level violation trends and drill into officer performance; an admin can stage and promote a new AI model version without a full redeploy.
- **Estimated Complexity:** Medium.
- **Priority:** P1–P2 (valuable but not launch-blocking for a pilot jurisdiction).

## Epic 11 — Citizen Portal
- **Objectives:** Public-facing property status lookup, complaint submission, and notice tracking.
- **Deliverables:** `apps/citizen-portal` deployed separately; complaint intake flow feeding into `case-service`; public notice lookup by case reference number.
- **Dependencies:** Epic 7, Epic 9 (notices must exist to be looked up).
- **Acceptance Criteria:** A citizen can search a property by address/survey number, view its public compliance status, and submit a complaint that creates a trackable case reference.
- **Estimated Complexity:** Medium.
- **Priority:** P2 — valuable for transparency/trust goals but not required for internal enforcement workflows to function.
---

# Part 8 — Features → Tasks → Subtasks

Full task/subtask decomposition for all 11 epics in one document would run to hundreds of pages and go stale before a single sprint finished — that level of detail belongs in the team's issue tracker (Jira/Linear), generated epic-by-epic right before that epic starts, not written speculatively now. What's genuinely useful today is: (a) the **feature-level breakdown for every epic**, which is stable enough to plan sprints against, and (b) a **fully worked task/subtask example for the two highest-priority, highest-risk epics** (Authentication, AI Detection Pipeline) so the team has a concrete template to replicate for the rest.

## 8.1 Feature-level breakdown — all epics

**Epic 1 — Authentication & Access Control**
Features: SSO/OIDC integration · JWT issuance & refresh · MFA enrollment & verification · RBAC policy engine · Session management & revocation · Audit event emission.

**Epic 2 — Organizations & Users**
Features: Org hierarchy CRUD · User invitation flow · Role/jurisdiction assignment UI · Org-level settings & feature flags.

**Epic 3 — Property & Parcel Management**
Features: Cadastral batch import pipeline · Parcel versioning (subdivision/merge tracking) · Property profile & search · Ownership history · Permit record management & matching.

**Epic 4 — GIS Engine**
Features: Boundary-layer ingestion (roads/water/forest/zoning) · Intersection/buffer query API · Encroachment-check engine · Vector-tile (MVT) serving · Boundary data-quality scoring.

**Epic 5 — Satellite Engine**
Features: Provider integration & tasking · Acquisition scheduler · Cloud/shadow masking · Orthorectification · Tiling & COG generation · Tile-serving API · AOI configuration UI.

**Epic 6 — AI Detection Pipeline**
Features: Building detection model & serving · Change detection model & serving · Risk scoring (rule-based baseline → learned model) · Inference orchestration DAG · Model versioning & rollout control · Inference audit trail.

**Epic 7 — Case Management**
Features: Case creation from AI triggers · Officer review workflow · Case assignment & SLA tracking · Case status state machine · Case evidence bundling.

**Epic 8 — Drone Operations**
Features: Mission planning & airspace-check integration · Pilot upload flow · Photogrammetry pipeline (SfM/orthomosaic/DSM) · Mission report generation · Dashboard 3D-viewer integration.

**Epic 9 — Reports & Notifications**
Features: Report template engine · LLM-assisted draft generation with grounding checks · PDF/Word export · SMS/email/push dispatch · Delivery tracking & retry.

**Epic 10 — Analytics & Administration**
Features: Warehouse ETL/CDC pipeline · Ward/city/executive dashboards · Officer performance analytics · Model rollout admin UI · API key & feature-flag management.

**Epic 11 — Citizen Portal**
Features: Public property search · Complaint submission → case creation bridge · Notice lookup by reference number · Feedback/help flow.

## 8.2 Worked example — Epic 1: Authentication & Access Control

**Feature: SSO/OIDC Integration**
- Task: Register SATRAK as a relying party with the government identity provider.
  - Subtask: Obtain client ID/secret and redirect URI allowlist from IdP admin.
  - Subtask: Implement OIDC discovery-document fetch and JWKS caching in `auth-service`.
  - Subtask: Implement authorization-code-flow callback handler with PKCE.
- Task: Map IdP claims to internal user records.
  - Subtask: Define claim-to-field mapping (email, department, employee ID) in config, not hardcoded.
  - Subtask: Implement just-in-time user provisioning on first successful login (create `users` row if not exists, flagged `pending_role_assignment`).
- Task: Handle IdP outage gracefully.
  - Subtask: Cache JWKS with a stale-while-revalidate policy so brief IdP downtime doesn't block already-cached-key validation.
  - Subtask: Define and implement the user-facing error state when the IdP is unreachable.

**Feature: JWT Issuance & Refresh**
- Task: Implement access/refresh token pair issuance.
  - Subtask: Short-lived access token (15 min) signed with rotating RS256 key pair.
  - Subtask: Refresh token stored server-side (`sessions` table) with rotation-on-use (old refresh token invalidated when a new one is issued) to limit replay risk.
- Task: Implement token refresh endpoint and frontend auto-refresh interceptor.
  - Subtask: Backend `POST /auth/refresh` validating refresh token against `sessions`.
  - Subtask: Frontend API client 401-interceptor triggering silent refresh before retrying the original request.

**Feature: MFA Enrollment & Verification**
- Task: TOTP-based MFA enrollment flow.
  - Subtask: QR-code provisioning UI + backend secret generation/storage (encrypted at rest).
  - Subtask: Backup-code generation and one-time display.
- Task: MFA verification at login.
  - Subtask: Backend TOTP validation with clock-skew tolerance.
  - Subtask: Rate-limit MFA attempts (lockout after N failures, logged as a security event).

**Feature: RBAC Policy Engine**
- Task: Define the permission model (resource + action + jurisdiction scope).
  - Subtask: Schema design for `roles`, `permissions`, `role_permissions` supporting jurisdiction-scoped grants.
  - Subtask: Implement `RbacService.check(user, action, resource, jurisdiction)` as the single call site every other service uses.
- Task: Expose RBAC as a shared middleware/library (`py-common`), not a per-service reimplementation.
  - Subtask: FastAPI dependency-injection helper (`Depends(require_permission("case:dispatch_drone"))`).
  - Subtask: Frontend `usePermission()` hook consuming decoded JWT claims.

**Feature: Session Management & Revocation**
- Task: Implement admin-triggered session revocation (e.g., on role change or account compromise).
  - Subtask: `POST /admin/users/{id}/revoke-sessions` invalidating all active refresh tokens for a user.
  - Subtask: Real-time propagation so an already-issued access token stops working before its natural 15-minute expiry (short-lived access tokens make this acceptable without a revocation-check-on-every-request cost).

**Feature: Audit Event Emission**
- Task: Emit structured audit events for every auth-relevant action.
  - Subtask: `user.logged_in`, `user.login_failed`, `mfa.verified`, `session.revoked` events published to the event bus.
  - Subtask: Confirm `audit-service` consumer correctly hash-chains these events (integration test against Epic 1 + a stub audit consumer, since full `audit-service` may not exist yet — build the stub first, swap for the real service without changing the publish contract).

## 8.3 Worked example — Epic 6: AI Detection Pipeline

**Feature: Building Detection Model & Serving**
- Task: Assemble and label the initial training dataset.
  - Subtask: Source open building-footprint datasets for baseline pretraining.
  - Subtask: Establish a regional labeling workflow (in-house GIS analysts or a labeling vendor) for fine-tuning data, with a documented labeling guideline doc (edge cases: shadows, under-construction roofs, dense informal settlements).
- Task: Train and evaluate the model.
  - Subtask: Implement the training script (`ai/training/building_detection/train.py`) with Hydra-configured hyperparameters per region.
  - Subtask: Implement the regional evaluation harness (`ai/evaluation/building_detection/`) computing IoU/F1 against held-out sets.
  - Subtask: Document the go/no-go threshold (F1 ≥ 0.90 per TDD Section 1.6) as an automated check, not a manual judgment call, before a model version can be promoted.
- Task: Deploy as a served model.
  - Subtask: Export to ONNX for inference-runtime portability.
  - Subtask: Wrap in a KServe `InferenceService` manifest (`infra/k8s/ai/building-detection/`).
  - Subtask: Load-test the serving endpoint against the expected tile-throughput target (TDD Section 13).

**Feature: Inference Orchestration DAG**
- Task: Implement the orchestration pipeline as an explicit, inspectable DAG (not an implicit chain of function calls).
  - Subtask: Choose a lightweight DAG runner appropriate for this scale (e.g., a Celery task chain with explicit stage boundaries, or Prefect if the team wants richer observability) — this is a genuine open decision, flagged in Part 10.
  - Subtask: Implement the stage sequence: tile-ready event → building detection → change detection → GIS correlation → risk scoring → confidence-threshold gate → case-candidate event.
  - Subtask: Implement per-stage retry/backoff and dead-letter handling so one tile's model failure doesn't stall the batch.
- Task: Write every stage's output to `inference_runs` before advancing the DAG.
  - Subtask: Schema migration for `inference_runs` with model-version and confidence columns.
  - Subtask: Integration test verifying a full DAG run produces a complete, correctly-linked audit trail from tile to candidate case.

**Feature: Model Versioning & Rollout Control**
- Task: Implement the shadow-deployment rollout mechanism described in Part 4.
  - Subtask: Routing-config schema (`model_rollout_config`) supporting "shadow" vs. "active" state per model per jurisdiction.
  - Subtask: Admin UI screen to view shadow-mode comparison metrics and promote/rollback a version.
---

# Part 9 — Development Roadmap (Sprints)

Two-week sprints assumed. This roadmap sequences work by real dependency order (Part 7's epic dependencies), with GIS Engine and Property/Parcel running in parallel per the note in Epic 4. "Independently deployable" means: at the end of the sprint, the newly built services can be deployed to staging and exercised end-to-end for what they cover so far — not that the full product is usable, which only becomes true much later.

| Sprint | Focus | Deployable Outcome |
|---|---|---|
| **Sprint 0** | Bootstrap | Monorepo scaffolded (Part 1 structure); `docker-compose` stack runs locally; CI pipeline skeleton (lint + unit test on every PR); base Terraform modules for one cloud environment (dev). Nothing user-facing yet. |
| **Sprint 1** | Epic 1, part 1 | `auth-service` deployed to staging with SSO/OIDC login and JWT issuance working; no MFA/RBAC yet. A developer can log in and get a token. |
| **Sprint 2** | Epic 1, part 2 | MFA and full RBAC policy engine complete; session revocation working; audit event emission wired to a stub consumer. Epic 1 is feature-complete. |
| **Sprint 3** | Epic 2 | Organization hierarchy + user invitation flow live; admin console shell (empty except org/user screens) deployed. An admin can onboard a jurisdiction and invite an officer. |
| **Sprint 4** | Epic 4, part 1 (parallel: Epic 3, part 1) | GIS Engine: boundary-layer ingestion + intersection/buffer API against a minimal test boundary set. Property Service: parcel schema + cadastral import pipeline (not yet integrated with GIS validation). |
| **Sprint 5** | Epic 4, part 2 + Epic 3, part 2 | GIS/Property integration complete: cadastral import validates against GIS boundaries; encroachment-check API working against real imported parcels; property profile screen live. |
| **Sprint 6** | Epic 5, part 1 | Satellite Engine: one provider integrated, acquisition scheduler running against a configured pilot-jurisdiction AOI; raw scene ingestion working (no preprocessing yet). |
| **Sprint 7** | Epic 5, part 2 | Full preprocessing pipeline (cloud masking → orthorectification → tiling) producing served, analysis-ready tiles for the pilot AOI. Satellite Engine is feature-complete for the pilot jurisdiction. |
| **Sprint 8** | Epic 6, part 1 | Building Detection model trained against pilot-jurisdiction imagery and passing the F1 ≥ 0.90 gate; served via KServe; orchestration DAG stage 1 wired to real tiles. |
| **Sprint 9** | Epic 6, part 2 | Change Detection model trained and integrated as DAG stage 2; rule-based Risk Prediction baseline wired as stage 3; `inference_runs` audit trail verified end-to-end. |
| **Sprint 10** | Epic 6, part 3 | Model versioning/rollout control (shadow deployment) implemented; first region-stratified evaluation run completed and documented as a launch-readiness artifact. AI Detection Pipeline is feature-complete for the pilot jurisdiction. |
| **Sprint 11** | Epic 7, part 1 | Case Management: case creation from AI candidate events, case queue UI, basic officer review (approve/reject) working. An officer can see and act on a real AI-detected case for the first time. |
| **Sprint 12** | Epic 7, part 2 | Assignment, SLA tracking, and full case-status state machine complete; case-evidence bundling (satellite imagery + AI output attached to a case) working. |
| **Sprint 13** | Epic 8, part 1 | Drone Operations: mission planning UI, dispatch-from-case flow, pilot upload endpoint working (no photogrammetry processing yet — raw imagery stored). |
| **Sprint 14** | Epic 8, part 2 | Photogrammetry pipeline (orthomosaic/DSM/point cloud) and mission report generation complete; drone evidence viewable in the case detail panel (the screen already prototyped in Figma). |
| **Sprint 15** | Epic 9 | Reports & Notifications: report template engine, LLM-assisted drafting with officer-approval gate, PDF export, and SMS/email dispatch with delivery tracking all live. A case can now go from detection to a citizen-facing notice end-to-end — **this is the first sprint where the full core workflow (TDD Section 4) is deployable start-to-finish.** |
| **Sprint 16** | Epic 10 | Analytics & Administration: warehouse ETL running, ward/city dashboards live, model-rollout admin UI complete. |
| **Sprint 17** | Epic 11 | Citizen Portal: public property search, complaint submission bridged into case creation, notice lookup. |
| **Sprint 18** | Hardening | Security review remediation, load testing against TDD Section 13 targets, DR drill (per TDD Section 12), accessibility audit (WCAG 2.2 AA) on all officer/citizen screens. |
| **Sprint 19–20** | Pilot launch prep | Jurisdiction-specific configuration for the actual launch jurisdiction (boundary data loading, permit-feed integration if available, officer onboarding/training materials), staged rollout plan execution, go-live readiness review against every acceptance criterion in Part 7. |

**Buffer note:** Sprints 8–10 (AI Detection Pipeline) and Sprint 6–7 (Satellite Engine) are the two most likely to slip — real-world model training and external provider integration rarely go exactly to plan. This roadmap does not pad individual sprints with slack; instead, treat Sprints 18–20 as the flexible buffer zone and be willing to compress hardening scope (not core-workflow scope) if earlier sprints run over.
---

# Part 10 — Architecture Review: Weaknesses, Risks, and Recommendations

This section is deliberately adversarial to the plan above — the point of writing it is to find problems now, while they're cheap to fix, not after Sprint 10.

### 1. The AI Detection Pipeline epic is underscoped relative to its actual difficulty
Epic 6 is listed as one epic with three "parts," but training a building-detection model to F1 ≥ 0.90 and a change-detection model with an acceptable false-positive rate, **per region**, against real (often messy, cloud-affected, informally-built) imagery, is realistically the highest-uncertainty piece of the entire project. It's the one place in this blueprint most likely to be treated as "a few sprints of ML work" when it's closer to an ongoing research effort with an uncertain timeline.
**Recommendation:** Start data collection and labeling for the pilot jurisdiction in Sprint 0/1, in parallel with Auth/GIS work, not in Sprint 8 when the pipeline epic officially starts. Model quality should be tracked as a continuously-updated metric from the first labeled batch onward, not treated as a binary pass/fail gate that appears for the first time in Sprint 10. Budget an explicit "model quality did not meet threshold" contingency plan — e.g., launching with a lower-confidence model that creates more manual-review cases rather than blocking launch entirely.

### 2. The GIS Engine ↔ Property Service circular dependency is real and not fully resolved by "run them in parallel"
Part 7 acknowledges the circularity but the resolution ("build GIS against a minimal boundary set, integrate later") pushes real integration risk into Sprint 5 without a concrete integration contract defined earlier. If the two teams build against divergent assumptions about geometry format, CRS handling, or what "a parcel" even means (a survey parcel vs. a subdivided plot vs. a merged holding), Sprint 5 becomes a renegotiation, not an integration.
**Recommendation:** Before Sprint 4 starts, both teams should jointly write and freeze a shared parcel-geometry contract (exact GeoJSON/WKT shape, CRS, versioning fields) as an ADR, and build against that contract independently — the parallelization is safe once the contract is fixed, and unsafe if it's left implicit.

### 3. Rule-based Risk Prediction as a "baseline" risks becoming permanent
TDD ADR and this blueprint both describe the learned Risk Prediction model as depending on historical officer-labeled outcomes that don't exist yet — meaning at actual launch, every jurisdiction is a cold start running the rule-based fallback. There's a real risk that the rule-based version works "well enough" that the learned model never gets prioritized, and the AI Goals in TDD Section 1.6 quietly go unmet indefinitely.
**Recommendation:** Explicitly track "officer decision" as a first-class labeled event from Sprint 11 onward (every approve/reject in Case Management is potential training data), and put a concrete re-evaluation checkpoint on the calendar (e.g., 90 days post-launch: does labeled volume support a first learned-model training run?) rather than leaving it as an unscheduled "future work" item.

### 4. The event bus is a single point of coupling that isn't stress-tested until very late
Nearly every service in this architecture publishes/consumes events (Kafka), and `case-service`'s event stream in particular is described as "the most heavily consumed" in Part 2.11 — yet the roadmap doesn't include a dedicated load/chaos test of the event bus itself until Sprint 18 (Hardening). If Kafka partitioning, consumer-group scaling, or backpressure handling is wrong, it likely won't surface until the system is under real multi-jurisdiction load, by which point every service's assumptions about "the event will arrive" are baked in.
**Recommendation:** Add a lightweight event-bus load test as an explicit deliverable in Sprint 9 or 10 (once AI Orchestration is producing real event volume) rather than deferring all load testing to Sprint 18 — catching a partitioning-strategy mistake at Sprint 10 is a schema/config change; catching it at Sprint 18 may mean reworking multiple services' consumer logic.

### 5. "Human-in-the-loop" is an architectural principle without an architected escape hatch for scale
TDD ADR-04 correctly mandates officer review before any enforcement action. But this blueprint doesn't specify what happens when detection volume at national scale (TDD's stated ambition) outpaces officer review capacity — the honest failure mode of a mandatory-human-review system under load is a growing backlog, not a graceful degradation. Nothing in Epic 7 or the roadmap addresses queue-overflow behavior.
**Recommendation:** Decide now (not during a future incident) what the system does when the review queue SLA is structurally unmeetable for a jurisdiction: auto-triage lower-priority cases to a longer SLA tier, surface a capacity-shortfall metric to commissioners rather than silently growing the backlog, or both. This is a product/policy decision as much as a technical one, and it belongs in Epic 7's acceptance criteria, not as an implicit assumption.

### 6. The DAG-runner choice for AI Orchestration is left genuinely open (flagged, not resolved)
Part 8.3 flags a real open decision (Celery task chains vs. Prefect or similar) and doesn't resolve it. This is honest, but it's also a decision that affects retry semantics, observability, and how Sprint 8–10 work gets structured — leaving it open past Sprint 0 risks the orchestration DAG being built twice.
**Recommendation:** Timebox this decision to a Sprint 0 spike (1–2 days), not something the AI team decides implicitly while building Sprint 8 — the choice affects `py-common` shared tooling that other services may also want to reuse for their own background-job chains (e.g., photogrammetry processing in Epic 8 has similar multi-stage-pipeline shape).

### 7. Multi-tenancy/jurisdiction-sharding strategy is assumed but never concretely designed
TDD Section 1.3 and this blueprint both reference "sharded by jurisdiction/state" for services like `case-service`, but no part of this document specifies the actual sharding mechanism (separate databases per state? row-level jurisdiction_id partitioning within one database? separate deployed service instances per state?). This matters enormously for the difficulty of Epic 3/4/7 and is currently underspecified enough that different engineers could reasonably build incompatible assumptions.
**Recommendation:** This deserves its own ADR before Epic 3/4 implementation starts (not before this blueprint is finalized — it can be Sprint 1's first ADR) — the likely pragmatic answer for a pilot-then-scale rollout is row-level `jurisdiction_id` partitioning with logical isolation enforced by RBAC/RLS (Postgres Row-Level Security) initially, with physical sharding-by-state deferred until a specific jurisdiction's data volume or a specific data-residency requirement (e.g., a state demanding its own physical database) forces the split — but this should be a stated decision, not a default nobody chose.

### 8. Overall assessment
The architecture is sound and the epic/sprint sequencing correctly respects real dependencies — this is not a case of the plan being wrong in its broad strokes. The risks above are concentrated in exactly the places you'd expect for a project of this kind: the AI pipeline's real-world difficulty, the places where two teams' work must integrate, and the operational failure modes (queue overflow, event-bus load) that only show up under real usage. None of these are reasons to change the epic order in Part 7 or the sprint sequence in Part 9 — they're reasons to add specific, dated checkpoints (data labeling starting in Sprint 0, a frozen parcel-geometry ADR before Sprint 4, an event-bus load test in Sprint 9–10, a jurisdiction-sharding ADR in Sprint 1) so that the plan's known unknowns get resolved on a schedule instead of being discovered as surprises.

---

*End of Implementation Blueprint.*
