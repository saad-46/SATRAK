"""Specification pattern.

A reusable way to encapsulate a business rule / selection criterion as a
first-class object that can be evaluated in memory and composed with ``&``, ``|``,
and ``~``. Repositories may later translate specifications into query predicates;
in the domain they express invariants and eligibility rules without leaking
persistence concerns.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class Specification[T](ABC):
    """A predicate over candidates of type ``T``."""

    @abstractmethod
    def is_satisfied_by(self, candidate: T) -> bool: ...

    def __and__(self, other: Specification[T]) -> Specification[T]:
        return _And(self, other)

    def __or__(self, other: Specification[T]) -> Specification[T]:
        return _Or(self, other)

    def __invert__(self) -> Specification[T]:
        return _Not(self)


class _And[T](Specification[T]):
    def __init__(self, left: Specification[T], right: Specification[T]) -> None:
        self._left = left
        self._right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self._left.is_satisfied_by(candidate) and self._right.is_satisfied_by(candidate)


class _Or[T](Specification[T]):
    def __init__(self, left: Specification[T], right: Specification[T]) -> None:
        self._left = left
        self._right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self._left.is_satisfied_by(candidate) or self._right.is_satisfied_by(candidate)


class _Not[T](Specification[T]):
    def __init__(self, inner: Specification[T]) -> None:
        self._inner = inner

    def is_satisfied_by(self, candidate: T) -> bool:
        return not self._inner.is_satisfied_by(candidate)


class PredicateSpecification[T](Specification[T]):
    """Adapt a plain callable into a :class:`Specification`."""

    def __init__(self, predicate: Callable[[T], bool]) -> None:
        self._predicate = predicate

    def is_satisfied_by(self, candidate: T) -> bool:
        return self._predicate(candidate)
