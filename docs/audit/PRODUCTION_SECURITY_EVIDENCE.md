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

## 4. Release checks not yet run in this environment

Next.js production build (sandbox TLS failure on the font fetch), Docker image builds, the GitHub
integration CI job, and the Python 3.12 lockfile freshness check.
