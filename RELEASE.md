# Release Guide

SATRAK uses annotated Git tags for releases. Pre-1.0 the platform ships
`vMAJOR.MINOR.PATCH` with a stage suffix (`-alpha`, `-beta`, `-rc.N`).

## Release Candidate checklist

Run the automated portion first:

```bash
bash scripts/verify-release.sh    # or: make check (from repo root)
```

Every box below is either verified by that script (**auto**) or must be checked
manually (**manual**).

### Engineering gates (auto)

- [ ] **Lint** — `ruff check` clean
- [ ] **Format** — `ruff format --check` clean
- [ ] **Types** — `mypy app` strict, 0 errors
- [ ] **Dependency rule** — `import-linter` contracts kept (0 broken)
- [ ] **Tests + coverage** — `pytest` passes, coverage ≥ 80%
- [ ] **SAST** — `bandit` clean
- [ ] **Dependency CVEs** — `pip-audit` clean
- [ ] **Git** — working tree clean, on the release commit

### Verified in CI (auto, on GitHub)

- [ ] Web: lint · typecheck · test · build
- [ ] CodeQL (python + javascript-typescript) — no new alerts
- [ ] Gitleaks — no secrets
- [ ] Migrations — `alembic upgrade head` + `downgrade base` against PostGIS
- [ ] Docker images build (api + web)

### Manual / infra (see linked docs)

- [ ] **Docker stack** — [docs/DOCKER_VALIDATION.md](docs/DOCKER_VALIDATION.md)
      checklist run once against a real Docker host
- [ ] **Docs** — README / ARCHITECTURE / ADRs reflect the released state
- [ ] **ADRs** — any architecture change in this release has an ADR
- [ ] **Source-of-truth** — no unratified divergence from PRD / TDD / Blueprint
- [ ] **CHANGELOG / release notes** drafted

## Cutting a release

```bash
# 1. Ensure main is green and the checklist passes.
bash scripts/verify-release.sh

# 2. Bump versions (apps/api/pyproject.toml [project].version, package.json).
# 3. Tag (annotated) and push the tag.
git tag -a v0.2.0-alpha -m "SATRAK v0.2.0-alpha — Epic 2 core domain platform"
git push origin v0.2.0-alpha
```

## Versioning policy

- **`v0.1.x`** — Epic 1 (engineering foundation).
- **`v0.2.0-alpha`** — Epic 2 (core domain platform), once this checklist passes.
- Feature epics bump the minor version; breaking foundation changes are recorded
  as ADRs and bump appropriately pre-1.0.
