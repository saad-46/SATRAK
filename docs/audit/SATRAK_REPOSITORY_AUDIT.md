# SATRAK Repository Audit (initial pass)

Date: 2026-10-10 · Auditor: Claude (discovery only, no feature code) · Evidence = commands actually run in this session.

## 1. Verified roots and state

| Item                               | Finding                                                                                                                                                                                                                                                                                            |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GitHub clone                       | `/home/claude/SATRAK`, detached HEAD at `main` = `ce93ee6` (2026-07-05), clean tree, remote `origin` = saad-46/SATRAK, no tags                                                                                                                                                                     |
| Authoritative local state          | `/mnt/project-files/satrak` (Saad's synced folder), **not a git repo** (no `.git`), so its history/uncommitted status cannot be verified                                                                                                                                                           |
| Sync gaps                          | Dotfiles/dirs are absent from the synced folder (`.github/`, `.gitignore`, `.env.example`, `.husky`, `.nvmrc`, `.python-version`, `apps/*/.env.example`, `.dockerignore`). `infra/k8s`, `infra/terraform`, `apps/web/public` `.gitkeep` files also absent. These are sync artifacts, not deletions |
| Duplicate docs                     | `SATRAK_PRD.md`=`PRD.md`, `SATRAK_Technical_Design_Document.md`=`TDD.md`, `SATRAK_Implementation_Blueprint.md`=`ENGINEERING_BLUEPRINT.md` (identical md5). The three top-level docs are byte-identical to GitHub                                                                                   |
| Divergence (local ahead of GitHub) | Local adds: `contexts/earth_observation` (5,125 LOC, ~188 py files total in app), `api/v1/endpoints/earth_observation/*`, `packages/py-geo                                                                                                                                                         | py-imagery | py-raster`(stubs, 251 LOC), ADRs 0005–0010,`docs/epic-3-earth-observation-platform-spec.md`, 2 import-linter contracts, EO tests (+245 tests), `main.py`/`router.py`wiring. Local drops`contexts/satellite`and`services/satellite`(renamed per ADR-0005/0010;`services/earth_observation` is present). GitHub-only: nothing of substance beyond the dotfiles above |
| Not found                          | No AGENTS.md / CLAUDE.md. README/CONTRIBUTING/RELEASE exist                                                                                                                                                                                                                                        |

## 2. Stack and map

Monorepo (pnpm 9.15.9 + Turborepo; Python 3.12 per `.python-version`). `apps/api` FastAPI + SQLAlchemy 2 async + Alembic + GeoAlchemy2 + structlog; `apps/web` Next.js 15/React 19/Tailwind 4/TanStack Query/Zustand; `apps/ai` placeholder; `packages/{config,sdk,shared,ui}` TS (placeholders), `packages/py-*` Python stubs; `services/*` README-only extraction addresses; `infra/docker-compose` (postgis, redis, api, web); CI in `.github/workflows` (ci.yml, codeql.yml).
API layering: `api -> contexts -> shared` (shared kernel stdlib-only). Contexts: `core`, `identity`, `organization` (domain models only), `earth_observation` (local only), the rest empty reserved boundaries.

## 3. Module status

| Module                                                                                     | Status                                                                                                                                            | Evidence                                       |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Foundation (config, logging, middleware, RFC 9457 errors, metrics, health, pagination)     | Implemented, verified                                                                                                                             | 93 tests pass on GitHub main                   |
| Shared kernel (entities, UoW, ports, VOs)                                                  | Implemented (in-memory only)                                                                                                                      | tests                                          |
| identity / organization / core                                                             | Domain models only. **No login, JWT, MFA, RBAC, persistence, endpoints**                                                                          | `app/contexts/identity/domain` = 3 small files |
| earth_observation                                                                          | Domain, application, providers (Sentinel-2 search/normalize only), pure-Python raster engine, tile/keying, jobs, REST read API, **all in-memory** | 338 tests pass locally                         |
| Property, GIS, AI, Compliance, Inspection, Drone, Reports, Notifications, Analytics, Admin | Reserved empty packages                                                                                                                           |                                                |
| Web                                                                                        | Shell: `(app)`, `(public)` route groups, error/loading pages, 6 unit tests. No auth, no map, no features                                          |                                                |

## 4. Baseline results (this session)

Environment: Python 3.12.3 venv, deps resolved fresh from `pyproject` (fastapi 0.143, pydantic 2.14, sqlalchemy 2.1.4, ruff 0.17, mypy 2.4). Note: no lockfile for Python, so versions float.

| Check                         | GitHub main                        | Synced local tree (copied to scratch, original untouched)            |
| ----------------------------- | ---------------------------------- | -------------------------------------------------------------------- |
| ruff check / format           | pass / 124 files formatted         | pass / 260 files formatted                                           |
| mypy strict                   | pass (100 files)                   | pass (188 files)                                                     |
| import-linter                 | 3/3 kept                           | 5/5 kept                                                             |
| pytest                        | **93 passed**, cov 86.1%           | **338 passed**, cov 94.7%                                            |
| bandit (CI uses it as a gate) | exit 0                             | **exit 1: 7 LOW B101 (`assert`) in EO code** → would fail CI on push |
| pip-audit                     | no known vulns (done on main only) | not run                                                              |
| Web lint / typecheck / vitest | pass / pass / 6 pass               | not run (same code)                                                  |

Not run: web build, Playwright e2e, Docker builds, alembic against PostGIS (needs services / larger cost; CI covers these on main), gitleaks, CodeQL, pip-audit on local tree. Before running web checks, `pnpm install` triggered husky `prepare` which may have set a git hooks path in the container clone; the container clone has no work to lose, but a check/reset was blocked by the sandbox classifier so I did not touch it.

## 5. Findings (ranked)

**Critical / High**

1. **No authentication or authorization exists anywhere**, yet EO endpoints (`/api/v1/eo/*`, including signed-URL-adjacent tile reads) are mounted publicly. Blueprint Epic 1 (P0, "blocks everything") is not done; the project's own "Epic 1" label meant the engineering foundation. PRD FR-16.1, FR-18.x, NFR-18.x unmet. Mitigation today: nothing is deployed, data is in-memory.
2. **EO persistence is in-memory only.** Alembic has only `0001_enable_postgis`; no EO tables (`satellite_scenes`, `tile_index`, `aoi_definitions`…) or migration. Restarting the API loses all scenes. Real storage (S3/MinIO), Celery, httpx download and rasterio/GDAL are not in `pyproject` dependencies; raster engine is pure-Python float arrays, not COG. So "tiles served from COG range reads" (ADR-0006) is not yet real.
3. **Local work is unpushed and unversioned** (synced folder has no `.git`). One lost folder loses ~5k LOC + 6 ADRs. Needs commit on a feature branch (requires your approval to push).
4. **Local tree would fail CI**: bandit B101 asserts (7 LOW) — fix is small (replace asserts with explicit checks) but not done in this audit pass.

**Medium** 5. CORS: `allow_credentials=True` with `allow_methods/headers=["*"]`; origins are config-driven (safe default `localhost:3000`) but production must pin them. 6. Tile endpoint hashes full tile per request and sets `Cache-Control: public` with no authz; `?version=` pin unvalidated length; no rate limiting anywhere (PRD FR-16.2, FR-9.6). 7. Audit trail: `AuditSink` port exists but no durable/hash-chained implementation; EO emits no audit events to a real sink (PRD FR-20.x, NFR-20.4). 8. Multi-tenancy (PRD AP1, schema-per-tenant; Blueprint Part 10 #7 asks for a jurisdiction ADR): no `tenant_id`/jurisdiction concept in code. EO models carry none. 9. Python deps unlocked (no `uv.lock`/constraints); only `pip-audit` at CI time protects against drift. 10. `docker-compose` dev defaults include a dev DB password (`satrak_dev_password`) — acceptable for dev only; prod secret injection not designed yet.

**Low / hygiene** 11. Stale GitHub README/structure refs `services/satellite`; `docs/README.md` ADR table on GitHub lacks ADR-0005..0010. 12. 10 open Dependabot PRs on GitHub; #11 (TS7/ESLint10/Next16) fails CI (from project memory, not re-verified here). 13. `commitlint.config.mjs` scope list differs (local adds `earth-observation`).

## 6. Deployment readiness

Not deployable beyond dev. Present: multi-stage non-root API Dockerfile with HEALTHCHECK, `/health/live` + readiness, compose stack, CI with migration round-trip, security scans. Absent: k8s/terraform (placeholders), secrets manager integration, object storage, worker/beat processes, observability backends (metrics endpoint exists), backup/DR, rollback runbook, any staging.

---

Update 2026-10-10: this report is the pre-transfer baseline. Since then the EO work was transferred to a local feature branch in the canonical repository (six local commits, not pushed) and the seven B101 findings were fixed. The ranked findings above (no authn/authz, no tenancy, in-memory EO, unlocked deps) still stand.
