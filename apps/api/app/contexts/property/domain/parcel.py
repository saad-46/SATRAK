"""Parcel and property identity rules (PRD Module 4 FR-4.1/4.4, Module 5 FR-5.1/5.2).

A parcel has a *stable* identity (its code, unique inside a jurisdiction) and a sequence of
immutable geometry versions: a boundary change appends a version, it never overwrites one
(FR-4.1, NFR-5.2). A new version is checked against its neighbours and flagged, not rejected,
when it overlaps one (FR-4.4: "detect and flag topology errors"); the flag is evidence for a
human data steward, not a silent correction.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from app.shared.domain.errors import ValueValidationError

_CODE_PATTERN: Final = re.compile(r"^[A-Z0-9][A-Z0-9/_.\-]{0,63}$")

# Closed vocabulary until zoning layers (Module 4 FR-4.2) define the authoritative one.
LAND_USES: Final = frozenset(
    {
        "residential",
        "commercial",
        "industrial",
        "mixed_use",
        "institutional",
        "agricultural",
        "public",
        "vacant",
    }
)


class TopologyStatus(StrEnum):
    CLEAN = "clean"
    OVERLAPS_NEIGHBOUR = "overlaps_neighbour"


def normalize_parcel_code(value: str) -> str:
    """Upper-case, trimmed parcel code: letters, digits and ``/ _ . -``, 1-64 characters."""
    code = value.strip().upper()
    if not _CODE_PATTERN.fullmatch(code):
        raise ValueValidationError(
            "parcel code must be 1-64 characters of letters, digits and / _ . -", field="code"
        )
    return code


def normalize_property_ref(value: str) -> str:
    """Property reference (e.g. the municipal assessment number): same alphabet as a code."""
    ref = value.strip().upper()
    if not _CODE_PATTERN.fullmatch(ref):
        raise ValueValidationError(
            "property reference must be 1-64 characters of letters, digits and / _ . -",
            field="property_ref",
        )
    return ref


def normalize_land_use(value: str) -> str:
    land_use = value.strip().lower()
    if land_use not in LAND_USES:
        raise ValueValidationError(
            f"land use must be one of: {', '.join(sorted(LAND_USES))}", field="land_use"
        )
    return land_use
