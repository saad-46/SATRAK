# SATRAK API

FastAPI application gateway for the SATRAK platform. As of **Epic 2** this hosts
the reusable **core domain platform** — the shared kernel and bounded-context
domain models every future module builds on. No feature workflows or feature
tables yet.

## Architecture

Clean Architecture + DDD, dependencies point inward. Full detail (domain model,
dependency rules, layer responsibilities, extension points) is in
[ARCHITECTURE.md](ARCHITECTURE.md).

```
app/
├── shared/         # SHARED KERNEL (pure Python): domain base, value objects,
│                   #   events, persistence + service abstractions, pagination
├── contexts/       # BOUNDED CONTEXTS: core, identity, organization (+ reserved)
├── db/             # declarative Base + ORM mixins + async session management
├── core/           # config, logging, middleware, errors, problem details, metrics
├── api/            # HTTP layer: routers, deps, response schemas, v1 endpoints
├── schemas/        # Pydantic contracts for the meta/health surface
├── testing/        # reusable factories + fakes (shipped for every context's tests)
└── main.py         # create_app() factory + lifespan
```

The dependency rule: `api`/`db` → `contexts` → `shared`; the shared kernel depends
on nothing else in `app`. A lint rule (import-linter) will enforce this as the
codebase grows.

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

- Docs: http://localhost:8000/docs
- Liveness: http://localhost:8000/api/v1/health/live
- Version: http://localhost:8000/api/v1/meta/version

## Database migrations

```bash
alembic upgrade head              # apply (starts by enabling PostGIS)
alembic revision --autogenerate -m "add X table"
```

## Quality

```bash
ruff check .          # lint
ruff format .         # format (replaces black + isort — see ADR-0004)
mypy app              # strict type check
bandit -c pyproject.toml -r app   # SAST
pip-audit             # dependency CVE audit
lint-imports          # enforce the dependency rule (import-linter)
pytest                # tests + coverage gate
```

From the repo root, `make check` runs the whole gate (mirrors CI).
