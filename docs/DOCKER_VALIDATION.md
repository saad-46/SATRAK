# Docker Validation — Static Review & Verification Checklist

The audit sandbox has the Docker client but no Docker daemon, so the compose stack (`docker compose up`)
has never been brought up there. This document records the **static review**, what the CI
**`container-smoke`** job now runs against the built images, and the **runtime checklist** for the compose
stack, which is still not executed anywhere.

## What CI runs against the images (`container-smoke` job)

Everything uses CI-only synthetic configuration and disposable PostGIS and Redis service containers; no
production credential, host or IdP is involved. The job passed on `e34c3b7` (all steps green).

| Check                                                                                                                                                          | Where it is asserted                                           |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| API image builds and `alembic upgrade head` runs inside it as `satrak_migrator`                                                                                | steps "Build API image", "Migrate using the API image"         |
| API starts with `SATRAK_API_ENVIRONMENT=production`, the application database role `satrak_app`, Redis, an unreachable issuer (`idp.invalid`)                  | step "API starts with production settings"                     |
| `GET /api/v1/health/live` and `/health/ready` return 200                                                                                                       | same step                                                      |
| Entrypoint user is `satrak`, uid is not 0, and no process in the container runs as root                                                                        | step "API process is not root"                                 |
| The image `HEALTHCHECK` reaches `healthy`                                                                                                                      | step "Image HEALTHCHECK reports healthy"                       |
| Schema-owner role as the application role exits non-zero (`unsafe database role`); production without a database exits non-zero (`database_url is required`)   | step "Unsafe configuration is refused"                         |
| Web image builds (repository-root context, root `.dockerignore`), serves `/` with HTTP 200 and the text `SATRAK`; user is `nextjs`, uid not 0, no root process | steps "Build Web image", "Web starts as non-root and serves /" |

**Startup does not need the IdP.** Established from code (`build_auth_runtime` only creates an HTTP client;
keys are fetched lazily on the first token) and by test: the same configuration with an unreachable issuer
started and answered `live` and `ready` with 200, both in a local non-container run and in the CI job.

**Not proven by this job:** token validation (no IdP exists in CI), IdP-side revocation (R4), network controls
(R5, R6), tenant isolation of a real deployment, or behaviour under load. A passing smoke job says the images
start under production settings and refuse two unsafe configurations; it does not make SATRAK production-ready.
`NEXT_PUBLIC_*` values are build-time; the Web image is built with `SKIP_ENV_VALIDATION=true`, so the smoke
test does not exercise production URLs.

Local, non-container cross-checks run before the job existed: the API under the same environment (valid
configuration answered `live`/`ready` 200; owner role exited with code 3; empty database URL exited 1) and the
Next.js standalone server (`node apps/web/server.js` answered `/` with 200 containing `SATRAK`). These were not
run inside images.

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
      without push; the `container-smoke` job also starts them (see above).

## Follow-up (tracked, not blocking Epic 2)

1. Add an integration-test CI job that runs this checklist against the compose
   stack (CI now starts the two images with service containers, but not the compose stack).
2. Consider an `api` compose entrypoint that runs `alembic upgrade head` before
   uvicorn **in dev only**, guarded by `SATRAK_API_ENVIRONMENT=development`.
