"""Aggregate router for API v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health, meta, system

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health")
api_router.include_router(meta.router, prefix="/meta")
api_router.include_router(system.router, prefix="/system")
