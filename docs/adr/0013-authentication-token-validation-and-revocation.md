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
2. Evaluation is performed on **every** request from a shared store (Redis cache in front of PostgreSQL). Cache
   entries have a hard TTL of at most **15 seconds** (configurable, default 15 s), and revocation actively
   invalidates them, so the propagation bound is the TTL plus clock skew, well inside 60 s.
3. **Fail closed:** if neither cache nor database can answer, requests are denied (503/401), never allowed.
4. Revocation is exposed to administrators and recorded in the audit log (`session.revoked`).
5. Tests must prove: revoked session/user rejected on the very next request with a populated cache; a second
   application instance sharing the store also rejects it; Redis outage does not allow revoked principals;
   measured propagation reported, not assumed. Refresh-token rotation and offline mobile sessions are out of
   scope (they remain an open item; N14).

**F. Audit:** `user.logged_in`, `user.login_failed`, `access.denied`, `session.revoked` are written durably
(see sprint spec), and fail closed for denials.

## Unresolved (need owner or IdP information)

Actual IdP, issuer and audience; claim-name mapping, if any; whether the IdP exposes `sid`; whether
refresh tokens are held by the SPA/BFF; MFA enforcement location; service-account model.
