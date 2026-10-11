# SATRAK — Access-Control Foundation Sprint (specification)

Approved by the owner 2026-10-10, scope as below. One story at a time; focused checks per story;
full verification at the end; stop at the checkpoint. No push, PR or deploy. Governing records:
ADR-0011 (tenancy), ADR-0012 (CRS), ADR-0013 (authentication and revocation), ADR-0014 (officer verification).

## Dependency locking (decided approach)

Existing tooling (verified): `apps/api/pyproject.toml` (hatchling), CI/Docker/Makefile all use `pip`; no Python lock exists;
JS uses a committed `pnpm-lock.yaml`. `pip lock` (PEP 751) is experimental in the installed pip and failed on a
local-project input when tried, so it is not used.

Chosen: **pip-tools `pip-compile --generate-hashes`** from `pyproject.toml`, which stays inside the pip ecosystem:

- `apps/api/requirements.lock` (runtime) and `apps/api/requirements-dev.lock` (runtime + `dev` extra), full transitive graph with hashes, header recording the exact command and Python version.
- Install with `pip install --require-hashes -r requirements.lock` (Docker builder) and the dev lock (CI, Makefile). The project itself is then installed with `--no-deps`.
- CI check: regenerate to a temp file and fail if it differs from the committed lock; `pip-audit -r requirements.lock`.
- Scope/limits (documented in `apps/api/README.md`): resolved for CPython 3.12 on Linux x86_64 (the CI and Docker target); other platforms need their own regeneration. Update procedure: change `pyproject.toml`, regenerate, review the diff and licenses, run `pip-audit`.
- Changing CI/Docker to use the lock is part of Story 0; no other new tooling is introduced. If the owner prefers `uv`, only the generation command changes.

## Dependency policy

Add a dependency only in the story that needs it, with: purpose, version range, transitive additions (from the lock diff), license, platform wheels, `pip-audit` result. Planned: Story 1 `PyJWT[crypto]` (MIT; pulls `cryptography`; wheels for linux/macOS/Windows); `httpx` moves from dev to runtime for JWKS/discovery fetch (BSD-3). Rate limiting uses the existing `redis` dependency. Not in this sprint: rasterio/GDAL, S3 client, Celery (added later only with native-library compatibility, license and CVE review).

## Stories

0. **Lock foundation** — generate and verify the locks, update Docker/CI/Makefile/README, add the CI freshness check. (Prerequisite; touches no behavior.)
1. **Configuration and token validation** (ADR-0013 B–C) — settings, JWKS/discovery client with cache and bounded refresh, `get_current_principal`, RFC 9457 401s, explicit allow-list of public routes (health, docs only).
2. **Identity, organization and jurisdiction persistence** — first real migration(s): `jurisdiction` (hierarchy), `organization`, `user_account` (unique issuer+subject), `role`, `permission`, `role_assignment` (user, role, jurisdiction, valid_from/to), session and revocation tables; audit envelope; non-null `jurisdiction_id` on tenant-owned tables (ADR-0011).
3. **Authorization** — `RbacService.check(principal, action, jurisdiction)`, `require_permission`, hierarchy-aware jurisdiction scoping, time-bound cross-jurisdiction grants, default deny, `finding:verify` defined in the permission catalogue (ADR-0014 prerequisite).
4. **EO endpoint enforcement** — Scene/AOI carry non-null `jurisdiction_id`; list/search/tile/timeline filtered and checked per principal; names proposed: `eo:scene:read`, `eo:aoi:read`, `eo:aoi:write`, `eo:tile:read`, `eo:process:submit` (to be confirmed at story start).
5. **Revocation and durable audit** — implement ADR-0013 E; append-only `audit_event` (app role has no UPDATE/DELETE), `jurisdiction_id`, actor, action, resource, outcome, request id, `seq`, `prev_hash`; events `user.logged_in`, `user.login_failed`, `access.denied`, `session.revoked`; denials/logins fail closed if the audit write fails; chain verifier.
6. **Baseline controls and rate limiting** — below; CORS fix (reject `*` when credentials are enabled), security headers, request-size limits, no secrets or tokens in logs.
7. **Row-level security** (ADR-0011) — policies on every tenant-owned table, FORCE RLS, non-owner non-bypass app role, transaction-scoped `SET LOCAL`, pool-leak tests, CI policy-coverage check.
8. **Migration and PostGIS verification** — upgrade head / downgrade base on `postgis/postgis:16-3.4`, autogenerate drift check, data-preserving test.

## Rate limiting (owner-approved initial defaults; configurable per environment and route)

| Operation                                              | Initial limit                                          |
| ------------------------------------------------------ | ------------------------------------------------------ |
| Login initiation and other sensitive auth entry points | 10 req/min per IP                                      |
| Invalid-token / repeated authentication failures       | 10 failures/min per IP, progressive throttling         |
| Ordinary authenticated API requests                    | 120 req/min per user                                   |
| Earth Observation search                               | 30 req/min per user                                    |
| Expensive imagery/raster/analytical submissions        | 5 req/min and 30 req/hour per user                     |
| Administrative or bulk operations                      | 10 req/min per user, tighter per endpoint where needed |

