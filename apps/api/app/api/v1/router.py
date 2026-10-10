"""Aggregate router for API v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_principal
from app.api.v1.endpoints import health, meta, system
from app.api.v1.endpoints.earth_observation.router import eo_router

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health")
api_router.include_router(meta.router, prefix="/meta")
# Secure by default: everything outside the explicit public allow-list above requires an
# authenticated caller (see tests/api/test_route_inventory.py).
_authenticated = [Depends(get_current_principal)]
api_router.include_router(system.router, prefix="/system", dependencies=_authenticated)
# EO routes authenticate through their own permission dependencies (jurisdiction-scoped).
api_router.include_router(eo_router)
