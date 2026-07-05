"""Value object base.

Value objects are immutable and compared by value, not identity. Concrete value
objects are ``@dataclass(frozen=True)`` subclasses of :class:`ValueObject`; the
frozen dataclass provides structural equality and hashing for free, while each
performs its own validation in ``__post_init__`` and raises
:class:`~app.shared.domain.errors.ValueValidationError` on invalid input.
"""

from __future__ import annotations


class ValueObject:
    """Marker base for immutable, value-compared domain values.

    Kept intentionally minimal: it exists to type-annotate "this is a value
    object" and to give a shared home for helpers, not to impose machinery.
    Immutability and equality come from the concrete ``frozen=True`` dataclass.
    """

    __slots__ = ()
