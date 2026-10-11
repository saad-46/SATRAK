"""Security audit events and the hash chain (in-memory reference; SQL parity in tests/db)."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest

from app.core.security_audit import (
    ACCESS_DENIED,
    GENESIS_HASH,
    USER_LOGGED_IN,
    InMemorySecurityAuditLog,
    SecurityEvent,
    chain_hash,
)


def _event(**kwargs: object) -> SecurityEvent:
    base: dict[str, object] = {"event_type": ACCESS_DENIED, "outcome": "denied"}
    return SecurityEvent(**{**base, **kwargs})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"event_type": "user.deleted"},
        {"outcome": "maybe"},
        {"occurred_at": datetime(2026, 1, 1)},  # naive
        {"details": {"access_token": "x"}},
        {"details": {"Authorization": "Bearer abc"}},
        {"details": {"client_secret": "x"}},
        {"details": {"note": "x" * 201}},
        {"details": {"nested": {"a": 1}}},
    ],
)
def test_invalid_events_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _event(**kwargs)


def test_hash_depends_on_previous_hash_and_every_field() -> None:
    event = _event(actor_user_id=uuid.uuid4(), details={"reason": "no_grant"})
    base = chain_hash(GENESIS_HASH, event)
    assert chain_hash("1" * 64, event) != base
    for change in (
        {"outcome": "failure"},
        {"permission": "eo:scene:read"},
        {"ip": "10.0.0.1"},
        {"details": {"reason": "other"}},
        {"jurisdiction_id": uuid.uuid4()},
        {"occurred_at": datetime(2020, 1, 1, tzinfo=UTC)},
    ):
        assert chain_hash(GENESIS_HASH, dataclasses.replace(event, **change)) != base  # type: ignore[arg-type]


async def test_chain_verifies_and_detects_tampering() -> None:
    log = InMemorySecurityAuditLog()
    for i in range(5):
        await log.record(_event(details={"n": i}))
    assert (await log.verify_chain()).ok

    edited = InMemorySecurityAuditLog(list(log.events), list(log.hashes))
    edited.events[2] = _event(details={"n": 999})
    report = await edited.verify_chain()
    assert (report.ok, report.first_bad_position, report.reason) == (False, 3, "hash mismatch")

    deleted = InMemorySecurityAuditLog(
        [e for i, e in enumerate(log.events) if i != 1],
        [h for i, h in enumerate(log.hashes) if i != 1],
    )
    report = await deleted.verify_chain()
    assert (report.ok, report.first_bad_position, report.reason) == (False, 2, "broken link")

    swapped = InMemorySecurityAuditLog(list(log.events), list(log.hashes))
    swapped.events[0], swapped.events[1] = swapped.events[1], swapped.events[0]
    assert not (await swapped.verify_chain()).ok


async def test_failing_log_raises() -> None:
    log = InMemorySecurityAuditLog(fail=True)
    with pytest.raises(RuntimeError):
        await log.record(_event(event_type=USER_LOGGED_IN, outcome="success"))
