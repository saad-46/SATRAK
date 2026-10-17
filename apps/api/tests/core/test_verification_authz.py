"""ADR-0014: verification needs the permission AND the finding's jurisdiction."""

from __future__ import annotations

import uuid

import pytest

from app.core.authz import AccessContext, AccessDeniedError
from app.core.authz.verification import FINDING_VERIFY, authorize_verification

HOME, OTHER = uuid.uuid4(), uuid.uuid4()


def test_permission_in_the_findings_jurisdiction_is_allowed() -> None:
    authorize_verification(AccessContext(uuid.uuid4(), FINDING_VERIFY, frozenset({HOME})), HOME)


@pytest.mark.parametrize("jurisdiction", [OTHER, None])
def test_other_or_missing_jurisdictions_are_denied(jurisdiction: uuid.UUID | None) -> None:
    ctx = AccessContext(uuid.uuid4(), FINDING_VERIFY, frozenset({HOME}))
    with pytest.raises(AccessDeniedError):
        authorize_verification(ctx, jurisdiction)


def test_a_context_for_another_permission_never_verifies() -> None:
    ctx = AccessContext(uuid.uuid4(), "eo:scene:read", frozenset({HOME}))
    with pytest.raises(AccessDeniedError):
        authorize_verification(ctx, HOME)


def test_no_jurisdictions_means_no_verification() -> None:
    with pytest.raises(AccessDeniedError):
        authorize_verification(AccessContext(uuid.uuid4(), FINDING_VERIFY, frozenset()), HOME)
