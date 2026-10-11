"""PostgreSQL/PostGIS persistence for the compliance workflow.

Every method runs on a session that is already inside a ``tenant_session`` transaction: row-level
security limits what it can see and write to the caller's permitted jurisdictions (ADR-0011).
Methods that create a row also take the target jurisdiction explicitly so a write outside the
caller's scope fails loudly instead of silently inserting nothing.

All SQL is parameterised; GeoJSON geometry travels as a bound parameter and is parsed by PostGIS,
which is the authority for spatial validity, areas (computed on the geography type, so in square
metres) and overlap tests. Statements are assembled from constant fragments only (hence the
``nosec B608`` markers); no request value is ever interpolated into SQL text.
History tables are append-only (enforced by triggers, migration 0005).
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.shared.domain.errors import ConcurrencyConflict, ValueValidationError
from app.shared.pagination import Page, PageRequest
from app.shared.value_objects.polygon import GeoPolygon


def _required[T](row: T | None) -> T:
    """Return a row that SQL guarantees exists (INSERT ... RETURNING, aggregate); never ``None``."""
    if row is None:
        raise RuntimeError("the database returned no row for a statement that must return one")
    return row


# A neighbour overlap below this is boundary noise (shared edges), not a topology problem.
OVERLAP_THRESHOLD_SQ_M = 0.5

_GEOM = "ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)"
_PARCEL_COLUMNS = (
    "p.id, p.jurisdiction_id, p.code, p.current_version, p.created_at, p.updated_at,"
    " v.area_sq_m, v.topology_status, v.topology_detail,"
    " ST_AsGeoJSON(v.geometry, 7)::jsonb AS geometry"
)
_PARCEL_FROM = (
    "FROM parcel p JOIN parcel_geometry_version v"
    " ON v.parcel_id = p.id AND v.version = p.current_version"
)
_PERMIT_COLUMNS = (
    "id, jurisdiction_id, permit_number, status, valid_from, valid_to, sanctioned_floors,"
    " sanctioned_footprint_area_sq_m, sanctioned_built_up_area_sq_m, declared_plot_area_sq_m,"
    " declared_parcel_code, parcel_id, match_status, match_detail, source_system,"
    " source_record_ref, is_simulated, version, created_at, updated_at"
)
_CANDIDATE_COLUMNS = (
    "id, jurisdiction_id, source_type, is_simulated, observed_on, change_type,"
    " ST_AsGeoJSON(footprint, 7)::jsonb AS footprint, footprint_area_sq_m, estimated_floors,"
    " confidence, model_name, model_version, imagery_refs, provenance_note, parcel_id, status,"
    " created_at, updated_at"
)
_CASE_COLUMNS = (
    "id, jurisdiction_id, candidate_id, evaluation_id, parcel_id, source_type, severity,"
    " priority_score, status, assigned_to, opened_by, version, created_at, updated_at"
)


def _plain(value: Any) -> Any:
    """JSON-friendly scalars (the API layer serialises Decimal as float, never as a string)."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)
    return value


def _dict(row: Any) -> dict[str, Any]:
    return {key: _plain(value) for key, value in row._mapping.items()}


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


