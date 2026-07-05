# infra/

Infrastructure-as-code and container definitions for SATRAK.

```
infra/
├── docker-compose/     # local dev stack (postgis, redis, api, web) + db-init
├── docker/             # (future) shared/base Dockerfiles not colocated with an app
├── k8s/                # (future) Kustomize/Helm overlays per environment
└── terraform/          # (future) cloud resource IaC (modules + environments)
```

Per-app production Dockerfiles live with their app (`apps/api/Dockerfile`,
`apps/web/Dockerfile`); this directory holds cross-cutting orchestration.

## Local stack

```bash
cp .env.example .env          # from repo root
docker compose -f infra/docker-compose/docker-compose.yml up -d --build
# or: make up
```

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs
- API liveness: http://localhost:8000/api/v1/health/live
- Postgres: localhost:5432 (postgis/postgis:16-3.4)
- Redis: localhost:6379

The common local workflow is **infra in Docker, apps native** for the fastest
hot-reload: `docker compose ... up -d postgis redis` then `make dev`.
