# SATRAK

**AI-Powered Government Urban Compliance Intelligence Platform**

SATRAK monitors cities using satellite imagery and GIS data to automatically detect unauthorized construction — additional unsanctioned floors, boundary/setback violations, and encroachment on public or protected land — and turns it into a ranked, evidence-backed queue for municipal enforcement officers.

SATRAK is a **decision-support system**, not an automated enforcement system: it detects and prioritizes leads; a human officer always verifies before any action is taken. See [PRD.md](PRD.md) for the full product rationale.

> **Status:** Epic 1 — engineering foundation. The repository contains the production-grade skeleton (monorepo, backend, frontend, database, Docker, CI). No domain/AI/GIS logic is implemented yet; those arrive in later epics (see [ENGINEERING_BLUEPRINT.md](ENGINEERING_BLUEPRINT.md)).

---

## Architecture overview

Product pipeline (target system):

```
Satellite Imagery → Ingestion → Preprocessing → Building Footprint Extraction
        → Height/Floor Estimation + Multi-temporal Change Detection
        → GIS Overlay & Rule Engine (parcel / zoning / protected-land / sanctioned-plan)
        → Risk Scoring & Prioritization → Human Verification Workflow
        → Case Management & Reporting → Notifications & Transparency Portal
                    ↑___________ MLOps / Feedback Loop ___________↓
```

Foundation as built today:

```
apps/web (Next.js 15) ──HTTP──▶ apps/api (FastAPI)
                                   ├── PostgreSQL + PostGIS   (spatial system of record)
                                   └── Redis                  (cache / queues)
```

The API follows clean architecture (`api → services → repositories → db`, all may depend on `domain`, `domain` depends on nothing). Full module-by-module design is in [TDD.md](TDD.md) and [ENGINEERING_BLUEPRINT.md](ENGINEERING_BLUEPRINT.md).

## Technology stack

| Layer          | Technology                                                                                                          |
| -------------- | ------------------------------------------------------------------------------------------------------------------- |
| Frontend       | Next.js 15 · React 19 · TypeScript · Tailwind CSS v4 · shadcn/ui · TanStack Query · Zustand · React Hook Form · Zod |
| Backend        | FastAPI · Python 3.12 · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · structlog                                    |
| Database       | PostgreSQL + PostGIS                                                                                                |
| Cache / queues | Redis                                                                                                               |
| Infrastructure | Docker · Docker Compose · Kubernetes (future) · GitHub Actions                                                      |
| Tooling        | pnpm workspaces · Turborepo · Ruff · Black · isort · ESLint · Prettier · Husky · lint-staged                        |
| Testing        | Pytest · Vitest · Playwright                                                                                        |

Full rationale for each choice is in [TDD.md](TDD.md) and [ENGINEERING_BLUEPRINT.md](ENGINEERING_BLUEPRINT.md).

## Repository structure

```
satrak/
├── apps/
│   ├── web/                 # Next.js 15 web app (officer/admin shell) — foundation
│   ├── api/                 # FastAPI gateway (clean architecture) — foundation
│   └── ai/                  # AI/ML workspace (placeholder — reserved boundary)
├── packages/
│   ├── ui/                  # shared design-system library (placeholder)
│   ├── sdk/                 # generated API client (placeholder)
│   ├── shared/              # shared TS types/constants
│   └── config/              # shared eslint/tsconfig presets
├── services/                # Python bounded-context placeholders (reserved boundaries)
│   ├── satellite/  gis/  drone/  notifications/  compliance/
├── infra/
│   ├── docker-compose/      # local dev stack + db-init
│   ├── k8s/                 # (future) manifests
│   └── terraform/           # (future) IaC
├── docs/                    # docs index + ADRs
├── scripts/                 # dev bootstrap + ops scripts
├── .github/workflows/       # CI (lint · typecheck · test · build · docker)
├── PRD.md · TDD.md · ENGINEERING_BLUEPRINT.md   # source-of-truth docs
├── pnpm-workspace.yaml · turbo.json · Makefile
└── tsconfig.base.json · .prettierrc.json · commitlint.config.mjs
```

