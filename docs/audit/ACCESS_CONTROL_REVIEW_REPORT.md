# Access-control sprint: local review report

Branch `claude/project-thread-w90bwr`. Local only: nothing pushed, no PR, no deployment. This report was
prepared after the owner's review decisions of 2026-10-10.

## Commits (oldest first, after `ce93ee6`)

`e8358d9` ADRs 0005-0010 and EO spec · `ef3010e` EO bounded context · `1d8627d` EO endpoints · `708ce09` EO tests ·
`a17688c` B101 fix · `f5e8e8a` decisions and audit reports · `f81059d` hash-pinned locks · `3b271cd` S1 token
validation · `7b9fe31` S2 identity schema · `be8b4c1` S3 authorization · `2b7dff0` S4 EO enforcement · `3b6a53c`
S5 revocation and audit log · `4696dea` S6 rate limiting and baseline controls · `30fa110` S7 row-level security ·
`4079440` S8 migration test, CI job, evidence. The review changes are in the commit that follows these.

## Diff summary (from `f5e8e8a` to the sprint head, before the review commit)

86 files, +11,186 / -94; `apps/api/app` +2,820; tests +3,866 (about 480 test functions in the repo).

## Changes made in this review

- Tiles default to 120/min/user. `api_ip` stays separately configurable (placeholder value).
- National-scope administrators can revoke accounts with no assignment (store method `covers_national`).
- `authorize_verification` guard for `finding:verify` (permission and jurisdiction).
- `prune_auth_sessions` (audited, privileged role) and `session_retention_days`.
- Tests assert the test engines really run as `satrak_app` / `satrak_admin` on repeated checkouts.
- From the independent bypass review: tiles are `Cache-Control: private` (were `public`); `X-Forwarded-For` is
  read across all header lines; IPv6 clients are keyed by /64; readiness no longer returns exception text;
  the Redis pool is bounded and queues instead of erroring at the cap (`redis_max_connections`).

## Remaining risks

1. **RLS is not on any data path yet (high).** EO data is in memory, so isolation depends on `access.require` and
   the endpoint filters. RLS covers only `organization` and `role_assignment`. Repository ports treat
   `jurisdiction_ids=None` as unrestricted, so a future caller that omits it fails open. Make it required
   when SQL repositories arrive and wrap request sessions in `tenant_session`.
2. **No startup check of the database role (low).** A DSN pointing at an owner or superuser role would
   silently bypass RLS; migration grants skip absent roles. Add a startup assertion before release.
3. **Proxy topology (medium, deployment).** `trusted_proxy_hops` defaults to 0 and nothing enforces that only the
   proxy reaches the API. Behind a load balancer with 0, all clients share one IP bucket.
4. **`/health/ready` is unauthenticated and unthrottled (medium).** Each call opens a connection.
5. **Tokens with neither `sid` nor `jti`** cannot be revoked individually (user-wide revocation still works).
6. **Ordinary-traffic fallback is per instance** and not distributed; there is no metric, only a log event.
7. `environment` defaults to development; staging/production guards apply only when it is set.
8. Not built: finding/case aggregates (so no verify endpoint), Redis revocation cache, refresh/offline sessions.

## Not verified (do not treat as passed)

- Next.js production build: fails in this sandbox on a Google Fonts fetch (TLS interception).
- Docker image builds: Docker unavailable.
- The new GitHub CI `integration` job: never run on GitHub.
- Lock freshness on Python 3.12: local re-resolution used 3.13; pins and hashes matched, comments differed.
- Full-stack HTTP load and abuse testing: only the limiter was load-tested; staged infrastructure is needed.

## Verified locally

ruff, format, mypy strict (208 files), bandit, import-linter (6 contracts kept), pip-audit (no known
vulnerabilities), pytest 614 passed / 1 skipped / 93% coverage with PostGIS roles and a real Redis, web lint,
typecheck and tests, migration upgrade/downgrade/drift/data-preserving tests.

## Required before release

```
cd apps/api
pip install --require-hashes -r requirements-dev.lock && pip install --no-deps -e .
ruff check . && ruff format --check . && mypy app && lint-imports && bandit -q -c pyproject.toml -r app
pip-audit --require-hashes --disable-pip -r requirements-dev.lock
# with roles from infra/db/roles.sql, SATRAK_TEST_DATABASE_URL and SATRAK_TEST_REDIS_URL set:
pytest
alembic upgrade head && alembic downgrade base && alembic check
cd ../.. && pnpm turbo run lint typecheck test build
docker build apps/api; docker build -f apps/web/Dockerfile .
```

Plus a green GitHub run of every CI job (including `integration`) and the 3.12 lock freshness step, then
owner approval to push.
