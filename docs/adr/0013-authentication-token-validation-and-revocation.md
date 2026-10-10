# ADR-0013: Authentication — provider-agnostic OIDC validation and revocation

- **Status:** Proposed — design for owner review before implementation (the sprint's first story is gated on it)
- **Date:** 2026-10-10
- **Relates to:** PRD Module 18 (FR-18.x, NFR-18.1–18.3), Blueprint §2.1/§8.2, TDD §3.1/§11, [ADR-0011](0011-tenancy-jurisdiction-rows-with-rls.md)

## Context

The documents specify OIDC authorization-code + PKCE, RS256, 15-minute access tokens, RBAC+ABAC with
jurisdiction scope, MFA for elevated roles, and revocation within one minute (NFR-18.2, a hard SLA).
They do **not** specify the identity provider, issuer, audience, claim names, JWKS refresh interval
or refresh/offline lifetimes, and they disagree on who issues tokens (PRD: Keycloak issues; Blueprint/TDD: relying
party of a government IdP). **No issuer, audience, credential or claim name is invented here.**

## Decision

**A. API is a relying party that validates tokens; it never mints them.** Provider details come from configuration.

**B. Configuration** (pydantic-settings; no defaults for issuer/audience; auth cannot be enabled
with these unset and the application refuses to start): issuer, audience(s), optional JWKS URL
(otherwise OIDC discovery from the issuer, HTTPS only), `allowed_algorithms` (default `["RS256"]`; `none`
and HS\* rejected), clock-skew leeway (default 30 s), JWKS cache TTL, token size limit, and the **names of the
claims** the deployment's IdP uses for any optional mapping. Only registered claims (`sub`, `iss`, `aud`,
`exp`, `iat`, `nbf`, `jti`) are assumed by the code.

**C. Validation (PyJWT):** signature checked against the key selected by `kid` from the trusted issuer's JWKS;
algorithm taken from the explicit allow-list, never from the token header; `iss`, `aud`, `exp`, `iat`
required and checked, `nbf` honored; keys are fetched only from the configured/discovered trusted
location; unknown `kid` triggers at most one rate-limited JWKS refresh, so key rotation works without
allowing refresh storms; previous keys remain valid while still published; JWKS fetch failure with a
cached, unexpired set keeps validating (stale-while-revalidate, bounded), with no cache → fail closed.
Malformed, expired, mis-scoped, wrong-issuer/audience/algorithm tokens → 401 (RFC 9457 problem +
`WWW-Authenticate`). Tokens are never logged.

**D. Identity and authorization state live locally.** `(issuer, sub)` maps to a local user record (JIT
creation yields a user with **no permissions** and status `pending_role_assignment`). Roles, jurisdictions
and grants are read from the local database, not trusted from token claims, so revocation and
jurisdiction changes take effect without waiting for token expiry.

**E. Revocation within one minute (resolving PRD NFR-18.2 vs 15-minute tokens).** A short token lifetime alone
cannot meet the SLA, so each request is checked against server-side authorization state:

1. Revocation records: per-session revocation (`sid` if the IdP supplies it, else `jti`), and a per-user
   `revoked_before` timestamp; a token is rejected if `iat < revoked_before` or its session/jti is revoked, or
   the user is disabled, or the relevant assignments were removed.
2. Evaluation is performed on **every** request against the authoritative PostgreSQL state (implemented in
   Story 5), so revocation propagates to every instance on the very next request (propagation bound: one
   request, well inside 60 s). The Redis read-through cache (hard TTL of at most 15 s, invalidated on
   revocation) described in the original draft is **deferred**: it is an optimization to add only if measured
   load requires it, and it would be bounded by that TTL. Session rows (`auth_session`) are keyed by `sid`,
   else `jti`; a session key is bound to the first user that presents it. `iat` has one-second resolution, so a
   token minted within the same second as a user-level revocation is also rejected (the user re-authenticates).
