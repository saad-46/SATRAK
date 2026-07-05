"""Tests for the specification pattern."""

from __future__ import annotations

from app.shared.domain.specification import PredicateSpecification


def test_predicate_specification() -> None:
    is_even = PredicateSpecification[int](lambda n: n % 2 == 0)
    assert is_even.is_satisfied_by(4) is True
    assert is_even.is_satisfied_by(3) is False


def test_and_or_not_composition() -> None:
    is_even = PredicateSpecification[int](lambda n: n % 2 == 0)
    is_positive = PredicateSpecification[int](lambda n: n > 0)

    both = is_even & is_positive
    either = is_even | is_positive
    not_even = ~is_even

    assert both.is_satisfied_by(4) is True
    assert both.is_satisfied_by(-4) is False
    assert either.is_satisfied_by(3) is True
    assert either.is_satisfied_by(-3) is False
    assert not_even.is_satisfied_by(3) is True