These are starting values, to be tuned from measured traffic and abuse testing, not capacity guarantees.

Design requirements: limits apply at both user and IP level; state is shared across instances (Redis; this is a
documented runtime dependency already present in the stack); atomic increment via a single Redis script
(sliding-window or token bucket) so concurrent requests cannot overshoot; 429 with `Retry-After` and
rate-limit headers; unauthenticated callers are keyed by IP so rotating a claimed user id gains nothing;
client IP is taken from the socket peer unless the peer is in a configured trusted-proxy list, in which case the
configured forwarded header is used; client-supplied identity/jurisdiction headers are ignored.
Failure handling: when Redis is unavailable, auth entry points and expensive operations **fail closed**;
ordinary reads fall back to a strict per-process limiter and emit an alert. This failure policy is a proposal
for the owner to confirm (see unresolved decisions). An in-memory-only limiter is not accepted.

## Officer-verification gate (ADR-0014) — sprint treatment

Prerequisites delivered here: authenticated officers, jurisdiction-scoped permissions including `finding:verify`,
audit events, append-only history pattern. The gate (rejecting release of unverified findings by API and by
jobs, DB-level guard, provenance in court packages) is implemented and tested in the first epic that creates
findings or cases, because no AI-candidate aggregate exists in the code today. Carry-forward acceptance tests are
recorded in that epic's spec; they are not claimed by this sprint.

## Acceptance tests (the original 12, extended)

| #   | Criterion                                                                                                                                                                         | Verification                                                                                                                                                                                                                                            |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A1  | Missing/malformed/expired/wrong-`iss`/wrong-`aud`/wrong-algorithm (`none`, HS256 with the public key as secret)/unknown-`kid`/bad-signature tokens → 401 on every protected route | Parametrized over the OpenAPI route inventory; inventory test fails if a route is unclassified                                                                                                                                                          |
| A2  | Authenticated without permission → 403, no data in the body                                                                                                                       | Per-route negative tests                                                                                                                                                                                                                                |
| A3  | Cross-jurisdiction access → 403 (or uniform 404 for object ids, decided in Story 4); lists return only permitted jurisdictions                                                    | Two jurisdictions × two users; parent/child; sibling; expired grant                                                                                                                                                                                     |
| A4  | Tile endpoint enforces the same checks                                                                                                                                            | Other-jurisdiction token on a tile URL → 403                                                                                                                                                                                                            |
| A5  | Login success/failure, access denied, session revoke produce durable audit rows                                                                                                   | Row exists after commit and in a fresh session; audit failure → request fails closed                                                                                                                                                                    |
| A6  | Audit immutability                                                                                                                                                                | App role cannot UPDATE/DELETE `audit_event` (run against Postgres); chain verifier detects tampering                                                                                                                                                    |
| A7  | **Revocation within 60 s**                                                                                                                                                        | Revoked user/session rejected on the next request with warm cache; second instance also rejects; Redis down does not admit a revoked principal; measured propagation recorded                                                                           |
| A8  | Bypass attempts                                                                                                                                                                   | Trailing slash, method override, HEAD/OPTIONS, prefix variants, mounted sub-apps, static/tile paths, spoofed `X-Forwarded-*`/tenant/identity headers ignored; raw SQL as the app role cannot read other jurisdictions; app never uses owner/bypass role |
| A9  | Migrations                                                                                                                                                                        | `upgrade head` → `downgrade base` on PostGIS 16-3.4; autogenerate drift empty; data-preserving test                                                                                                                                                     |
| A10 | Quality gates                                                                                                                                                                     | ruff, format, mypy strict, bandit, import-linter, pip-audit, pytest ≥ 80 % coverage, web lint/typecheck/test/build, docker build                                                                                                                        |
| A11 | Config safety                                                                                                                                                                     | App refuses to start with auth enabled and issuer/audience unset; locks verified fresh                                                                                                                                                                  |
| A12 | Rate limiting                                                                                                                                                                     | Limits above enforced per route; N+1th → 429 with `Retry-After`; shared across two app instances; concurrency test shows no overshoot; Redis-down behavior as specified; changing a claimed user id as an anonymous caller does not reset the counter   |
| A13 | RLS and pools                                                                                                                                                                     | No context leakage across requests (sequential, concurrent, after exception/rollback); every `jurisdiction_id` table has RLS (CI check); workers and admin roles follow the documented rules                                                            |
| A14 | Signing-key rotation                                                                                                                                                              | New `kid` accepted after one bounded refresh; retired key rejected; refresh-storm protection test                                                                                                                                                       |

## Unresolved security decisions

1. Redis-unavailable behavior for the rate limiter (proposed above).
2. Whether the target IdP supplies `sid`/`jti`, its issuer/audience, and any role/jurisdiction claims; JIT-provisioned users start with no permissions.
3. Revocation cache TTL (proposed 15 s) and a 404-versus-403 policy for foreign object ids.
4. Refresh-token and offline-mobile session handling (out of scope; N14).
5. Classification of tenant-less PRD tables and cross-tenant analytics (ADR-0011 follow-ups).
6. Whether `finding:verify` is held per jurisdiction or by role only.
