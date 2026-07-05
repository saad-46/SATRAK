# Engineer Onboarding

Welcome to SATRAK. This gets you from clone to a running, tested stack.

## 1. Read first (30–60 min)

- [PRD.md](../../PRD.md) §1 — what SATRAK is and who uses it.
- [TDD.md](../../TDD.md) §1–3 — architecture and the microservice map.
- [ENGINEERING_BLUEPRINT.md](../../ENGINEERING_BLUEPRINT.md) Part 1, 2, 7 — repo
  shape, modules, epic order.
- [ADR index](../README.md) — especially ADR-0002 (domain platform) and ADR-0003
  (modular monolith → services).

## 2. Tooling

| Tool   | Version | Why                         |
| ------ | ------- | --------------------------- |
| Node   | ≥ 20    | frontend + tooling          |
| pnpm   | ≥ 9     | JS workspace manager        |
| Python | ≥ 3.12  | backend (`apps/api`)        |
| Docker | latest  | local stack (postgis/redis) |

## 3. Setup

```bash
git clone <repo> && cd satrak
make install        # JS + Python deps
cp .env.example .env
make check          # confirm your env passes every gate
make up             # start postgis + redis + api + web in Docker
make migrate        # apply DB migrations
```

Verify:

- API liveness: http://localhost:8000/api/v1/health/live → `200`
- API docs: http://localhost:8000/docs
- Web: http://localhost:3000

## 4. Where code lives

```
apps/api/app/shared/       # shared kernel (pure Python) — start here
apps/api/app/contexts/     # bounded contexts (core, identity, organization, …)
apps/api/app/{api,core,db} # HTTP boundary, cross-cutting infra, persistence
apps/web/                  # Next.js frontend
services/<ctx>/            # RESERVED future homes (see ADR-0003) — empty today
packages/                  # shared TS packages
infra/                     # docker-compose, k8s, terraform
docs/                      # ADRs, this guide, Docker validation, release
```

## 5. Your first change

1. Branch from `main`.
2. Make the change; add/adjust tests.
3. `make check` until green (mirrors CI).
4. Conventional-commit; open a PR; ensure all CI jobs pass.

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full workflow and the
architecture rules the CI `import-linter` gate enforces.
