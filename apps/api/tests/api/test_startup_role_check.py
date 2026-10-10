"""The lifespan refuses unsafe database roles (ADR-0011)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from app.core.config import Environment, Settings
from app.db.role_check import RoleReport, UnsafeDatabaseRoleError
from app.main import _verify_database_role
from tests.auth_support import auth_settings, make_settings


class _Log:
    def __init__(self) -> None:
        self.events: list[str] = []

    def info(self, event: str, **_: Any) -> None:
        self.events.append(event)

    warning = info


def _app(
    monkeypatch: pytest.MonkeyPatch, report: RoleReport | Exception, **settings: Any
) -> FastAPI:
    app = FastAPI()
    app.state.settings = make_settings().model_copy(
        update={"database_url": "postgresql+asyncpg://u:p@localhost/db", **settings}
    )
    app.state.access = object()

    async def fake(_engine: object) -> RoleReport:
        if isinstance(report, Exception):
            raise report
        return report

    monkeypatch.setattr("app.main.inspect_application_role", fake)
    monkeypatch.setattr("app.main.get_engine", lambda: object())
    return app


UNSAFE = RoleReport("postgres", ("role is a superuser",))
SAFE = RoleReport("satrak_app", ())


async def test_unsafe_role_stops_startup_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(UnsafeDatabaseRoleError, match="superuser"):
        await _verify_database_role(_app(monkeypatch, UNSAFE), _Log())


async def test_safe_role_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    log = _Log()
    await _verify_database_role(_app(monkeypatch, SAFE), log)
    assert log.events == ["database_role_verified"]


async def test_warn_mode_only_logs_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    log = _Log()
    await _verify_database_role(_app(monkeypatch, UNSAFE, database_role_check="warn"), log)
    assert log.events == ["database_role_unsafe"]


async def test_unverifiable_role_stops_production_but_not_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    down = OSError("db down")
    with pytest.raises(UnsafeDatabaseRoleError, match="could not verify"):
        await _verify_database_role(
            _app(monkeypatch, down, environment=Environment.STAGING), _Log()
        )
    log = _Log()
    await _verify_database_role(_app(monkeypatch, down), log)
    assert log.events == ["database_role_unverified"]


def test_warn_mode_is_rejected_in_staging_and_production() -> None:
    for env in (Environment.STAGING, Environment.PRODUCTION):
        with pytest.raises(ValueError, match="database_role_check"):
            Settings(
                environment=env,
                database_role_check="warn",
                redis_url="redis://x:6379/0",
                auth=auth_settings(),
            )
