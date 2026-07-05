"""OpenAPI schema customization.

Adds consistent metadata, tag descriptions, and a shared error-response component
so the generated spec (and any client generated from it) is self-documenting.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.core.config import Settings

TAGS_METADATA = [
    {"name": "health", "description": "Liveness and readiness probes."},
    {"name": "meta", "description": "Service version and non-secret runtime metadata."},
]


def build_custom_openapi(app: FastAPI, settings: Settings) -> Any:
    """Return a cached, customized OpenAPI schema builder."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=settings.app_name,
            version=settings.version,
            description=(
                "SATRAK — AI-Powered Government Urban Compliance Intelligence "
                "Platform. This is the API gateway foundation; domain endpoints "
                "are added by their respective bounded contexts."
            ),
            routes=app.routes,
            tags=TAGS_METADATA,
        )
        schema["info"]["contact"] = {"name": "SATRAK Engineering"}
        schema["info"]["license"] = {"name": "MIT"}
        schema.setdefault("components", {}).setdefault("schemas", {})["ErrorEnvelope"] = {
            "type": "object",
            "properties": {
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "details": {"type": "object"},
                        "request_id": {"type": "string", "nullable": True},
                    },
                }
            },
        }
        app.openapi_schema = schema
        return schema

    return custom_openapi
