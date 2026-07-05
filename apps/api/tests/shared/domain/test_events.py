"""Tests for domain events."""

from __future__ import annotations

import dataclasses

import pytest

from app.shared.domain.events import DomainEvent, EntityCreated
from app.shared.domain.identifiers import new_id


def test_event_has_identity_and_timestamp() -> None:
    event = DomainEvent()
    assert event.event_id is not None
    assert event.occurred_at is not None
    assert event.name == "DomainEvent"


def test_entity_event_carries_aggregate_metadata() -> None:
    aggregate_id = new_id()
    event = EntityCreated(aggregate_id=aggregate_id, aggregate_type="Organization")
    assert event.aggregate_id == aggregate_id
    assert event.aggregate_type == "Organization"
    assert event.name == "EntityCreated"


def test_events_are_immutable() -> None:
    event = EntityCreated(aggregate_id=new_id(), aggregate_type="X")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.aggregate_type = "Y"  # type: ignore[misc]
