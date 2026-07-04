# SATRAK — Engineering Blueprint

**Status:** Draft v1.0
**Last updated:** 2026-07-05
**Companion documents:** [PRD.md](PRD.md), [TDD.md](TDD.md)

This document defines how SATRAK is built day-to-day: repository layout, branching, commit/versioning conventions, coding and testing standards, CI/CD, and the implementation roadmap. It complements the *what* (PRD) and the *how it's architected* (TDD) with the *how we work*.

---

## 1. Planned Repository Structure

SATRAK is a polyglot system (Python ML/services + TypeScript frontend + infra). A monorepo is used for v1 to keep the pipeline, backend, and frontend evolving together while shared architecture is still settling; splitting into multiple repos can happen later once module boundaries stabilize.

```
satrak/
├── PRD.md
├── TDD.md
├── ENGINEERING_BLUEPRINT.md
├── README.md
├── LICENSE
├── .gitignore
├── apps/
│   ├── web/                 # React frontend (officer dashboard, admin, transparency portal)
│   └── mobile/              # Field-officer mobile app
├── services/
│   ├── ingestion/           # Data ingestion & orchestration (Airflow/Prefect DAGs)
│   ├── preprocessing/       # Ortho, cloud masking, co-registration, radiometric normalization
│   ├── detection/           # Footprint extraction, height/floor estimation, change detection models
│   ├── rules-engine/        # GIS overlay & violation classification
│   ├── risk-scoring/        # Prioritization service
│   ├── case-management/     # Case/report/workflow API
│   └── notifications/       # Alerts & transparency-portal API
├── ml/
│   ├── models/              # Model definitions, checkpoints (or pointers to model registry)
│   ├── training/            # Training/fine-tuning scripts
│   └── evaluation/          # Benchmarking against LEVIR-CD, OSCD, SpaceNet, etc.
├── infra/
│   ├── docker/
│   ├── k8s/
│   └── terraform/ (or equivalent for chosen deployment target)
├── docs/
│   └── (architecture decision records, runbooks, API specs)
└── scripts/
```

*This structure is a starting recommendation, not final — it should be validated against the actual module boundaries once implementation begins (see §7).*

---

## 2. Git Branching Strategy

**Trunk-based development with short-lived feature branches**, appropriate for a small initial team:

- `main` — always deployable; protected branch; requires PR + review before merge.
- `feature/<short-description>` — one branch per unit of work, branched from `main`, merged via PR.
- `fix/<short-description>` — bug fixes, same flow.
- `release/<version>` — cut only when preparing a tagged release to a pilot environment (optional until v1 nears deployment).

Avoid long-lived `develop` branches — they accumulate drift and merge pain disproportionate to team size at this stage.

---

## 3. Commit Message Convention

**Conventional Commits**, since the project spans multiple languages/services and benefits from machine-parseable history (changelogs, semantic-release tooling later):

```
<type>(<optional scope>): <short summary>

[optional body]
[optional footer]
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`, `build`.

Examples:
- `feat(detection): add Siamese change-detection head on Prithvi backbone`
- `fix(rules-engine): correct buffer tolerance for parcel intersection`
- `docs: initialize SATRAK project documentation and repository`

---

## 4. Versioning Strategy

- **Semantic Versioning (SemVer)** — `MAJOR.MINOR.PATCH` — for released artifacts (backend services, mobile app, deployable pipeline images).
- Pre-v1.0.0, the project is in `0.x.y` — breaking changes are expected and acceptable.
- Model checkpoints are versioned independently (e.g., `detection-model-v0.3.0`) and tracked in a model registry/manifest, decoupled from application release versioning, since retraining cadence differs from software release cadence.

---

## 5. Coding Standards