## Prerequisites

- **Node.js** ≥ 20 and **pnpm** ≥ 9 (`npm install -g pnpm` or `corepack enable`)
- **Python** 3.12
- **Docker** + Docker Compose (for the local datastore stack)

## Getting started

```bash
# 1. Clone, then bootstrap everything (env files + JS + Python deps)
./scripts/dev-setup.sh              # or: make install

# 2. Start datastores (PostGIS + Redis)
make up                             # docker compose up -d (full stack)
#   …or just infra, and run apps natively for fastest hot-reload:
#   docker compose -f infra/docker-compose/docker-compose.yml up -d postgis redis

# 3. Apply database migrations (enables PostGIS)
make migrate

# 4. Run the apps
make dev                            # web + api via turbo
```

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs
- API liveness: http://localhost:8000/api/v1/health/live

Per-app details: [apps/web/README.md](apps/web/README.md), [apps/api/README.md](apps/api/README.md).

## Development commands

All commands run from the repo root via the `Makefile` (cross-language) or pnpm/turbo:

| Command                              | Action                                       |
| ------------------------------------ | -------------------------------------------- |
| `make install`                       | Install JS + Python dependencies             |
| `make dev`                           | Run web + api dev servers (Turborepo)        |
| `make up` / `make down`              | Start / stop the Docker stack                |
| `make migrate`                       | Apply Alembic migrations to head             |
| `make lint`                          | Lint everything (ESLint + Ruff)              |
| `make format`                        | Format everything (Prettier + Black + isort) |
| `make typecheck`                     | Type-check everything (tsc + mypy)           |
| `make test`                          | Run all tests (Vitest + Pytest)              |
| `pnpm --filter @satrak/web <script>` | Target the web app (dev/build/test/test:e2e) |
| `pytest` (in `apps/api`)             | Run backend tests                            |

## Docker

```bash
# Full local stack (postgis, redis, api with hot-reload, web with HMR)
docker compose -f infra/docker-compose/docker-compose.yml up -d --build

# Tail logs / tear down
make logs
make down
```

Production images are built from each app's own multi-stage `Dockerfile`
(`apps/api/Dockerfile`, `apps/web/Dockerfile`); CI verifies both build on every PR.

## Environment variables

Configuration is validated at startup (fails fast on misconfiguration).

| Scope        | File                                        | Notes                                              |
| ------------ | ------------------------------------------- | -------------------------------------------------- |
| Docker stack | `.env` (from `.env.example`)                | Postgres/Redis creds, host ports                   |
| API          | `apps/api/.env` (from `.env.example`)       | `SATRAK_API_*`, validated by `pydantic-settings`   |
| Web          | `apps/web/.env.local` (from `.env.example`) | `NEXT_PUBLIC_*`, validated by `@t3-oss/env-nextjs` |

Secrets are never committed. In deployed environments they are injected from a
secrets manager as env vars; `.env*` files are for local development only.

## Conventions

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) enforced by commitlint (see `commitlint.config.mjs`).
- **Branching:** trunk-based; short-lived `feature/*` and `fix/*` branches merged into `main` via PR.
- **Quality gates:** Husky pre-commit runs lint-staged (Prettier/ESLint/Ruff/Black/isort); CI runs lint + typecheck + tests + build before merge.

## Documentation

- [PRD.md](PRD.md) — Product Requirements Document
- [TDD.md](TDD.md) — Technical Design Document
- [ENGINEERING_BLUEPRINT.md](ENGINEERING_BLUEPRINT.md) — Engineering blueprint, epics, roadmap
- [docs/](docs/) — documentation index and Architecture Decision Records

## License

Licensed under the [MIT License](LICENSE).
