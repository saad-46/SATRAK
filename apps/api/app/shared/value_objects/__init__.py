"""Reusable, immutable value objects shared across all bounded contexts."""

from app.shared.value_objects.address import Address
from app.shared.value_objects.contact_information import ContactInformation
from app.shared.value_objects.email import Email
from app.shared.value_objects.file_reference import FileCategory, FileReference
from app.shared.value_objects.geo import BoundingBox, Coordinates, GeoPoint
from app.shared.value_objects.measurement import (
    Area,
    AreaUnit,
    Dimensions,
    Distance,
    DistanceUnit,
    Measurement,
)
from app.shared.value_objects.money import Money
from app.shared.value_objects.phone_number import PhoneNumber
from app.shared.value_objects.ranges import DateRange, TimeRange
from app.shared.value_objects.version import SemanticVersion

__all__ = [
    "Address",
    "Area",
    "AreaUnit",
    "BoundingBox",
    "ContactInformation",
    "Coordinates",
    "DateRange",
    "Dimensions",
    "Distance",
    "DistanceUnit",
    "Email",
    "FileCategory",
    "FileReference",
    "GeoPoint",
    "Measurement",
    "Money",
    "PhoneNumber",
    "SemanticVersion",
    "TimeRange",
]
