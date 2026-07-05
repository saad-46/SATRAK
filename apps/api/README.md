# SATRAK API

FastAPI application gateway for the SATRAK platform. This is the **engineering
foundation** — clean-architecture scaffolding with health/version endpoints only.
No domain logic, no domain tables.

## Architecture

Clean architecture, dependencies point inward:

```
app/
├── api/            # HTTP layer: routers, endpoints, DI (deps.py)
│   └── v1/         # versioned API surface
├── core/           # config, logging, middleware, errors, OpenAPI
├── db/             # declarative base + async session management
├── domain/         # pure domain entities (framework-agnostic)
├── repositories/   # data access (BaseRepository), no business logic
├── services/       # business logic / orchestration (BaseService)
├── schemas/        # Pydantic request/response contracts
└── main.py         # create_app() factory + lifespan
```

The dependency rule: `api → services → repositories → db`, and everything may
depend on `domain`, but `domain` depends on nothing. A lint rule (import-linter)
will enforce this as the codebase grows.

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
ruff check .
black . && isort .
mypy app
pytest
```
