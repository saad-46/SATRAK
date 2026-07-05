# Docker Validation — Static Review & Verification Checklist

Docker is **not installed in the CI/audit environment**, so the stack could not be
brought up (`docker compose up`) during Epic 2 hardening. This document records
the **static review** (which _was_ performed) and the **runtime checklist** to
execute once Docker is available (locally or in the `docker-build` /future
integration CI job).

## Static review — findings

Reviewed: `apps/api/Dockerfile`, `apps/web/Dockerfile`,
`infra/docker-compose/docker-compose.yml`,
`infra/docker-compose/db-init/01-init-postgis.sql`.

| Area                 | Finding                                                                                                                                    | Status                   |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------ |
| **API image**        | Multi-stage (builder → slim runtime); no build toolchain in final image                                                                    | ✅ good                  |
| **API image**        | Runs as non-root `satrak` user                                                                                                             | ✅ good                  |
| **API image**        | GDAL/GEOS runtime libs present for GeoAlchemy2/Shapely                                                                                     | ✅ good                  |
| **API image**        | `curl` present → `HEALTHCHECK` can run                                                                                                     | ✅ good                  |
| **API image**        | `HEALTHCHECK` hits `/api/v1/health/live`                                                                                                   | ✅ good                  |
| **Web image (prod)** | `apps/web/Dockerfile` multi-stage, Node 20 slim, standalone output (gated on `BUILD_STANDALONE=true`)                                      | ✅ good                  |
| **Web (compose)**    | Compose runs `node:20-slim` with an inline `pnpm install`/dev server (HMR), **not** the prod Dockerfile — an intentional dev-vs-prod split | ✅ by design (noted)     |
| **Compose**          | Healthchecks on postgis, redis, api                                                                                                        | ✅ good                  |
| **Compose**          | `depends_on: condition: service_healthy` for api→(postgis,redis)                                                                           | ✅ correct startup order |
| **Compose**          | Named volumes for postgis/redis/node_modules                                                                                               | ✅ persistent + fast     |
| **Compose**          | PostGIS init SQL mounted read-only to `docker-entrypoint-initdb.d`                                                                         | ✅ good                  |
| **Compose**          | Env via `${VAR:-default}` with dev defaults                                                                                                | ✅ 12-factor             |
| **Compose**          | DB URL uses `postgresql+asyncpg://` (async driver)                                                                                         | ✅ matches app           |
| **Networking**       | Services resolve by name (`postgis`, `redis`) on the default compose network                                                               | ✅ good                  |
| **Secrets**          | Only dev-default passwords in compose; real secrets via env/secrets-manager (12-factor)                                                    | ✅ acceptable for local  |
| **Migrations**       | Not auto-run on api start (compose mounts `alembic/` but `command` is uvicorn)                                                             | ⚠️ see note              |

**Note (migrations on startup):** the compose `api` service starts uvicorn
directly and does **not** run `alembic upgrade head` first. For local dev this is
fine (run `make migrate`), and for production migrations should be a **separate,
gated deploy step** (per Blueprint Part 6, never auto-applied on deploy). No change
needed; documented so it is a conscious choice, not a surprise.

## Runtime verification checklist (run once Docker is available)

```bash
# From repo root. Uses infra/docker-compose/docker-compose.yml.
cp .env.example .env                      # if not present
make up                                   # docker compose up -d --build
```

- [ ] `docker compose ps` — all of `postgis`, `redis`, `api`, `web` are `Up` and
      `postgis`/`redis`/`api` are `healthy`.
- [ ] **PostgreSQL**: `docker compose exec postgis pg_isready -U satrak` → accepting
      connections.
- [ ] **PostGIS**: `docker compose exec postgis psql -U satrak -d satrak -c "SELECT postgis_version();"`
      returns a version (init SQL applied).
- [ ] **Redis**: `docker compose exec redis redis-cli ping` → `PONG`.
- [ ] **Migrations**: `make migrate` (or `docker compose exec api alembic upgrade head`)
      completes; `alembic current` shows `0001`.
- [ ] **Liveness**: `curl -fsS localhost:8000/api/v1/health/live` → `200`.
- [ ] **Readiness**: `curl -s localhost:8000/api/v1/health/ready` → `200` **with the
      DB up** (contrast: `503` when DB is down — the probe correctly reflects
      dependency health).
- [ ] **Metrics/info**: `curl -s localhost:8000/api/v1/system/info` and
      `/system/metrics` → `200`.
- [ ] **Web**: `curl -fsS localhost:3000` → Next.js app responds.
- [ ] **Startup order**: stop postgis, restart stack — api waits for postgis health
      before starting (no crash loop).
- [ ] **Volumes persist**: `make down` then `make up` — postgis data survives.
- [ ] **Image build (CI parity)**: the `docker-build` CI job builds both images
      without push.

## Follow-up (tracked, not blocking Epic 2)

1. Add an integration-test CI job that runs this checklist against the compose
   stack (currently only image _build_ is verified in CI).
2. Consider an `api` compose entrypoint that runs `alembic upgrade head` before
   uvicorn **in dev only**, guarded by `SATRAK_API_ENVIRONMENT=development`.