- **Python:** PEP 8, enforced via `ruff`/`black`; type hints required on public functions; `mypy` for static type checking on backend services.
- **TypeScript/React:** ESLint + Prettier; strict TypeScript (`strict: true`); no implicit `any`.
- **Geospatial code:** always carry and validate CRS (coordinate reference system) explicitly through pipeline stages — silent CRS mismatches are a common, hard-to-detect source of spatial bugs.
- **Notebooks:** allowed for exploration only; no notebook code ships to production services — logic must be promoted into tested modules.
- **Docstrings/comments:** explain *why*, not *what*, per general engineering practice — avoid restating what well-named code already shows.

---

## 6. Testing Standards

- **Unit tests** for all rule-engine logic (§3.6 in TDD) — these are deterministic and must have high coverage given their legal-defensibility role.
- **Model evaluation harness** for detection/change-detection models against held-out benchmark datasets (LEVIR-CD, OSCD, SpaceNet) plus any pilot-city labeled data, tracked over successive training runs.
- **Integration tests** for the ingestion → preprocessing → detection → rule-engine pipeline using fixture imagery, so a broken stage is caught before touching real satellite tasking budget.
- **API contract tests** for backend services consumed by the frontend/mobile apps.
- **No merge to `main` without passing CI**, including linting, type-checking, and tests.

---

## 7. Immediate Development Workflow Recommendations

1. Validate the repository structure in §1 against real module boundaries once the first 1–2 services are scaffolded — adjust rather than over-committing to it upfront.
2. Stand up CI (lint + type-check + test) before writing substantial application code, not after.
3. Establish the model-evaluation harness early, using public benchmark datasets, before any pilot-city labeled data exists — this de-risks the highest-uncertainty part of the system first.
4. Pick and lock the pilot city/ward early, since available GIS data quality there determines which rule-engine capabilities (§3.6 in TDD) are usable at launch.

---

## 8. CI/CD Recommendations

- **CI (all branches/PRs):** lint, type-check, unit tests, model-evaluation smoke tests (small/fast subset), build Docker images.
- **CD (on merge to `main`):** deploy to a staging environment automatically; production/pilot deployment gated behind manual approval, given the government-deployment context.
- Keep CI/CD portable (containerized, cloud-agnostic pipeline definitions) to match the data-sovereignty requirement of eventual deployment on NIC/MeghRaj or a state data center rather than being tied to a single commercial cloud's native CI ecosystem.

---

## 9. High-Level Implementation Roadmap (milestones)

1. **M0 — Foundations (current):** repository, documentation, standards, CI skeleton.
2. **M1 — Data & benchmark baseline:** ingestion of public benchmark datasets (LEVIR-CD, OSCD, SpaceNet), preprocessing pipeline stood up, baseline footprint-segmentation model fine-tuned and evaluated.
3. **M2 — Change detection & height estimation:** Siamese/foundation-model change-detection head; height/floor delta estimation; evaluated against benchmark + any available pilot imagery.
4. **M3 — GIS rule engine:** parcel/zoning/protected-land intersection logic against a pilot city's available layers; explicit handling of missing sanctioned-plan data.
5. **M4 — Risk scoring & case workflow:** prioritization scoring, officer verification UI, case-management backend.
6. **M5 — Reporting & transparency:** evidence-report generation, ward/city dashboards, public transparency portal.
7. **M6 — Pilot deployment:** deployment to a chosen pilot city/ward, feedback loop wired to retraining.

*This roadmap will be tracked and refined as implementation issues/tickets, not maintained solely as prose in this document.*

---

## 10. Notes on Repository/Process Improvements (recommended, not yet applied)

- Once services in §1 exist, add per-service `README.md` files documenting local setup — this document should not become a dumping ground for service-specific instructions.
- Add architecture decision records (ADRs) under `docs/` for significant reversals of decisions made in TDD.md, rather than editing TDD.md's history away.
- Revisit monorepo-vs-multi-repo once `apps/` and `services/` boundaries stabilize (see §1) — premature splitting adds coordination overhead without benefit at this stage.
