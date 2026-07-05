"""Tests for the Entity / StatefulEntity / AggregateRoot base classes."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.shared.domain.entity import AggregateRoot, Entity, StatefulEntity
from app.shared.domain.enums import EntityStatus
from app.shared.domain.errors import InvariantViolation
from app.shared.domain.events import DomainEvent
from app.shared.domain.identifiers import new_id


@dataclass(kw_only=True, eq=False)
class _Thing(Entity):
    name: str = "thing"


@dataclass(kw_only=True, eq=False)
class _StatefulThing(StatefulEntity):
    name: str = "thing"


@dataclass(kw_only=True, eq=False)
class _Aggregate(AggregateRoot):
    name: str = "agg"


def test_defaults() -> None:
    thing = _Thing()
    assert thing.version == 1
    assert thing.is_deleted is False
    assert thing.deleted_at is None
    assert thing.id is not None


def test_touch_bumps_version_and_actor() -> None:
    thing = _Thing()
    actor = new_id()
    original_updated = thing.updated_at
    thing.touch(actor=actor)
    assert thing.version == 2
    assert thing.updated_by == actor
    assert thing.updated_at >= original_updated


def test_soft_delete_and_restore() -> None:
    thing = _Thing()
    thing.soft_delete()
    assert thing.is_deleted is True
    assert thing.deleted_at is not None
    assert thing.version == 2

    thing.restore()
    assert thing.is_deleted is False
    assert thing.deleted_at is None
    assert thing.version == 3


def test_double_delete_raises() -> None:
    thing = _Thing()
    thing.soft_delete()
    with pytest.raises(InvariantViolation):
        thing.soft_delete()


def test_restore_when_not_deleted_raises() -> None:
    with pytest.raises(InvariantViolation):
        _Thing().restore()


def test_equality_is_by_type_and_id() -> None:
    shared_id = new_id()
    a = _Thing(id=shared_id, name="a")
    b = _Thing(id=shared_id, name="b-different-attrs")
    assert a == b
    assert hash(a) == hash(b)

    # Same id, different type -> not equal.
    other = _StatefulThing(id=shared_id)
    assert a != other


def test_stateful_transitions() -> None:
    thing = _StatefulThing()
    assert thing.status == EntityStatus.ACTIVE
    thing.deactivate()
    assert thing.status == EntityStatus.INACTIVE
    thing.archive()
    assert thing.status == EntityStatus.ARCHIVED
    thing.activate()
    assert thing.status == EntityStatus.ACTIVE
    assert thing.version == 4


def test_aggregate_records_and_pulls_events() -> None:
    agg = _Aggregate()
    assert agg.has_pending_events is False
    event = DomainEvent()
    agg.record_event(event)
    assert agg.has_pending_events is True

    pulled = agg.pull_events()
    assert pulled == [event]
    assert agg.has_pending_events is False
    assert agg.pull_events() == []
