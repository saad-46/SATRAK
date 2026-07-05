"""Money value object with currency-safe arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject


@dataclass(frozen=True)
class Money(ValueObject):
    """An amount in a specific currency.

    Uses :class:`~decimal.Decimal` (never float) for exact monetary arithmetic.
    Operations across different currencies are rejected rather than silently
    coerced — a correctness guarantee for anything touching fees/penalties.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        code = self.currency.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueValidationError(
                "currency must be an ISO 4217 alpha-3 code", field="currency"
            )
        try:
            amount = Decimal(self.amount)
        except (InvalidOperation, TypeError) as exc:
            raise ValueValidationError(f"invalid money amount: {self.amount!r}") from exc
        if not amount.is_finite():
            raise ValueValidationError("money amount must be finite")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "currency", code)

    def _assert_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueValidationError(f"currency mismatch: {self.currency} vs {other.currency}")

    def add(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def subtract(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def multiply(self, factor: Decimal | int) -> Money:
        return Money(self.amount * Decimal(factor), self.currency)

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
