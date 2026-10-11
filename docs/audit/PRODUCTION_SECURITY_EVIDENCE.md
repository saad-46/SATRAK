# Production security evidence still required

Status as of 2026-10-10. This lists what must be demonstrated before SATRAK is called production-ready.
Nothing below has been demonstrated; no IdP behaviour is assumed.

## 1. Revocation within one minute (NFR-18.2)

What the code does: revocation made through SATRAK (logout, `POST /admin/users/{id}/revoke-sessions`,
`/admin/sessions/revoke`) is read from PostgreSQL on every request, so it applies on the next request on
every instance. Tokens must carry `sid` or `jti` and live at most `auth.max_token_lifetime_seconds` (900).
Revocation done **only at the IdP** is unknown to SATRAK; the bound there is the token lifetime.

Evidence to collect (staging, real IdP):

1. IdP facts, from its documentation and a captured token (claims only, no secrets): which of `sid`/`jti`
   it emits; its access-token lifetime; whether it supports back-channel logout or introspection, and
   whether SATRAK is configured to receive it (not implemented).
2. A timed revocation test: obtain a token, call an authenticated endpoint (200), revoke through the admin
   endpoint at T0, then call again on **each** API instance every second until 401. Record the maximum
   delay (expected: the next request). Repeat with a user-level revoke, with Redis stopped, and with one
   instance restarted.
3. An IdP-side disable test: disable the user at the IdP, then measure how long the old token still works.
   If this exceeds 60 s, either an IdP signal must be integrated or the requirement restated by the owner.
4. The audit trail for each test (`session.revoked`, `access.denied`) and the chain verifier output.

## 2. No untrusted direct access to the API

What the code does: `X-Forwarded-For` is believed only from `rate_limit.trusted_proxy_cidrs` and only
`trusted_proxy_hops` entries from the right; anything else is keyed by the TCP peer. This protects rate-limit
keys. It does not stop a client from reaching the API port.

Controls to put in place and demonstrate (none exists in the repository; `infra/k8s` and `infra/terraform`
are empty):

1. Only the proxy/load balancer can connect to the API port: a security group, private subnet or
   Kubernetes `NetworkPolicy` that admits the proxy's address range only. The same range goes into
   `SATRAK_API_RATE_LIMIT_TRUSTED_PROXY_CIDRS`; `..._TRUSTED_PROXY_HOPS` equals the number of proxies that
   append to the header.
2. If uvicorn is started with `--proxy-headers`, `--forwarded-allow-ips` must be the same range, never `*`.
3. The proxy overwrites or appends `X-Forwarded-For` and strips client-supplied `X-Forwarded-*` otherwise.
4. TLS terminates at the proxy; the API port is not published publicly (compose publishes it for local
   development only).

Evidence: (a) a connection attempt to the API port from a host outside the range is refused or times out;
(b) through the proxy, a request carrying a forged `X-Forwarded-For` is limited under the proxy-observed
address (inspect the `rate_limited` log key or exhaust `api_ip` from the forged value and from the real one);
(c) `rate_limit_no_trusted_proxy` is absent from production start-up logs.

## 3. Limits and policy values awaiting confirmation

- `api_ip` is 120 requests/minute/IP over all requests from an address (owner decision 2026-10-10). It
  needs load and abuse testing; users behind one NAT share it. Stricter endpoint limits still apply.
- `session_retention_days` = 30 is **unapproved**; the records-retention policy must decide.
- Rate-limit fallback state and metrics are per process.

## 4. Release checks

Local sandbox (Python 3.13): the Next.js production build failed on a font fetch (TLS), and Docker could not
be run. GitHub Actions at `d7ab92d` (Python 3.12) then passed these jobs: Web (lint, typecheck, test, build),
API (includes "Dependency lock is current"), Integration, Migrations, Security, Docker build verification and
CodeQL. What those jobs do and do not prove:

- **Lockfile freshness (Python 3.12):** enforced. The API job reinstalls from the hash-pinned lock, runs
  `pip-compile` (pip-tools 7.6.2) for `requirements.lock` and `requirements-dev.lock` on 3.12, then
  `git diff --exit-code`. It checks the committed locks on Linux x86_64 only.
- **Docker:** the job builds two images without pushing: `apps/api/Dockerfile` (tag `satrak-api:ci`) and
  `apps/web/Dockerfile` (`satrak-web:ci`). It never starts a container, so the `HEALTHCHECK`, the non-root
  user, start-up under production settings and an image vulnerability scan are not exercised by that job
  (the separate `container-smoke` job, below, starts the images; an image vulnerability scan is not part of
  this change). No image exists for a job worker. `infra/docker-compose` also pulls `postgis/postgis:16-3.4`, `redis:7-alpine` and
  `node:20-slim` for local development; those are not built or scanned by CI. Base images are pinned by tag,
  not digest.

### Container smoke job (`container-smoke`)

At `e34c3b7` every step of the job passed in GitHub Actions: the API image migrates and starts under production
settings with synthetic config (live and ready 200, issuer unreachable), runs as the non-root `satrak` user
with a healthy `HEALTHCHECK`, and exits non-zero for a schema-owner database role and for a missing database;
the Web image serves `/` with 200 as the non-root `nextjs` user. Details and limits: `docs/DOCKER_VALIDATION.md`.
This is CI evidence for R10 only in part (see the table); it is not staging evidence.

## 5. Evidence record (fill in during staging; leave blank until demonstrated)

| #   | Requirement                            | Pass criterion                                                                    | Result           | Date / run / log link                                                                                                                                     |
| --- | -------------------------------------- | --------------------------------------------------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | IdP emits `sid` or `jti`               | Present in a captured access token (claims only)                                  |                  |                                                                                                                                                           |
| R2  | IdP access-token lifetime              | Documented value, and `exp - iat` in a captured token, at most 900 s              |                  |                                                                                                                                                           |
| R3  | SATRAK-side revocation                 | 401 on every API instance within 60 s of the revoke call (expected: next request) |                  |                                                                                                                                                           |
| R4  | IdP-side disable                       | Old token rejected within 60 s, via an integrated IdP signal                      |                  |                                                                                                                                                           |
| R5  | API port reachable only from the proxy | Connection from outside the allowed range is refused or times out                 |                  |                                                                                                                                                           |
| R6  | Forged `X-Forwarded-For`               | Limited under the proxy-observed address                                          |                  |                                                                                                                                                           |
| R7  | `rate_limit_no_trusted_proxy`          | Absent from production start-up logs                                              |                  |                                                                                                                                                           |
| R8  | Session retention                      | Written approval of a retention period (30 days is unapproved)                    |                  |                                                                                                                                                           |
| R9  | AI finding publication gate            | `finding:verify` enforced by an implemented finding/case flow, with tests         | NOT IMPLEMENTED  | Only `authorize_verification` exists (ADR-0014); no finding or case aggregate. Its own approved phase. Not passed.                                        |
| R10 | Container runtime                      | Images start under production settings, non-root, healthy, refuse unsafe config   | PARTIAL: CI only | `container-smoke` green at `e34c3b7`. Still open: run in the real runtime (staging), compose stack, image scan (separate PR), worker image (none exists). |

R4 passes only with evidence of an IdP signal that SATRAK consumes. If the IdP offers none, the one-minute
requirement stays unmet unless the owner restates it.
