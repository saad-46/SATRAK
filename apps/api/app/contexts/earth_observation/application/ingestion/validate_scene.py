"""Scene validation (Epic 3 Story 11).

A composable rule set over a ``ValidationContext``: each rule is a pure function
returning an issue or ``None``, so new checks extend the set without modifying the
validator (open/closed). The service applies the verdict to the aggregate — pass moves
the scene to ``VALIDATED``; failures reject it with the issue codes as the reason
(emitting ``ImageRejected``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.domain.ports.repositories import SceneRepository
from app.contexts.earth_observation.infrastructure.storage.keying import ensure_sha256
from app.shared.domain.clock import utcnow
from app.shared.domain.errors import ValueValidationError
from app.shared.domain.identifiers import EntityId
from app.shared.domain.scope import AccessScope
from app.shared.persistence.scoped import ScopedRepository
from app.shared.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class ValidationIssue:
    """One failed check, with a stable machine-readable code."""

    code: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)


@dataclass(frozen=True)
class ValidationContext:
    """Everything a rule may inspect. ``None`` expectations disable their checks."""

    scene: Scene
    now: datetime
    expected_provider: str | None = None
    expected_checksum_sha256: str | None = None
    required_band_names: tuple[str, ...] = ()
    max_cloud_cover_pct: float | None = None
    max_gsd_m: float | None = None


ValidationRule = Callable[[ValidationContext], ValidationIssue | None]


def rule_provider_consistency(ctx: ValidationContext) -> ValidationIssue | None:
    if (
        ctx.expected_provider is not None
        and ctx.scene.provider_scene_id.provider != ctx.expected_provider
    ):
        return ValidationIssue(
            code="provider_mismatch",
            message=(
                f"scene belongs to {ctx.scene.provider_scene_id.provider!r}, "
                f"expected {ctx.expected_provider!r}"
            ),
        )
    return None


def rule_bounding_box(ctx: ValidationContext) -> ValidationIssue | None:
    box = ctx.scene.bounding_box
    if box.width_deg <= 0 or box.height_deg <= 0:
        return ValidationIssue(
            code="degenerate_bounding_box",
            message="scene bounding box has zero width or height",
        )
    return None


def rule_crs_present(ctx: ValidationContext) -> ValidationIssue | None:
    if ctx.scene.crs is None:
        return None  # CRS is resolved at metadata extraction; absence is not failure here
    if ctx.scene.crs.epsg <= 0:  # defensive; the VO already forbids this
        return ValidationIssue(code="invalid_crs", message="scene CRS EPSG is invalid")
    return None


def rule_acquisition_not_in_future(ctx: ValidationContext) -> ValidationIssue | None:
    if ctx.scene.acquisition.acquired_at > ctx.now:
        return ValidationIssue(
            code="acquisition_in_future",
            message="scene claims an acquisition timestamp in the future",
        )
    return None


def rule_required_bands(ctx: ValidationContext) -> ValidationIssue | None:
    if not ctx.required_band_names:
        return None
    available = set(ctx.scene.bands.names) if ctx.scene.bands is not None else set()
    missing = [name for name in ctx.required_band_names if name not in available]
    if missing:
        return ValidationIssue(
            code="missing_bands", message=f"scene lacks required bands: {', '.join(missing)}"
        )
    return None


def rule_resolution(ctx: ValidationContext) -> ValidationIssue | None:
    if ctx.max_gsd_m is None or ctx.scene.bands is None:
        return None
    resolutions = [b.resolution.gsd_m for b in ctx.scene.bands.bands if b.resolution is not None]
    if resolutions and min(resolutions) > ctx.max_gsd_m:
        return ValidationIssue(
            code="resolution_too_coarse",
            message=f"finest band GSD {min(resolutions)} m exceeds limit {ctx.max_gsd_m} m",
        )
    return None


def rule_cloud_cover(ctx: ValidationContext) -> ValidationIssue | None:
    cloud = ctx.scene.acquisition.cloud_cover
    if (
        ctx.max_cloud_cover_pct is not None
        and cloud is not None
        and cloud.value > ctx.max_cloud_cover_pct
    ):
        return ValidationIssue(
            code="cloud_cover_exceeded",
            message=f"cloud cover {cloud.value}% exceeds limit {ctx.max_cloud_cover_pct}%",
        )
    return None


def rule_checksum(ctx: ValidationContext) -> ValidationIssue | None:
    stored = ctx.scene.checksum_sha256
    if stored is None:
        return ValidationIssue(
            code="missing_checksum", message="scene has no stored checksum (not downloaded?)"
        )
    try:
        normalized = ensure_sha256(stored)
    except ValueValidationError:
        return ValidationIssue(
            code="malformed_checksum", message="stored checksum is not a SHA-256 digest"
        )
    if ctx.expected_checksum_sha256 is not None and normalized != ensure_sha256(
        ctx.expected_checksum_sha256
    ):
        return ValidationIssue(
            code="checksum_mismatch",
            message="stored checksum does not match the provider-declared digest",
        )
    return None


def rule_sar_has_no_cloud(ctx: ValidationContext) -> ValidationIssue | None:
    # Defensive cross-check; AcquisitionMetadata already enforces it at construction.
    acq = ctx.scene.acquisition
    if acq.sensor_type is SensorType.SAR and acq.cloud_cover is not None:
        return ValidationIssue(
            code="sar_cloud_cover", message="SAR scene must not carry cloud cover"
        )
    return None


DEFAULT_RULES: tuple[ValidationRule, ...] = (
    rule_provider_consistency,
    rule_bounding_box,
    rule_crs_present,
    rule_acquisition_not_in_future,
    rule_required_bands,
    rule_resolution,
    rule_cloud_cover,
    rule_checksum,
    rule_sar_has_no_cloud,
)


@dataclass(frozen=True)
class SceneValidator:
    """Applies an ordered rule set; extend by passing a different tuple of rules."""

    rules: tuple[ValidationRule, ...] = field(default=DEFAULT_RULES)

    def validate(self, ctx: ValidationContext) -> ValidationReport:
        issues = tuple(issue for rule in self.rules if (issue := rule(ctx)) is not None)
        return ValidationReport(issues=issues)


@dataclass(frozen=True)
class ValidationPolicy:
    """Deploy-time expectations fed into every validation run."""

    expected_provider: str | None = None
    required_band_names: tuple[str, ...] = ()
    max_cloud_cover_pct: float | None = None
    max_gsd_m: float | None = None


class ValidateSceneService:
    """Runs validation and applies the verdict to the aggregate."""

    def __init__(
        self,
        *,
        scenes: SceneRepository,
        uow: UnitOfWork,
        validator: SceneValidator | None = None,
        policy: ValidationPolicy | None = None,
    ) -> None:
        self._scenes = scenes
        self._uow = uow
        self._validator = validator if validator is not None else SceneValidator()
        self._policy = policy if policy is not None else ValidationPolicy()

    async def validate(
        self, *, scene_id: EntityId, scope: AccessScope, expected_checksum_sha256: str | None = None
    ) -> ValidationReport:
        scenes = ScopedRepository(self._scenes, scope)
        scene = await scenes.require(scene_id)
        report = self._validator.validate(
            ValidationContext(
                scene=scene,
                now=utcnow(),
                expected_provider=self._policy.expected_provider,
                expected_checksum_sha256=expected_checksum_sha256,
                required_band_names=self._policy.required_band_names,
                max_cloud_cover_pct=self._policy.max_cloud_cover_pct,
                max_gsd_m=self._policy.max_gsd_m,
            )
        )
        if report.ok:
            scene.mark_validated()
        else:
            scene.reject(reason=f"validation failed: {', '.join(report.codes)}")
        await scenes.update(scene)
        self._uow.track(scene)
        await self._uow.commit()
        return report


def issues_summary(report: ValidationReport) -> Sequence[str]:
    """Human-readable one-liners for logs/operator tooling."""
    return [f"{issue.code}: {issue.message}" for issue in report.issues]
