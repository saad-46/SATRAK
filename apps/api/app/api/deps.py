"""Shared FastAPI dependencies (dependency-injection surface).

Endpoints depend on these callables rather than importing infrastructure
directly, so wiring stays centralized and is trivial to override in tests.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db


def get_app_settings(request: Request) -> Settings:
    """Return the settings the running app was constructed with.

    Reads from ``app.state`` rather than the module-level ``get_settings()`` cache
    so a test (or an embedding process) that builds the app with custom settings
    gets those exact settings in every endpoint.
    """
    return cast(Settings, request.app.state.settings)


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]
