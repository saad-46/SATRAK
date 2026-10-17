"""Local full-stack end-to-end harness: the REAL API on real PostgreSQL/PostGIS for a browser run.

TEST-ONLY. It is not a deployment path and not an identity provider:

* It rebuilds the schema of ``SATRAK_TEST_DATABASE_URL`` with Alembic (destructive; the URL must
  name a database ending in ``_test``).
* Tokens come from the in-process fake OIDC issuer used by the API tests (``tests.auth_support``);
  the API validates them exactly as it would a real issuer's, but nothing here proves production
  IdP behaviour.
* All seeded rows are synthetic and flagged ``is_simulated``.

Usage (from apps/api)::

    SATRAK_TEST_DATABASE_URL=... python -m tests.e2e_stack.serve /tmp/e2e-token.json

It seeds one jurisdiction tree, users, one evaluated and still-unverified candidate, writes a
JSON file with a short-lived bearer token per persona, then serves the API on 127.0.0.1:8000.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

import uvicorn
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.access_store import SqlAccessStore
from app.db.security_audit_store import SqlSecurityAuditLog
from app.main import create_app
from tests.auth_support import TestIdp, make_settings
from tests.authz_support import SqlWorld
from tests.db.conftest import ADMIN_ROLE, APP_ROLE, role_engine, run_alembic
from tests.db.test_compliance_api import (
    EVERYTHING,
    IMAGERY,
    INSIDE,
    OFFICER_PERMISSIONS,
    PARCEL,
    SUPERVISOR_PERMISSIONS,
)

TOKEN_TTL_SECONDS = 840  # the API rejects tokens that live longer than 900 s


async def main(token_file: str) -> None:
    url = os.environ.get("SATRAK_TEST_DATABASE_URL", "")
    if not url.endswith("_test"):
        raise SystemExit("refusing to rebuild a database whose name does not end in _test")
    for step in (("downgrade", "base"), ("upgrade", "head")):
        result = run_alembic(*step)
        if result.returncode != 0:
            raise SystemExit(result.stderr)

    idp = TestIdp()
    settings = make_settings()
    owner = create_async_engine(url)
    admin = role_engine(url, ADMIN_ROLE)
    app_engine = role_engine(url, APP_ROLE)
    world = SqlWorld(admin, app_engine, owner)
    await world.reset()
    nat = await world.jurisdiction("IN", "national")
    state = await world.jurisdiction("S1", "state", nat)
    ward = await world.jurisdiction("W1", "city", state)
    other = await world.jurisdiction("W2", "city", state)
    officer = await world.role("officer", OFFICER_PERMISSIONS)
    everything = await world.role("everything", EVERYTHING)
    supervisor = await world.role("supervisor", SUPERVISOR_PERMISSIONS)
    users = {
        "registrar": (officer, ward),  # registers data (as the ingest process would)
        "reviewer": (everything, ward),  # the persona the browser signs in as
        "supervisor": (supervisor, ward),  # can read, but cannot verify
        "outsider": (everything, other),  # holds rights in a different jurisdiction only
    }
    ids = {}
    for name, (role, where) in users.items():
        ids[name] = await world.user(name)
        await world.assign(ids[name], role, where)
    await world.user("nobody")

    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    app = create_app(
        settings,
        auth=idp.runtime(settings.auth),
        access=SqlAccessStore(lambda: sessions),
        audit=SqlSecurityAuditLog(lambda: sessions),
        sessions=lambda: sessions,
    )

    async def call(who: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://seed") as c:
            r = await c.request(
                method, f"/api/v1{path}", json=body, headers=idp.bearer(claims={"sub": who})
            )
        assert r.status_code < 300, (method, path, r.status_code, r.text)
        return r.json()

    j = str(ward)
    parcel = await call(
        "registrar",
        "POST",
        "/parcels",
        {"jurisdiction_id": j, "code": "E2E-100", "geometry": PARCEL},
    )
    await call(
        "registrar",
        "POST",
        "/permits",
        {
            "jurisdiction_id": j, "permit_number": "E2E-BP-1", "valid_from": "2025-01-01",
            "valid_to": "2027-12-31", "sanctioned_floors": 2, "sanctioned_footprint_area_sq_m": 150,
            "declared_plot_area_sq_m": 12000, "declared_parcel_code": "E2E-100",
            "source_system": "E2E-FIXTURE", "is_simulated": True,
        },
    )  # fmt: skip
    cand = await call(
        "registrar",
        "POST",
        "/candidates",
        {
            "jurisdiction_id": j, "source_type": "ai_detection", "observed_on": "2026-03-01",
            "change_type": "new_structure", "footprint": INSIDE, "estimated_floors": 4,
            "confidence": 0.87, "model_name": "e2e-fixture-detector",
            "model_version": "0.0-simulated",
            "imagery_refs": IMAGERY, "is_simulated": True,
        },
    )  # fmt: skip
    await call("registrar", "POST", f"/candidates/{cand['id']}/evaluations")

    now = int(time.time())
    tokens = {
        name: idp.token(claims={"sub": name, "exp": now + TOKEN_TTL_SECONDS})
        for name in ("reviewer", "supervisor", "outsider", "nobody")
    }
    with open(token_file, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "tokens": tokens,
                "user_ids": {k: str(v) for k, v in ids.items()},
                "candidate_id": cand["id"],
                "parcel_id": parcel["id"],
                "ward": j,
            },
            fh,
        )
    os.chmod(token_file, 0o600)
    print("e2e stack ready", flush=True)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
