# Access-control sprint: acceptance evidence (A1–A14)

Status at the local sprint checkpoint. Everything below was run locally against PostgreSQL 16 + PostGIS
and a real Redis; nothing has been pushed or deployed, and the CI workflow additions have **not** been run
on GitHub. Test paths are relative to `apps/api/`.

| ID  | Evidence                                                                                                                                                                              | Result                                     |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| A1  | `tests/api/test_auth_api.py` (route inventory, bad-token matrix), `tests/core/test_token_verifier.py`                                                                                 | Passing                                    |
| A2  | `tests/api/test_authz_api.py`, `tests/api/test_eo_authz.py`                                                                                                                           | Passing                                    |
| A3  | `tests/api/test_authz_api.py`, `tests/api/test_eo_authz.py`, `tests/db/test_access_contract.py` (same scenarios on memory and SQL). Foreign objects return 403 (decision open)        | Passing                                    |
| A4  | `tests/api/test_eo_authz.py` (tile endpoint)                                                                                                                                          | Passing                                    |
| A5  | `tests/api/test_revocation_api.py`, `tests/db/test_security_audit_store.py` (durable, fail-closed)                                                                                    | Passing                                    |
| A6  | `tests/db/test_security_audit_store.py` (triggers, hash chain), `tests/db/test_row_level_security.py` (app role privileges)                                                           | Passing                                    |
| A7  | `tests/api/test_revocation_api.py`. Revocation reads PostgreSQL on every request (no cache), so there is no warm-cache window; propagation is asserted `< 5 s`, in practice immediate | Passing; Redis cache deliberately deferred |
| A8  | `tests/api/test_auth_api.py`, `tests/api/test_authz_api.py` (spoofed headers), `tests/db/test_row_level_security.py` (raw SQL as app role)                                            | Passing                                    |
| A9  | `tests/db/test_access_schema.py` (round trip, `alembic check` drift, data-preserving), CI `migrations` job                                                                            | Passing locally                            |
| A10 | ruff, format, mypy strict, bandit, import-linter (6 contracts), pip-audit, pytest 602 passed / 93 % coverage, web lint/typecheck/test                                                 | Passing; **web build and docker not run**  |
| A11 | `tests/core/test_auth_config.py`, production-settings validators                                                                                                                      | Passing                                    |
| A12 | `tests/core/test_ratelimit.py` (memory and real Redis), `tests/api/test_rate_limit_api.py`                                                                                            | Passing                                    |
| A13 | `tests/db/test_row_level_security.py` (sequential, concurrent, rollback, cancellation, policy coverage, workers, privileged use)                                                      | Passing                                    |
| A14 | `tests/core/test_token_verifier.py` (rotation, retired key, refresh storm)                                                                                                            | Passing                                    |

## Not verified here

- `next build` fails in this sandbox on a Google Fonts fetch (`self-signed certificate in certificate chain`
  through the proxy); web lint, typecheck and tests pass. Docker is unavailable, so no image build was run.
- Lock files: re-resolving with pip-tools 7.6.2 on Python 3.13 gives identical pins and hashes; only the
  "via" annotations differ from the 3.12-generated files. The CI freshness check on 3.12 is authoritative.
- The new CI `integration` job is untested until it runs on GitHub.
