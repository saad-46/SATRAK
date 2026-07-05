"""Tests for scalar/text value objects: Email, PhoneNumber, Address, Money, Version."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.shared.domain.errors import ValueValidationError
from app.shared.value_objects import (
    Address,
    Email,
    Money,
    PhoneNumber,
    SemanticVersion,
)


class TestEmail:
    def test_normalizes_and_parses(self) -> None:
        email = Email("  User@Example.COM ")
        assert email.value == "user@example.com"
        assert email.local_part == "user"
        assert email.domain == "example.com"

    @pytest.mark.parametrize("bad", ["", "no-at", "a@b", "a b@c.com", "@example.com"])
    def test_rejects_invalid(self, bad: str) -> None:
        with pytest.raises(ValueValidationError):
            Email(bad)

    def test_value_equality(self) -> None:
        assert Email("a@b.com") == Email("A@B.COM")


class TestPhoneNumber:
    def test_normalizes_separators(self) -> None:
        assert PhoneNumber("+1 (415) 555-0132").value == "+14155550132"

    @pytest.mark.parametrize("bad", ["", "abc", "+0123", "12"])
    def test_rejects_invalid(self, bad: str) -> None:
        with pytest.raises(ValueValidationError):
            PhoneNumber(bad)


class TestAddress:
    def test_valid(self) -> None:
        addr = Address(line1="1 MG Road", city="Bengaluru", country_code="in")
        assert addr.country_code == "IN"
        assert "Bengaluru" in addr.as_single_line()

    def test_requires_city(self) -> None:
        with pytest.raises(ValueValidationError):
            Address(line1="x", city="  ", country_code="IN")

    def test_bad_country_code(self) -> None:
        with pytest.raises(ValueValidationError):
            Address(line1="x", city="y", country_code="IND")


class TestMoney:
    def test_arithmetic_same_currency(self) -> None:
        a = Money(Decimal("10.50"), "INR")
        b = Money(Decimal("4.50"), "inr")
        assert a.add(b).amount == Decimal("15.00")
        assert a.subtract(b).amount == Decimal("6.00")
        assert a.multiply(2).amount == Decimal("21.00")

    def test_currency_mismatch_rejected(self) -> None:
        with pytest.raises(ValueValidationError):
            Money(Decimal("1"), "INR").add(Money(Decimal("1"), "USD"))

    def test_invalid_currency(self) -> None:
        with pytest.raises(ValueValidationError):
            Money(Decimal("1"), "RUPEE")


class TestSemanticVersion:
    def test_parse_and_str(self) -> None:
        v = SemanticVersion.parse("1.4.2")
        assert v.core == (1, 4, 2)
        assert str(v) == "1.4.2"

    def test_prerelease(self) -> None:
        v = SemanticVersion.parse("2.0.0-rc.1")
        assert v.prerelease == "rc.1"
        assert str(v) == "2.0.0-rc.1"

    def test_ordering(self) -> None:
        assert SemanticVersion.parse("1.0.0") < SemanticVersion.parse("1.2.0")
        assert SemanticVersion.parse("2.0.0") > SemanticVersion.parse("1.9.9")

    def test_invalid(self) -> None:
        with pytest.raises(ValueValidationError):
            SemanticVersion.parse("1.2")