3. **Fail closed:** if neither cache nor database can answer, requests are denied (503/401), never allowed.
4. Revocation is exposed to administrators and recorded in the audit log (`session.revoked`).
5. Tests must prove: revoked session/user rejected on the very next request with a populated cache; a second
   application instance sharing the store also rejects it; Redis outage does not allow revoked principals;
   measured propagation reported, not assumed. Refresh-token rotation and offline mobile sessions are out of
   scope (they remain an open item; N14).

**F. Audit (implemented in Story 5):** `user.logged_in` (first use of a session, written inside the session
registration, so if the audit write fails the request gets 503 and the registration rolls back: no login goes unrecorded),
`user.login_failed` (reason code only, never the token), `access.denied` (actor, permission, jurisdiction, route)
and `session.revoked` go to `audit_event`: append-only (UPDATE/DELETE/TRUNCATE rejected by triggers, including for
the table owner) and hash-chained under an advisory lock, with a verifier that reports the first broken position.
Denials stay denials if the audit store is down (logged at error level); anything that would _allow_ a new
session fails closed with 503 `audit_unavailable`. Tokens are never stored. Revocation is performed first and then
audited (a restrictive action is not blocked by an audit outage; the failure is reported as 503).

## Unresolved (need owner or IdP information)

Actual IdP, issuer and audience; claim-name mapping, if any; whether the IdP exposes `sid`; whether
refresh tokens are held by the SPA/BFF; MFA enforcement location; service-account model.

## Review decisions (owner, 2026-10-10)

- **Redis failure.** Login/auth-entry and expensive operations fail closed (503, `Retry-After: 5`) when
  distributed enforcement is unavailable. Ordinary API traffic falls back to a strict, configurable
  per-process budget (`rate_limit.fallback_per_minute`). That fallback is **not** distributed enforcement:
  each instance counts alone, so the effective ceiling is multiplied by the instance count. Degraded mode
  is observable through the error log event `rate_limiter_unavailable` (alert on it); no metric exists yet.
- **Limits.** Approved: 120/min/user API, 30/min/user EO search, 5/min and 30/h per user expensive,
  10/min/user admin/bulk, 10/min/IP auth entry. Tiles start at 120/min/user (`tiles_user`). The separate IP
  abuse ceiling (`api_ip`, currently 600/min) is configurable but is an engineering placeholder.
  Limiter-level load test (real Redis, 8 simulated instances, 5,000 concurrent calls against a 120/min rule)
  admitted exactly 120; 200 users x 130 calls admitted exactly 120 each. Not a full-stack HTTP load test.
- **Unauthorized vs foreign.** 401 unauthenticated and 403 cross-jurisdiction remain the acceptance
  contract. Nonexistent ids return 404, so id existence can be probed; ids are random UUIDs, which limits
  this. A uniform-404 policy for specific endpoints would be an explicit contract change and needs approval.
- **IdP.** Issuer, audience(s), JWKS URL and algorithms come only from deployment configuration; nothing is
  assumed. Production configuration is still missing. `sid` is optional: without it the `jti` identifies the
  session.
- **Revocation.** SATRAK is a relying party and issues no tokens. It invalidates the tokens it accepts by
  (a) the per-user `revoked_before` instant compared with token `iat`, and (b) the per-session registry,
  both read from PostgreSQL on every request, so revocation applies on the next request on every instance
  (well inside 60 s). Revocation does not depend on a role assignment: an administrator with
  `session:revoke` at a jurisdiction can revoke users assigned there, and one holding it at **national**
  scope can also revoke accounts with no assignment. The IdP must also end its own session, or the user can
  sign in again.
- **Session pruning.** `auth_session` rows are pruned by `app.db.maintenance.prune_auth_sessions` through the
  audited privileged role, `session_retention_days` after token expiry (default 30, minimum 1). The number
  is a placeholder: **the records-retention policy needs confirmation**. `audit_event` is never pruned.
