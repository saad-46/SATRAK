"""Officer-verification authorization (ADR-0014).

Verifying an AI finding needs *both* the ``finding:verify`` permission and that permission
in the finding's own jurisdiction. A role alone never grants global verification rights. The
finding/case aggregates do not exist yet; their verify endpoint must call this guard.
"""

from __future__ import annotations

import uuid

from app.core.authz import AccessContext

FINDING_VERIFY = "finding:verify"


def authorize_verification(ctx: AccessContext, finding_jurisdiction_id: uuid.UUID | None) -> None:
    """Raise ``AccessDeniedError`` unless ``ctx`` is a ``finding:verify`` context covering the
    finding's jurisdiction. Default deny for a missing jurisdiction or a context built for a
    different permission."""
    if ctx.permission != FINDING_VERIFY:
        raise ctx.denial(finding_jurisdiction_id)
    ctx.require(finding_jurisdiction_id)
