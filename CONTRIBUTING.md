# Contributing to SATRAK

## Source of truth

`PRD.md`, `TDD.md`, and `ENGINEERING_BLUEPRINT.md` are authoritative and are **not
edited** during implementation. A change that revises a decision in them is
recorded as an ADR under [`docs/adr/`](docs/adr/) — see the
[ADR index](docs/README.md). Read the relevant sections before starting work.

## Local setup

Prerequisites: Node ≥ 20, pnpm ≥ 9, Python ≥ 3.12.

```bash
make install          # JS (pnpm) + Python (apps/api venv) deps
cp .env.example .env  # local config (dev defaults are safe)
make up               # optional: full stack in Docker (postgis, redis, api, web)
```

New engineers: see [docs/onboarding/](docs/onboarding/).

## Quality gates (run before pushing)

```bash
make check            # lint + types + dependency rule + tests + security
```

or individually (from `apps/api`): `ruff check .` · `ruff format .` · `mypy app` ·
`lint-imports` · `bandit -c pyproject.toml -r app` · `pip-audit` · `pytest`.

CI enforces all of these on every PR. **Ruff is the only formatter** (it replaces
black and isort — see [ADR-0004](docs/adr/0004-ruff-formatting-toolchain.md)).

## Architecture rules (enforced by `import-linter`)

- The shared kernel (`app/shared`) is pure Python — no FastAPI/SQLAlchemy/pydantic,
  no dependency on `app.api`/`app.db`/`app.core`/`app.contexts`.
- Bounded contexts (`app/contexts/<ctx>`) depend only on the shared kernel and
  never import each other's internals — they collaborate via ids + domain events.
- See [ARCHITECTURE.md](apps/api/ARCHITECTURE.md) and
  [ADR-0003](docs/adr/0003-modular-monolith-first.md) (modular monolith → services).

A PR that violates these fails the `import-linter` CI gate.

## Commits & PRs

- **Conventional Commits**, enforced by commitlint (`type(scope): subject`, lower-case
  subject). Allowed scopes are in `commitlint.config.mjs`.
- Keep commits logical and scoped; do not squash unrelated changes.
- Every commit is co-authored and signed off as configured.
- Do not commit secrets. Gitleaks + GitHub secret scanning run in CI; use `.env`
  (gitignored) locally and a secrets manager in deployed environments.
- PRs must be green (web, api, security, migrations, codeql) before merge.

## Tests

- Unit-test domain logic against the shared kernel; use `app.testing.factories`
  and `app.testing.fakes` for fixtures/fakes.
- Do not reduce coverage below the 80% gate.