class ComplianceStore:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ------------------------------------------------------------------ helpers
    async def _one(self, sql: str, **params: object) -> dict[str, Any] | None:
        row = (await self._s.execute(text(sql), params)).first()
        return _dict(row) if row is not None else None

    async def _all(self, sql: str, **params: object) -> list[dict[str, Any]]:
        return [_dict(r) for r in (await self._s.execute(text(sql), params)).all()]

    async def _scalar(self, sql: str, **params: object) -> Any:
        return _plain((await self._s.execute(text(sql), params)).scalar_one())

    async def _page(
        self, select: str, count: str, request: PageRequest, **params: object
    ) -> Page[dict[str, Any]]:
        total = int(await self._scalar(count, **params))
        rows = await self._all(
            f"{select} LIMIT :limit OFFSET :offset",
            limit=request.limit,
            offset=request.offset,
            **params,
        )
        return Page.create(rows, total, request)

    async def _geometry_facts(self, polygon: GeoPolygon, *, multi: bool) -> dict[str, Any]:
        geojson = _json(
            polygon.to_multipolygon_geojson() if multi else polygon.to_polygon_geojson()
        )
        row = await self._one(
            f"SELECT ST_IsValid(g.geom) AS valid, ST_IsValidReason(g.geom) AS reason,"  # nosec B608
            f" ST_Area(CAST(g.geom AS geography)) AS area"
            f" FROM (SELECT {_GEOM} AS geom) g",
            g=geojson,
        )
        row = _required(row)
        if not row["valid"]:
            raise ValueValidationError(
                f"the geometry is not topologically valid: {row['reason']}", field="geometry"
            )
        return {"geojson": geojson, "area": row["area"]}

    # ------------------------------------------------------------------ parcels
    async def create_parcel(
        self,
        *,
        jurisdiction_id: uuid.UUID,
        code: str,
        polygon: GeoPolygon,
        actor: uuid.UUID,
        reason: str | None,
    ) -> dict[str, Any]:
        facts = await self._geometry_facts(polygon, multi=True)
        try:
            async with self._s.begin_nested():
                parcel_id = await self._scalar(
                    "INSERT INTO parcel (jurisdiction_id, code, current_version, created_by,"
                    " updated_by) VALUES (:j, :c, 1, :u, :u) RETURNING id",
                    j=jurisdiction_id,
                    c=code,
                    u=actor,
                )
        except IntegrityError as exc:
            raise ConflictError(
                "A parcel with this code already exists in the jurisdiction.",
                code="parcel_code_taken",
            ) from exc
        await self._insert_geometry_version(
            parcel_id, jurisdiction_id, 1, facts, actor=actor, reason=reason
        )
        return await self.get_parcel(parcel_id)

    async def add_geometry_version(
        self,
        parcel_id: uuid.UUID,
        *,
        polygon: GeoPolygon,
        actor: uuid.UUID,
        reason: str,
        expected_version: int,
    ) -> dict[str, Any]:
        current = await self._one(
            "SELECT jurisdiction_id, current_version FROM parcel WHERE id = :i FOR UPDATE",
            i=parcel_id,
        )
        if current is None:
            raise NotFoundError("Parcel not found.", code="parcel_not_found")
        if current["current_version"] != expected_version:
            raise ConcurrencyConflict(
                "The parcel geometry changed since it was read.",
                details={"current_version": current["current_version"]},
            )
        facts = await self._geometry_facts(polygon, multi=True)
        version = current["current_version"] + 1
        await self._insert_geometry_version(
            parcel_id, current["jurisdiction_id"], version, facts, actor=actor, reason=reason
        )
        await self._s.execute(
            text(
                "UPDATE parcel SET current_version = :v, updated_by = :u, updated_at = now()"
                " WHERE id = :i"
            ),
            {"v": version, "u": actor, "i": parcel_id},
        )
        return await self.get_parcel(parcel_id)

    async def _insert_geometry_version(
        self,
        parcel_id: uuid.UUID,
        jurisdiction_id: uuid.UUID,
        version: int,
        facts: dict[str, Any],
        *,
        actor: uuid.UUID,
        reason: str | None,
    ) -> None:
        overlaps = await self._all(
            f"SELECT p.code, ST_Area(CAST(ST_Intersection(v.geometry, g.geom) AS geography))"  # nosec B608
            f" AS overlap_sq_m FROM (SELECT ST_Multi({_GEOM}) AS geom) g, parcel p"
            f" JOIN parcel_geometry_version v"
            f" ON v.parcel_id = p.id AND v.version = p.current_version"
            f" WHERE p.jurisdiction_id = :j AND p.id <> :p AND ST_Intersects(v.geometry, g.geom)"
            f" AND ST_Area(CAST(ST_Intersection(v.geometry, g.geom) AS geography)) > :min"
            f" ORDER BY p.code LIMIT 20",
            g=facts["geojson"],
            j=jurisdiction_id,
            p=parcel_id,
            min=OVERLAP_THRESHOLD_SQ_M,
        )
        detail = {
            "overlaps": [
                {"code": o["code"], "overlap_sq_m": round(o["overlap_sq_m"], 2)} for o in overlaps
            ]
        }
        await self._s.execute(
            text(
                f"INSERT INTO parcel_geometry_version (parcel_id, jurisdiction_id, version,"  # nosec B608
                f" geometry, area_sq_m, topology_status, topology_detail, reason, recorded_by)"
                f" VALUES (:p, :j, :v, ST_Multi({_GEOM}), :area, :status,"
                f" CAST(:detail AS jsonb), :reason, :u)"
            ),
            {
                "p": parcel_id,
                "j": jurisdiction_id,
                "v": version,
                "g": facts["geojson"],
                "area": round(facts["area"], 2),
                "status": "overlaps_neighbour" if overlaps else "clean",
                "detail": _json(detail),
                "reason": reason,
                "u": actor,
            },
        )

    async def get_parcel(self, parcel_id: uuid.UUID) -> dict[str, Any]:
        row = await self._one(
            f"SELECT {_PARCEL_COLUMNS} {_PARCEL_FROM} WHERE p.id = :i", i=parcel_id
        )
        if row is None:
            raise NotFoundError("Parcel not found.", code="parcel_not_found")
        return row

    async def list_parcels(
        self, request: PageRequest, *, topology_status: str | None
    ) -> Page[dict[str, Any]]:
        where = "WHERE (CAST(:ts AS text) IS NULL OR v.topology_status = :ts)"
        return await self._page(
            f"SELECT {_PARCEL_COLUMNS} {_PARCEL_FROM} {where} ORDER BY p.code, p.id",
            f"SELECT count(*) {_PARCEL_FROM} {where}",
            request,
            ts=topology_status,
        )

    async def parcel_history(self, parcel_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.get_parcel(parcel_id)
        return await self._all(
            "SELECT version, area_sq_m, topology_status, topology_detail, reason, recorded_by,"
            " created_at, ST_AsGeoJSON(geometry, 7)::jsonb AS geometry"
            " FROM parcel_geometry_version WHERE parcel_id = :i ORDER BY version",
            i=parcel_id,
        )

    # --------------------------------------------------------------- properties
    async def create_property(
        self,
        *,
        jurisdiction_id: uuid.UUID,
        parcel_id: uuid.UUID,
        property_ref: str,
        land_use: str,
        address_text: str | None,
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        try:
            async with self._s.begin_nested():
                row = await self._one(
                    "INSERT INTO property (jurisdiction_id, parcel_id, property_ref, land_use,"
                    " address_text, created_by, updated_by)"
                    " VALUES (:j, :p, :r, :l, :a, :u, :u)"
                    " RETURNING id, jurisdiction_id, parcel_id, property_ref, land_use,"
                    " address_text, created_at, updated_at",
                    j=jurisdiction_id,
                    p=parcel_id,
                    r=property_ref,
                    l=land_use,
                    a=address_text,
                    u=actor,
                )
        except IntegrityError as exc:
            message = str(exc.orig)
            if (
                "check_violation" in message
                or "same jurisdiction" in message
                or ("jurisdiction of the" in message)
            ):
                raise ValueValidationError(
                    "the parcel does not belong to this jurisdiction", field="parcel_id"
                ) from exc
            raise ConflictError(
                "The parcel already has a property record, or the reference is taken.",
                code="property_conflict",
            ) from exc
        row = _required(row)
        return row

    async def get_property(self, property_id: uuid.UUID) -> dict[str, Any]:
        row = await self._one(
            "SELECT id, jurisdiction_id, parcel_id, property_ref, land_use, address_text,"
            " created_at, updated_at FROM property WHERE id = :i",
            i=property_id,
        )
        if row is None:
            raise NotFoundError("Property not found.", code="property_not_found")
        return row

    async def list_properties(
        self, request: PageRequest, *, parcel_id: uuid.UUID | None = None
    ) -> Page[dict[str, Any]]:
        where = "WHERE (CAST(:p AS uuid) IS NULL OR parcel_id = :p)"
        return await self._page(
            "SELECT id, jurisdiction_id, parcel_id, property_ref, land_use, address_text,"
            f" created_at, updated_at FROM property {where} ORDER BY property_ref, id",  # nosec B608
            f"SELECT count(*) FROM property {where}",  # nosec B608
            request,
            p=parcel_id,
        )

    # ------------------------------------------------------------------ permits
    async def find_parcel_by_code(
        self, jurisdiction_id: uuid.UUID, code: str
    ) -> dict[str, Any] | None:
        return await self._one(
            "SELECT p.id, v.area_sq_m FROM parcel p JOIN parcel_geometry_version v"
            " ON v.parcel_id = p.id AND v.version = p.current_version"
            " WHERE p.jurisdiction_id = :j AND p.code = :c",
            j=jurisdiction_id,
            c=code,
        )

    async def create_permit(
        self,
        *,
        jurisdiction_id: uuid.UUID,
        values: dict[str, Any],
        parcel_id: uuid.UUID | None,
        match_status: str,
        match_detail: dict[str, object],
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        try:
            async with self._s.begin_nested():
                permit_id = await self._scalar(
                    "INSERT INTO building_permit (jurisdiction_id, permit_number, status,"
                    " valid_from, valid_to, sanctioned_floors, sanctioned_footprint_area_sq_m,"
                    " sanctioned_built_up_area_sq_m, declared_plot_area_sq_m,"
                    " declared_parcel_code, parcel_id, match_status, match_detail,"
                    " source_system, source_record_ref, is_simulated, created_by, updated_by)"
                    " VALUES (:j, :number, :status, :valid_from, :valid_to, :floors, :footprint,"
                    " :built_up, :plot, :code, :parcel, :match, CAST(:detail AS jsonb),"
                    " :system, :ref, :simulated, :u, :u) RETURNING id",
                    j=jurisdiction_id,
                    number=values["permit_number"],
                    status=values["status"],
                    valid_from=values["valid_from"],
                    valid_to=values.get("valid_to"),
                    floors=values["sanctioned_floors"],
                    footprint=values["sanctioned_footprint_area_sq_m"],
                    built_up=values.get("sanctioned_built_up_area_sq_m"),
                    plot=values.get("declared_plot_area_sq_m"),
                    code=values["declared_parcel_code"],
                    parcel=parcel_id,
                    match=match_status,
                    detail=_json(match_detail),
                    system=values["source_system"],
                    ref=values.get("source_record_ref"),
                    simulated=values["is_simulated"],
                    u=actor,
                )
        except IntegrityError as exc:
            raise ConflictError(
                "A permit with this number already exists in the jurisdiction.",
                code="permit_number_taken",
            ) from exc
        await self._permit_event(
            permit_id,
            jurisdiction_id,
            "created",
            None,
            values["status"],
            actor,
            None,
            {"match_status": match_status},
        )
        return await self.get_permit(permit_id)

    async def _permit_event(
        self,
        permit_id: uuid.UUID,
        jurisdiction_id: uuid.UUID,
        event: str,
        from_value: str | None,
        to_value: str | None,
        actor: uuid.UUID,
        reason: str | None,
        detail: dict[str, object],
    ) -> None:
        await self._s.execute(
            text(
                "INSERT INTO permit_history (permit_id, jurisdiction_id, event, from_value,"
                " to_value, actor_id, reason, detail)"
                " VALUES (:p, :j, :e, :f, :t, :a, :r, CAST(:d AS jsonb))"
            ),
            {
                "p": permit_id,
                "j": jurisdiction_id,
                "e": event,
                "f": from_value,
                "t": to_value,
                "a": actor,
                "r": reason,
                "d": _json(detail),
            },
        )

    async def get_permit(self, permit_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any]:
        row = await self._one(
            f"SELECT {_PERMIT_COLUMNS} FROM building_permit WHERE id = :i"  # nosec B608
            + (" FOR UPDATE" if lock else ""),
            i=permit_id,
        )
        if row is None:
            raise NotFoundError("Permit not found.", code="permit_not_found")
        return row

    async def list_permits(
        self,
        request: PageRequest,
        *,
        match_status: str | None,
        status: str | None,
        parcel_id: uuid.UUID | None = None,
    ) -> Page[dict[str, Any]]:
        where = (
            "WHERE (CAST(:m AS text) IS NULL OR match_status = :m)"
            " AND (CAST(:s AS text) IS NULL OR status = :s)"
            " AND (CAST(:p AS uuid) IS NULL OR parcel_id = :p)"
        )
        return await self._page(
            f"SELECT {_PERMIT_COLUMNS} FROM building_permit {where} ORDER BY permit_number, id",  # nosec B608
            f"SELECT count(*) FROM building_permit {where}",  # nosec B608
            request,
            m=match_status,
            s=status,
            p=parcel_id,
        )

    async def permit_history(self, permit_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.get_permit(permit_id)
        return await self._all(
            "SELECT seq, event, from_value, to_value, actor_id, reason, detail, created_at"
            " FROM permit_history WHERE permit_id = :i ORDER BY seq",
            i=permit_id,
        )

    async def change_permit_status(
        self,
        permit_id: uuid.UUID,
        *,
        target: str,
        reason: str,
        actor: uuid.UUID,
        expected_version: int,
        validate: Any,
    ) -> dict[str, Any]:
        permit = await self.get_permit(permit_id, lock=True)
        if permit["version"] != expected_version:
            raise ConcurrencyConflict(
                "The permit changed since it was read.",
                details={"current_version": permit["version"]},
            )
        validate(permit["status"], target)
        await self._s.execute(
            text(
                "UPDATE building_permit SET status = :t, version = version + 1,"
                " updated_by = :u, updated_at = now() WHERE id = :i"
            ),
            {"t": target, "u": actor, "i": permit_id},
        )
        await self._permit_event(
            permit_id,
            permit["jurisdiction_id"],
            "status_changed",
            permit["status"],
            target,
            actor,
            reason,
            {},
        )
        return await self.get_permit(permit_id)

    async def resolve_permit_match(
        self,
        permit_id: uuid.UUID,
        *,
        parcel_id: uuid.UUID,
        reason: str,
        actor: uuid.UUID,
        expected_version: int,
    ) -> dict[str, Any]:
        permit = await self.get_permit(permit_id, lock=True)
        if permit["version"] != expected_version:
            raise ConcurrencyConflict(
                "The permit changed since it was read.",
                details={"current_version": permit["version"]},
            )
        parcel = await self.get_parcel(parcel_id)
        if parcel["jurisdiction_id"] != permit["jurisdiction_id"]:
            raise ValueValidationError("the parcel is in another jurisdiction", field="parcel_id")
        detail = {"resolved_by_officer": True, "previous_match_status": permit["match_status"]}
        await self._s.execute(
            text(
                "UPDATE building_permit SET parcel_id = :p, match_status = 'matched',"
                " match_detail = CAST(:d AS jsonb), version = version + 1, updated_by = :u,"
                " updated_at = now() WHERE id = :i"
            ),
            {"p": parcel_id, "d": _json(detail), "u": actor, "i": permit_id},
        )
        await self._permit_event(
            permit_id,
            permit["jurisdiction_id"],
            "match_resolved",
            permit["match_status"],
            "matched",
            actor,
            reason,
            {"parcel_code": parcel["code"]},
        )
        return await self.get_permit(permit_id)

    # --------------------------------------------------------------- candidates
    async def create_candidate(
        self,
        *,
        jurisdiction_id: uuid.UUID,
        polygon: GeoPolygon,
        values: dict[str, Any],
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        facts = await self._geometry_facts(polygon, multi=False)
        try:
            async with self._s.begin_nested():
                candidate_id = await self._scalar(
                    f"INSERT INTO construction_change_candidate (jurisdiction_id, source_type,"  # nosec B608
                    f" is_simulated, observed_on, change_type, footprint, footprint_area_sq_m,"
                    f" estimated_floors, confidence, model_name, model_version, imagery_refs,"
                    f" provenance_note, created_by, updated_by)"
                    f" VALUES (:j, :source, :simulated, :observed, :change, {_GEOM}, :area,"
                    f" :floors, :confidence, :model, :version, CAST(:refs AS jsonb), :note,"
                    f" :u, :u) RETURNING id",
                    j=jurisdiction_id,
                    source=values["source_type"],
                    simulated=values["is_simulated"],
                    observed=values["observed_on"],
                    change=values["change_type"],
                    g=facts["geojson"],
                    area=round(facts["area"], 2),
                    floors=values.get("estimated_floors"),
                    confidence=values.get("confidence"),
                    model=values.get("model_name"),
                    version=values.get("model_version"),
                    refs=_json(values["imagery_refs"]),
                    note=values.get("provenance_note"),
                    u=actor,
                )
        except IntegrityError as exc:
            raise ValueValidationError(
                "the candidate failed a database integrity check", field="candidate"
            ) from exc
        return await self.get_candidate(candidate_id)

    async def get_candidate(self, candidate_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any]:
        row = await self._one(
            f"SELECT {_CANDIDATE_COLUMNS} FROM construction_change_candidate WHERE id = :i"  # nosec B608
            + (" FOR UPDATE" if lock else ""),
            i=candidate_id,
        )
        if row is None:
            raise NotFoundError("Candidate not found.", code="candidate_not_found")
        return row

    async def list_candidates(
        self,
        request: PageRequest,
        *,
        status: str | None,
        source_type: str | None,
        jurisdiction_id: uuid.UUID | None = None,
        parcel_id: uuid.UUID | None = None,
    ) -> Page[dict[str, Any]]:
        where = (
            "WHERE (CAST(:s AS text) IS NULL OR status = :s)"
            " AND (CAST(:t AS text) IS NULL OR source_type = :t)"
            " AND (CAST(:j AS uuid) IS NULL OR jurisdiction_id = :j)"
            " AND (CAST(:p AS uuid) IS NULL OR parcel_id = :p)"
        )
        return await self._page(
            f"SELECT {_CANDIDATE_COLUMNS} FROM construction_change_candidate {where}"  # nosec B608
            f" ORDER BY created_at DESC, id",
            f"SELECT count(*) FROM construction_change_candidate {where}",  # nosec B608
            request,
            s=status,
            t=source_type,
            j=jurisdiction_id,
            p=parcel_id,
        )

    async def candidate_reviews(self, candidate_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.get_candidate(candidate_id)
        return await self._all(
            "SELECT seq, decision, resulting_status, justification, evidence_refs, is_reversal,"
            " reviewer_id, created_at FROM candidate_review WHERE candidate_id = :i ORDER BY seq",
            i=candidate_id,
        )

    async def candidate_evaluations(self, candidate_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.get_candidate(candidate_id)
        return await self._all(
            "SELECT id, seq, classification, severity, failed_rules, result, parcel_id,"
            " evaluated_by, created_at FROM candidate_evaluation"
            " WHERE candidate_id = :i ORDER BY seq",
            i=candidate_id,
        )

    async def evaluation_facts(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Spatial and permit facts the pure rule engine needs (no decisions are made here)."""
        parcel = await self._one(
            "SELECT p.id, p.code, ST_Area(CAST(ST_Intersection(v.geometry, c.footprint)"
            " AS geography)) AS overlap_sq_m,"
            " ST_Area(CAST(ST_Difference(c.footprint, v.geometry) AS geography)) AS outside_sq_m"
            " FROM construction_change_candidate c, parcel p JOIN parcel_geometry_version v"
            " ON v.parcel_id = p.id AND v.version = p.current_version"
            " WHERE c.id = :c AND p.jurisdiction_id = c.jurisdiction_id"
            " AND ST_Intersects(v.geometry, c.footprint)"
            " ORDER BY overlap_sq_m DESC, p.code LIMIT 1",
            c=candidate["id"],
        )
        if parcel is None or parcel["overlap_sq_m"] <= 0:
            return {
                "parcel_id": None,
                "parcel_code": None,
                "outside_sq_m": float(candidate["footprint_area_sq_m"]),
                "permits": [],
                "unresolved": 0,
            }
        permits = await self._all(
            "SELECT id, permit_number, status, valid_from, valid_to, sanctioned_floors,"
            " sanctioned_footprint_area_sq_m FROM building_permit"
            " WHERE parcel_id = :p AND match_status = 'matched' ORDER BY permit_number",
            p=parcel["id"],
        )
        unresolved = await self._scalar(
            "SELECT count(*) FROM building_permit WHERE declared_parcel_code = :c"
            " AND match_status <> 'matched' AND jurisdiction_id = :j",
            c=parcel["code"],
            j=candidate["jurisdiction_id"],
        )
        return {
            "parcel_id": parcel["id"],
            "parcel_code": parcel["code"],
            "outside_sq_m": float(parcel["outside_sq_m"] or 0.0),
            "permits": permits,
            "unresolved": int(unresolved),
        }

    async def record_evaluation(
        self,
        candidate: dict[str, Any],
        *,
        parcel_id: uuid.UUID | None,
        classification: str,
        severity: str,
        failed_rules: list[str],
        result: dict[str, Any],
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        row = await self._one(
            "INSERT INTO candidate_evaluation (candidate_id, jurisdiction_id, evaluated_by,"
            " parcel_id, classification, severity, failed_rules, result)"
            " VALUES (:c, :j, :u, :p, :cl, :sv, CAST(:f AS jsonb), CAST(:r AS jsonb))"
            " RETURNING id, seq, classification, severity, failed_rules, result, parcel_id,"
            " evaluated_by, created_at",
            c=candidate["id"],
            j=candidate["jurisdiction_id"],
            u=actor,
            p=parcel_id,
            cl=classification,
            sv=severity,
            f=_json(failed_rules),
            r=_json(result),
        )
        row = _required(row)
        await self._s.execute(
            text(
                "UPDATE construction_change_candidate SET parcel_id = :p, updated_by = :u,"
                " updated_at = now() WHERE id = :c"
            ),
            {"p": parcel_id, "u": actor, "c": candidate["id"]},
        )
        return row

    async def review_context(self, candidate_id: uuid.UUID) -> dict[str, Any]:
        """Locked candidate row plus what the verification rules need to know about it."""
        candidate = await self.get_candidate(candidate_id, lock=True)
        candidate["evaluated"] = bool(
            await self._scalar(
                "SELECT EXISTS (SELECT 1 FROM candidate_evaluation WHERE candidate_id = :c)",
                c=candidate_id,
            )
        )
        candidate["has_open_case"] = bool(
            await self._scalar(
                "SELECT EXISTS (SELECT 1 FROM inspection_case WHERE candidate_id = :c"
                " AND status NOT IN ('resolved', 'dismissed'))",
                c=candidate_id,
            )
        )
        return candidate

    async def record_review(
        self,
        candidate: dict[str, Any],
        *,
        decision: str,
        resulting_status: str,
        justification: str,
        evidence_refs: list[dict[str, Any]],
        is_reversal: bool,
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        review = await self._one(
            "INSERT INTO candidate_review (candidate_id, jurisdiction_id, reviewer_id, decision,"
            " resulting_status, justification, evidence_refs, is_reversal)"
            " VALUES (:c, :j, :u, :d, :s, :t, CAST(:e AS jsonb), :r)"
            " RETURNING seq, decision, resulting_status, justification, evidence_refs,"
            " is_reversal, reviewer_id, created_at",
            c=candidate["id"],
            j=candidate["jurisdiction_id"],
            u=actor,
            d=decision,
            s=resulting_status,
            t=justification,
            e=_json(evidence_refs),
            r=is_reversal,
        )
        review = _required(review)
        await self._s.execute(
            text(
                "UPDATE construction_change_candidate SET status = :s, updated_by = :u,"
                " updated_at = now() WHERE id = :c"
            ),
            {"s": resulting_status, "u": actor, "c": candidate["id"]},
        )
        return review

    # -------------------------------------------------------------------- cases
    async def latest_evaluation_id(self, candidate_id: uuid.UUID) -> uuid.UUID | None:
        row = await self._one(
            "SELECT id, severity FROM candidate_evaluation WHERE candidate_id = :c"
            " ORDER BY seq DESC LIMIT 1",
            c=candidate_id,
        )
        return None if row is None else row["id"]

    async def latest_evaluation(self, candidate_id: uuid.UUID) -> dict[str, Any] | None:
        return await self._one(
            "SELECT id, severity, parcel_id FROM candidate_evaluation WHERE candidate_id = :c"
            " ORDER BY seq DESC LIMIT 1",
            c=candidate_id,
        )

    async def create_case(
        self,
        candidate: dict[str, Any],
        *,
        evaluation: dict[str, Any],
        priority_score: int,
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        try:
            async with self._s.begin_nested():
                case_id = await self._scalar(
                    "INSERT INTO inspection_case (jurisdiction_id, candidate_id, evaluation_id,"
                    " parcel_id, source_type, severity, priority_score, status, opened_by,"
                    " created_by, updated_by) VALUES (:j, :c, :e, :p, :src, :sev, :pr, 'created',"
                    " :u, :u, :u) RETURNING id",
                    j=candidate["jurisdiction_id"],
                    c=candidate["id"],
                    e=evaluation["id"],
                    p=evaluation["parcel_id"],
                    src=candidate["source_type"],
                    sev=evaluation["severity"],
                    pr=priority_score,
                    u=actor,
                )
        except IntegrityError as exc:
            raise ConflictError(
                "A case already exists for this candidate.", code="case_exists"
            ) from exc
        await self._transition_row(
            case_id, candidate["jurisdiction_id"], None, "created", actor, "case opened"
        )
        return await self.get_case(case_id)

    async def get_case(self, case_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any]:
        row = await self._one(
            f"SELECT {_CASE_COLUMNS} FROM inspection_case WHERE id = :i"  # nosec B608
            + (" FOR UPDATE" if lock else ""),
            i=case_id,
        )
        if row is None:
            raise NotFoundError("Case not found.", code="case_not_found")
        return row

    async def list_cases(
        self,
        request: PageRequest,
        *,
        status: str | None,
        assigned_to: uuid.UUID | None,
        jurisdiction_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        parcel_id: uuid.UUID | None = None,
        unassigned: bool = False,
    ) -> Page[dict[str, Any]]:
        where = (
            "WHERE (CAST(:s AS text) IS NULL OR status = :s)"
            " AND (CAST(:a AS uuid) IS NULL OR assigned_to = :a)"
            " AND (CAST(:j AS uuid) IS NULL OR jurisdiction_id = :j)"
            " AND (CAST(:c AS uuid) IS NULL OR candidate_id = :c)"
            " AND (CAST(:p AS uuid) IS NULL OR parcel_id = :p)"
            " AND (NOT CAST(:u AS boolean) OR assigned_to IS NULL)"
        )
        return await self._page(
            f"SELECT {_CASE_COLUMNS} FROM inspection_case {where}"  # nosec B608
            f" ORDER BY priority_score DESC, created_at, id",
            f"SELECT count(*) FROM inspection_case {where}",  # nosec B608
            request,
            s=status,
            a=assigned_to,
            j=jurisdiction_id,
            c=candidate_id,
            p=parcel_id,
            u=unassigned,
        )

    async def _transition_row(
        self,
        case_id: uuid.UUID,
        jurisdiction_id: uuid.UUID,
        from_status: str | None,
        to_status: str,
        actor: uuid.UUID,
        reason: str | None,
    ) -> None:
        await self._s.execute(
            text(
                "INSERT INTO case_state_transition (case_id, jurisdiction_id, from_status,"
                " to_status, actor_id, reason) VALUES (:c, :j, :f, :t, :a, :r)"
            ),
            {"c": case_id, "j": jurisdiction_id, "f": from_status, "t": to_status, "a": actor,
             "r": reason},
        )  # fmt: skip

    async def finding_count(self, case_id: uuid.UUID) -> int:
        return int(
            await self._scalar("SELECT count(*) FROM case_finding WHERE case_id = :c", c=case_id)
        )

    async def assign_case(
        self,
        case: dict[str, Any],
        *,
        assignee: uuid.UUID,
        new_status: str,
        reason: str | None,
        actor: uuid.UUID,
        expected_version: int,
    ) -> dict[str, Any]:
        if case["version"] != expected_version:
            raise ConcurrencyConflict(
                "The case changed since it was read.",
                details={"current_version": case["version"]},
            )
        await self._s.execute(
            text(
                "INSERT INTO case_assignment (case_id, jurisdiction_id, assigned_to, assigned_by,"
                " reason) VALUES (:c, :j, :a, :b, :r)"
            ),
            {"c": case["id"], "j": case["jurisdiction_id"], "a": assignee, "b": actor,
             "r": reason},
        )  # fmt: skip
        await self._s.execute(
            text(
                "UPDATE inspection_case SET assigned_to = :a, status = :s, version = version + 1,"
                " updated_by = :u, updated_at = now() WHERE id = :i"
            ),
            {"a": assignee, "s": new_status, "u": actor, "i": case["id"]},
        )
        if new_status != case["status"]:
            await self._transition_row(
                case["id"], case["jurisdiction_id"], case["status"], new_status, actor, reason
            )
        return await self.get_case(case["id"])

    async def transition_case(
        self,
        case: dict[str, Any],
        *,
        target: str,
        reason: str | None,
        actor: uuid.UUID,
        expected_version: int,
    ) -> dict[str, Any]:
        if case["version"] != expected_version:
            raise ConcurrencyConflict(
                "The case changed since it was read.",
                details={"current_version": case["version"]},
            )
        await self._s.execute(
            text(
                "UPDATE inspection_case SET status = :s, version = version + 1, updated_by = :u,"
                " updated_at = now() WHERE id = :i"
            ),
            {"s": target, "u": actor, "i": case["id"]},
        )
        await self._transition_row(
            case["id"], case["jurisdiction_id"], case["status"], target, actor, reason
        )
        return await self.get_case(case["id"])

    async def add_finding(
        self,
        case: dict[str, Any],
        *,
        notes: str,
        measurements: dict[str, Any],
        evidence: list[dict[str, str]],
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        row = await self._one(
            "INSERT INTO case_finding (case_id, jurisdiction_id, author_id, notes, measurements,"
            " evidence) VALUES (:c, :j, :a, :n, CAST(:m AS jsonb), CAST(:e AS jsonb))"
            " RETURNING seq, author_id, notes, measurements, evidence, created_at",
            c=case["id"],
            j=case["jurisdiction_id"],
            a=actor,
            n=notes,
            m=_json(measurements),
            e=_json(evidence),
        )
        row = _required(row)
        return row

    async def case_history(self, case_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        await self.get_case(case_id)
        return {
            "transitions": await self._all(
                "SELECT seq, from_status, to_status, actor_id, reason, created_at"
                " FROM case_state_transition WHERE case_id = :c ORDER BY seq",
                c=case_id,
            ),
            "assignments": await self._all(
                "SELECT seq, assigned_to, assigned_by, reason, created_at FROM case_assignment"
                " WHERE case_id = :c ORDER BY seq",
                c=case_id,
            ),
            "findings": await self._all(
                "SELECT seq, author_id, notes, measurements, evidence, created_at"
                " FROM case_finding WHERE case_id = :c ORDER BY seq",
                c=case_id,
            ),
        }

    # ---------------------------------------------------------------- console reads
    async def candidate_facts(self, candidate_id: uuid.UUID) -> dict[str, Any]:
        """What the verification and release rules need to know, without locking the row."""
        return _required(
            await self._one(
                "SELECT EXISTS (SELECT 1 FROM candidate_evaluation WHERE candidate_id = c.id)"
                " AS evaluated,"
                " EXISTS (SELECT 1 FROM inspection_case k WHERE k.candidate_id = c.id"
                " AND k.status NOT IN ('resolved', 'dismissed')) AS has_open_case,"
                " (SELECT k.id FROM inspection_case k WHERE k.candidate_id = c.id) AS case_id"
                " FROM construction_change_candidate c WHERE c.id = :i",
                i=candidate_id,
            )
        )

    async def counts_by_status(self, table: str) -> dict[str, int]:
        if table not in ("construction_change_candidate", "inspection_case"):
            raise ValueError("unsupported table")
        rows = await self._all(f"SELECT status, count(*) AS n FROM {table} GROUP BY status")  # nosec B608
        return {r["status"]: int(r["n"]) for r in rows}

    async def candidate_dashboard(self) -> dict[str, Any]:
        awaiting = await self._scalar(
            "SELECT count(*) FROM construction_change_candidate c WHERE c.status = 'confirmed'"
            " AND NOT EXISTS (SELECT 1 FROM inspection_case k WHERE k.candidate_id = c.id)"
        )
        simulated = await self._scalar(
            "SELECT count(*) FROM construction_change_candidate WHERE is_simulated"
        )
        by_jurisdiction = await self._all(
            "SELECT jurisdiction_id, count(*) AS pending FROM construction_change_candidate"
            " WHERE status IN ('unverified', 'needs_evidence')"
            " GROUP BY jurisdiction_id ORDER BY pending DESC, jurisdiction_id LIMIT 50"
        )
        return {
            "by_status": await self.counts_by_status("construction_change_candidate"),
            "verified_awaiting_case": int(awaiting),
            "simulated": int(simulated),
            "pending_by_jurisdiction": by_jurisdiction,
        }

    async def case_dashboard(self) -> dict[str, Any]:
        unassigned = await self._scalar(
            "SELECT count(*) FROM inspection_case WHERE assigned_to IS NULL"
            " AND status NOT IN ('resolved', 'dismissed')"
        )
        open_by_jurisdiction = await self._all(
            "SELECT jurisdiction_id, count(*) AS open FROM inspection_case"
            " WHERE status NOT IN ('resolved', 'dismissed')"
            " GROUP BY jurisdiction_id ORDER BY open DESC, jurisdiction_id LIMIT 50"
        )
        return {
            "by_status": await self.counts_by_status("inspection_case"),
            "unassigned_open": int(unassigned),
            "open_by_jurisdiction": open_by_jurisdiction,
        }

    async def recent_candidate_activity(self, limit: int) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT 'candidate.reviewed' AS kind, created_at AS occurred_at,"
            " reviewer_id AS actor_id, 'candidate' AS entity_type, candidate_id AS entity_id,"
            " jurisdiction_id, decision || ' -> ' || resulting_status AS summary"
            " FROM candidate_review ORDER BY created_at DESC LIMIT :n",
            n=limit,
        )

    async def recent_case_activity(self, limit: int) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT * FROM ("
            " SELECT 'case.transitioned' AS kind, created_at AS occurred_at, actor_id,"
            " 'case' AS entity_type, case_id AS entity_id, jurisdiction_id,"
            " coalesce(from_status, 'new') || ' -> ' || to_status AS summary"
            " FROM case_state_transition"
            " UNION ALL"
            " SELECT 'case.finding_added', created_at, author_id, 'case', case_id,"
            " jurisdiction_id, 'field finding recorded' FROM case_finding"
            ") a ORDER BY occurred_at DESC LIMIT :n",
            n=limit,
        )

    async def recent_permit_activity(self, limit: int) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT 'permit.' || event AS kind, created_at AS occurred_at, actor_id,"
            " 'permit' AS entity_type, permit_id AS entity_id, jurisdiction_id,"
            " event AS summary FROM permit_history ORDER BY created_at DESC LIMIT :n",
            n=limit,
        )

    async def recent_parcel_activity(self, limit: int) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT 'parcel.geometry_version' AS kind, created_at AS occurred_at,"
            " recorded_by AS actor_id, 'parcel' AS entity_type, parcel_id AS entity_id,"
            " jurisdiction_id, 'geometry version ' || version AS summary"
            " FROM parcel_geometry_version ORDER BY created_at DESC LIMIT :n",
            n=limit,
        )


def parse_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)
