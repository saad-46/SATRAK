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

## Dependency locking

`requirements.lock` (runtime) and `requirements-dev.lock` (runtime + `dev` extra) are full, hash-pinned
resolutions of `pyproject.toml`, generated with pip-tools (`pip-compile --generate-hashes`). They are
resolved for **CPython 3.12 on Linux x86_64**, the CI and Docker target. CI installs with
`--require-hashes`, fails if the committed locks differ from a fresh resolution, and audits the locked
graph with `pip-audit`. On other platforms the locks may omit platform-specific packages; use
`pip install -e ".[dev]"` there for local work, and regenerate on Linux before committing.

Regenerate after changing `pyproject.toml` (review the diff, licenses and `pip-audit`):

```bash
pip install pip-tools==7.6.2
pip-compile --generate-hashes --strip-extras --output-file=requirements.lock pyproject.toml
pip-compile --extra dev --generate-hashes --strip-extras --output-file=requirements-dev.lock pyproject.toml
```

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install --require-hashes -r requirements-dev.lock
pip install --no-deps -e .
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
