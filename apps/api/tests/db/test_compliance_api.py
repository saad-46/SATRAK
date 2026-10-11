"""Compliance workflow through HTTP against real PostgreSQL/PostGIS.

The app runs with the real SQL access store, tenant-scoped sessions (row-level security as the
non-bypass application role), the hash-chained SQL audit log, and a fake OIDC issuer for tokens.
Fixture data is synthetic and labelled ``is_simulated``; nothing here is a government record.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.access_store import SqlAccessStore
from app.db.security_audit_store import SqlSecurityAuditLog
from app.main import create_app
from tests.auth_support import TestIdp, make_settings
from tests.authz_support import SqlWorld
from tests.db.conftest import ADMIN_ROLE, APP_ROLE, requires_database, role_engine

pytestmark = [pytest.mark.integration, requires_database]


def _square(x1: float, y1: float, x2: float, y2: float) -> dict[str, Any]:
    ring = [[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]]
    return {"type": "Polygon", "coordinates": [ring]}


PARCEL = {  # ~111 m x 108 m near 12.0N 77.0E (about 12,000 sq m)
    "type": "Polygon",
    "coordinates": [[[77.0, 12.0], [77.001, 12.0], [77.001, 12.001], [77.0, 12.001], [77.0, 12.0]]],
}
NEIGHBOUR_OVERLAPPING = {
    "type": "Polygon",
    "coordinates": [
        [[77.0009, 12.0], [77.002, 12.0], [77.002, 12.001], [77.0009, 12.001], [77.0009, 12.0]]
    ],
}
BOWTIE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
INSIDE = _square(77.0002, 12.0002, 77.0004, 12.0004)  # ~22 m x 22 m inside PARCEL (~480 sq m)
STRADDLING = _square(77.0009, 12.0002, 77.0011, 12.0004)  # half of it lies outside the parcel
IMAGERY = [{"source": "fixture-imagery", "reference": "tile-001", "acquired_on": "2026-01-01"}]
SHA = "a" * 64

OFFICER_PERMISSIONS = [
    "parcel:read", "parcel:write", "property:read", "property:write", "permit:read",
    "permit:write", "candidate:read", "candidate:create", "candidate:evaluate", "case:read",
    "case:update",
]  # fmt: skip
SUPERVISOR_PERMISSIONS = [
    "case:read", "case:create", "case:assign", "case:update", "case:resolve", "case:issue_notice",
    "candidate:read",
]  # fmt: skip
EVERYTHING = sorted({*OFFICER_PERMISSIONS, *SUPERVISOR_PERMISSIONS, "finding:verify"})


@dataclass
class Env:
    client: AsyncClient
    j: dict[str, uuid.UUID]
    users: dict[str, uuid.UUID]
    admin: AsyncEngine
    audit: SqlSecurityAuditLog
    idp: TestIdp

    def auth(self, who: str) -> dict[str, str]:
        return self.idp.bearer(claims={"sub": who})

    async def call(
        self, who: str, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Response:
        return await self.client.request(
            method, f"/api/v1{path}", json=body, headers=self.auth(who)
        )

    async def events(self, event_type: str, actor: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT outcome, details, actor_user_id FROM audit_event WHERE event_type = :t"
        async with self.admin.connect() as conn:
            rows = (await conn.execute(text(sql), {"t": event_type})).all()
        return [
            {"outcome": r.outcome, "details": r.details, "actor": r.actor_user_id}
            for r in rows
            if actor is None or r.actor_user_id == self.users[actor]
        ]


@pytest_asyncio.fixture
async def env(migrated_database: str, idp: TestIdp) -> AsyncIterator[Env]:
    settings: Settings = make_settings()
    owner = create_async_engine(migrated_database)
    admin = role_engine(migrated_database, ADMIN_ROLE)
    app_engine = role_engine(migrated_database, APP_ROLE)
    world = SqlWorld(admin, app_engine, owner)
    await world.reset()
    nat = await world.jurisdiction("IN", "national")
    s1 = await world.jurisdiction("S1", "state", nat)
    s2 = await world.jurisdiction("S2", "state", nat)
    c1 = await world.jurisdiction("C1", "city", s1)
    c2 = await world.jurisdiction("C2", "city", s1)
    c3 = await world.jurisdiction("C3", "city", s2)
    j = {"c1": c1, "c2": c2, "c3": c3}
    officer = await world.role("officer", OFFICER_PERMISSIONS)
    verifier = await world.role("verifier", ["finding:verify", "candidate:read"])
    supervisor = await world.role("supervisor", SUPERVISOR_PERMISSIONS)
    everything = await world.role("everything", EVERYTHING)
    grants = {
        "alice": (officer, c1),  # registers data, evaluates, investigates
        "bob": (officer, c1),  # a second investigator
        "vera": (verifier, c1),  # officer verification
        "sam": (supervisor, c1),  # case creation, assignment, closure
        "otto": (everything, c3),  # all rights, but in another jurisdiction
        "wide": (everything, s1),  # all rights over c1 and c2 through the parent
    }
    users: dict[str, uuid.UUID] = {}
    for name, (role, where) in grants.items():
        users[name] = await world.user(name)
        await world.assign(users[name], role, where)
    users["nobody"] = await world.user("nobody")  # active user without any grant

    sessions = async_sessionmaker(app_engine, expire_on_commit=False)

    def make_sessions() -> async_sessionmaker:  # type: ignore[type-arg]
        return sessions

    audit = SqlSecurityAuditLog(make_sessions)
    app = create_app(
        settings,
        auth=idp.runtime(settings.auth),
        access=SqlAccessStore(make_sessions),
        audit=audit,
        sessions=make_sessions,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield Env(client, j, users, admin, audit, idp)
    await world.reset()
    for engine in (owner, admin, app_engine):
        await engine.dispose()


def _permit(env: Env, **over: Any) -> dict[str, Any]:
    body = {
        "jurisdiction_id": str(env.j["c1"]),
        "permit_number": "BP-2025-001",
        "valid_from": "2025-01-01",
        "valid_to": "2027-12-31",
        "sanctioned_floors": 2,
        "sanctioned_footprint_area_sq_m": 150,
        "declared_plot_area_sq_m": 12000,
        "declared_parcel_code": "p-100",
        "source_system": "FIXTURE-PERMIT-SYSTEM",
        "is_simulated": True,
    }
    body.update(over)
    return body


def _candidate(env: Env, **over: Any) -> dict[str, Any]:
    body = {
        "jurisdiction_id": str(env.j["c1"]),
        "source_type": "ai_detection",
        "observed_on": "2026-03-01",
        "change_type": "new_structure",
        "footprint": INSIDE,
        "estimated_floors": 4,
        "confidence": 0.87,
        "model_name": "fixture-detector",
        "model_version": "0.0-simulated",
        "imagery_refs": IMAGERY,
        "is_simulated": True,
    }
    body.update(over)
    return body


async def _parcel(env: Env, code: str = "P-100", who: str = "alice", **over: Any) -> dict[str, Any]:
    body = {"jurisdiction_id": str(env.j["c1"]), "code": code, "geometry": PARCEL, **over}
    response = await env.call(who, "POST", "/parcels", body)
    assert response.status_code == 201, response.text
    return response.json()


async def _confirmed_candidate(env: Env) -> str:
    """parcel + permit + candidate, evaluated and confirmed by an officer."""
    await _parcel(env)
    assert (await env.call("alice", "POST", "/permits", _permit(env))).status_code == 201
    created = await env.call("alice", "POST", "/candidates", _candidate(env))
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert (await env.call("alice", "POST", f"/candidates/{cid}/evaluations")).status_code == 201
    review = {"decision": "confirm", "justification": "Visible new structure on two images."}
    assert (await env.call("vera", "POST", f"/candidates/{cid}/reviews", review)).status_code == 201
    return cid


# ------------------------------------------------------------------ the whole slice
async def test_full_workflow_from_parcel_to_closed_case(env: Env) -> None:
    parcel = await _parcel(env)
    assert parcel["current_version"] == 1 and parcel["topology_status"] == "clean"
    assert 11_000 < parcel["area_sq_m"] < 13_000

    prop = await env.call(
        "alice",
        "POST",
        "/properties",
        {
            "jurisdiction_id": str(env.j["c1"]),
            "parcel_id": parcel["id"],
            "property_ref": "ward-7/12",
            "land_use": "residential",
        },
    )
    assert prop.status_code == 201 and prop.json()["property_ref"] == "WARD-7/12"

    permit = (await env.call("alice", "POST", "/permits", _permit(env))).json()
    assert permit["match_status"] == "matched" and permit["parcel_id"] == parcel["id"]
    assert permit["is_simulated"] is True

    candidate = (await env.call("alice", "POST", "/candidates", _candidate(env))).json()
    assert candidate["status"] == "unverified" and candidate["is_simulated"] is True
    cid = candidate["id"]

    evaluation = (await env.call("alice", "POST", f"/candidates/{cid}/evaluations")).json()
    assert evaluation["classification"] == "exceeds_sanctioned_plan"
    assert {"footprint_within_sanctioned", "floors_within_sanctioned"} <= set(
        evaluation["failed_rules"]
    )
    assert evaluation["result"]["caveat"]  # the machine result states it is only a recommendation

    # The candidate is still not a finding: no case may be opened from it.
    gate = await env.call("sam", "POST", "/cases", {"candidate_id": cid})
    assert gate.status_code == 409 and gate.json()["code"] == "verification_required"

    review = await env.call(
        "vera",
        "POST",
        f"/candidates/{cid}/reviews",
        {"decision": "confirm", "justification": "Two images show a four storey frame."},
    )
    assert review.status_code == 201 and review.json()["resulting_status"] == "confirmed"

    case = await env.call("sam", "POST", "/cases", {"candidate_id": cid})
    assert case.status_code == 201, case.text
    body = case.json()
    assert body["status"] == "created" and body["priority_score"] == 50  # medium severity
    case_id, version = body["id"], body["version"]

    # Not under investigation before somebody owns it; assignee must hold case:update.
    early = await env.call(
        "alice",
        "POST",
        f"/cases/{case_id}/transitions",
        {"target": "under_investigation", "expected_version": version},
    )
    assert early.status_code == 409
    unfit = await env.call(
        "sam",
        "POST",
        f"/cases/{case_id}/assignment",
        {"assignee_id": str(env.users["vera"]), "expected_version": version},
    )
    assert unfit.status_code == 422  # vera holds no case:update
    assigned = await env.call(
        "sam",
        "POST",
        f"/cases/{case_id}/assignment",
        {"assignee_id": str(env.users["alice"]), "expected_version": version},
    )
    assert assigned.status_code == 200 and assigned.json()["status"] == "assigned"
    version = assigned.json()["version"]

    started = await env.call(
        "alice",
        "POST",
        f"/cases/{case_id}/transitions",
        {"target": "under_investigation", "expected_version": version},
    )
    assert started.status_code == 200
    version = started.json()["version"]

    # A notice needs at least one recorded field finding, and the case:issue_notice right.
    no_finding = await env.call(
        "sam",
        "POST",
        f"/cases/{case_id}/transitions",
        {"target": "notice_issued", "expected_version": version},
    )
    assert no_finding.status_code == 409
    finding = await env.call(
        "alice",
        "POST",
        f"/cases/{case_id}/findings",
        {
            "notes": "Frame of four floors, footprint about 20 m x 24 m.",
            "measurements": {"floors": 4, "width_m": 20.5},
            "evidence": [
                {
                    "kind": "photo",
                    "reference": "photo-001.jpg",
                    "sha256": SHA,
                    "captured_at": "2026-03-05T10:00:00+00:00",
                }
            ],
        },
    )
    assert finding.status_code == 201 and finding.json()["evidence"][0]["sha256"] == SHA
    wrong_role = await env.call(
        "alice",
        "POST",
        f"/cases/{case_id}/transitions",
        {"target": "notice_issued", "expected_version": version},
    )
    assert wrong_role.status_code == 403
    notice = await env.call(
        "sam",
        "POST",
        f"/cases/{case_id}/transitions",
        {"target": "notice_issued", "reason": "Finding recorded", "expected_version": version},
    )
    assert notice.status_code == 200 and notice.json()["status"] == "notice_issued"
    closed = await env.call(
        "sam",
        "POST",
        f"/cases/{case_id}/transitions",
        {"target": "resolved", "expected_version": notice.json()["version"]},
    )
    assert closed.status_code == 200 and closed.json()["status"] == "resolved"

    history = (await env.call("sam", "GET", f"/cases/{case_id}/history")).json()
    assert [t["to_status"] for t in history["transitions"]] == [
        "created", "assigned", "under_investigation", "notice_issued", "resolved",
    ]  # fmt: skip
    assert len(history["assignments"]) == 1 and len(history["findings"]) == 1

    # A closed case is immutable: further changes are refused.
    again = await env.call(
        "sam",
        "POST",
        f"/cases/{case_id}/assignment",
        {"assignee_id": str(env.users["bob"]), "expected_version": closed.json()["version"]},
    )
    assert again.status_code == 409

    # Every step left an audit record, and the chain verifies.
    for event_type in (
        "parcel.created", "property.created", "permit.created", "candidate.registered",
        "candidate.evaluated", "candidate.reviewed", "case.created", "case.assigned",
        "case.transitioned", "case.finding_added", "release.denied",
    ):  # fmt: skip
        assert await env.events(event_type), event_type
    transitions = [
        e for e in await env.events("case.transitioned") if e["details"]["case_id"] == case_id
    ]
    assert len(transitions) == 3  # the audit log outlives resets, so count only this case
    report = await env.audit.verify_chain()
    assert report.ok


# ----------------------------------------------------------- verification gate (ADR-0014)
@pytest.mark.parametrize("decision", [None, "request_evidence", "reject"])
async def test_a_case_cannot_be_opened_from_an_unconfirmed_candidate(
    env: Env, decision: str | None
) -> None:
    await _parcel(env)
    cid = (await env.call("alice", "POST", "/candidates", _candidate(env))).json()["id"]
    await env.call("alice", "POST", f"/candidates/{cid}/evaluations")
    if decision:
        review = {"decision": decision, "justification": "Not enough to decide either way."}
        assert (await env.call("vera", "POST", f"/candidates/{cid}/reviews", review)).is_success
    response = await env.call("sam", "POST", "/cases", {"candidate_id": cid})
    assert response.status_code == 409 and response.json()["code"] == "verification_required"
    denied = await env.events("release.denied", actor="sam")
    assert denied and denied[-1]["outcome"] == "denied"
    cases = (await env.call("sam", "GET", "/cases")).json()
    assert cases["meta"]["total"] == 0


async def test_confirmation_needs_an_evaluation_provenance_and_a_justification(env: Env) -> None:
    await _parcel(env)
    cid = (await env.call("alice", "POST", "/candidates", _candidate(env))).json()["id"]
    verify = f"/candidates/{cid}/reviews"
    confirm = {"decision": "confirm", "justification": "Looks like a new structure."}
    not_evaluated = await env.call("vera", "POST", verify, confirm)
    assert not_evaluated.status_code == 422
    assert not_evaluated.json()["errors"][0]["missing"] == "evaluation"
    await env.call("alice", "POST", f"/candidates/{cid}/evaluations")
    short = await env.call("vera", "POST", verify, {"decision": "confirm", "justification": "ok"})
    assert short.status_code == 422
    no_imagery = (
        await env.call("alice", "POST", "/candidates", _candidate(env, imagery_refs=[]))
    ).json()["id"]
    await env.call("alice", "POST", f"/candidates/{no_imagery}/evaluations")
    missing = await env.call("vera", "POST", f"/candidates/{no_imagery}/reviews", confirm)
    assert missing.status_code == 422 and missing.json()["errors"][0]["missing"] == "provenance"
    ok = await env.call("vera", "POST", verify, confirm)
    assert ok.status_code == 201


async def test_a_decision_can_be_corrected_by_appending_not_editing(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    reject = {"decision": "reject", "justification": "Second look shows a tarpaulin shed."}
    reversed_ = await env.call("vera", "POST", f"/candidates/{cid}/reviews", reject)
    assert reversed_.status_code == 201 and reversed_.json()["is_reversal"] is True
    reviews = (await env.call("vera", "GET", f"/candidates/{cid}/reviews")).json()
    assert [r["resulting_status"] for r in reviews] == ["confirmed", "rejected"]
    again = await env.call("vera", "POST", f"/candidates/{cid}/reviews", reject)
    assert again.status_code == 409  # already rejected


async def test_a_confirmation_cannot_be_reversed_while_its_case_is_open(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    assert (await env.call("sam", "POST", "/cases", {"candidate_id": cid})).status_code == 201
    reject = {"decision": "reject", "justification": "Changed my mind after the fact."}
    response = await env.call("vera", "POST", f"/candidates/{cid}/reviews", reject)
    assert response.status_code == 409


async def test_only_one_case_per_candidate(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    assert (await env.call("sam", "POST", "/cases", {"candidate_id": cid})).status_code == 201
    second = await env.call("sam", "POST", "/cases", {"candidate_id": cid})
    assert second.status_code == 409 and second.json()["code"] == "case_exists"


# ------------------------------------------------- authorization and jurisdiction isolation
async def test_verification_requires_the_verify_permission_in_the_jurisdiction(env: Env) -> None:
    await _parcel(env)
    cid = (await env.call("alice", "POST", "/candidates", _candidate(env))).json()["id"]
    await env.call("alice", "POST", f"/candidates/{cid}/evaluations")
    body = {"decision": "confirm", "justification": "Visible new structure on two images."}
    # An investigator (and even a supervisor) holds no finding:verify.
    for who in ("alice", "sam", "nobody"):
        denied = await env.call(who, "POST", f"/candidates/{cid}/reviews", body)
        assert denied.status_code == 403, who
    # A verifier in another jurisdiction cannot even see the candidate.
    foreign = await env.call("otto", "POST", f"/candidates/{cid}/reviews", body)
    assert foreign.status_code == 404
    status = (await env.call("alice", "GET", f"/candidates/{cid}")).json()["status"]
    assert status == "unverified"
    assert await env.events("access.denied")


async def test_other_jurisdictions_see_nothing_and_can_change_nothing(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    case_id = (await env.call("sam", "POST", "/cases", {"candidate_id": cid})).json()["id"]
    parcel_id = (await env.call("alice", "GET", "/parcels")).json()["items"][0]["id"]
    permit_id = (await env.call("alice", "GET", "/permits")).json()["items"][0]["id"]
    for path in (
        f"/parcels/{parcel_id}",
        f"/parcels/{parcel_id}/geometry-versions",
        f"/permits/{permit_id}",
        f"/permits/{permit_id}/history",
        f"/candidates/{cid}",
        f"/candidates/{cid}/evaluations",
        f"/candidates/{cid}/reviews",
        f"/cases/{case_id}",
        f"/cases/{case_id}/history",
    ):
        assert (await env.call("otto", "GET", path)).status_code == 404, path
    for path in ("/parcels", "/permits", "/candidates", "/cases", "/properties"):
        listing = (await env.call("otto", "GET", path)).json()
        assert listing["meta"]["total"] == 0, path
    writes = [
        ("POST", f"/permits/{permit_id}/status", {"status": "revoked", "reason": "x" * 5,
                                                  "expected_version": 1}),
        ("POST", f"/cases/{case_id}/transitions", {"target": "dismissed", "expected_version": 1}),
        ("POST", f"/cases/{case_id}/findings", {"notes": "intrusion"}),
        ("POST", f"/candidates/{cid}/evaluations", None),
    ]  # fmt: skip
    for method, path, body in writes:
        assert (await env.call("otto", method, path, body)).status_code == 404, path


async def test_creating_in_a_jurisdiction_outside_the_callers_scope_is_denied(env: Env) -> None:
    sibling = str(env.j["c2"])
    parcel = await env.call(
        "alice", "POST", "/parcels", {"jurisdiction_id": sibling, "code": "X-1", "geometry": PARCEL}
    )
    assert parcel.status_code == 403
    candidate = await env.call(
        "alice", "POST", "/candidates", _candidate(env, jurisdiction_id=sibling)
    )
    assert candidate.status_code == 403
    permit = await env.call("alice", "POST", "/permits", _permit(env, jurisdiction_id=sibling))
    assert permit.status_code == 403
    # A caller with rights over the parent state may work in either city, and only there.
    ok = await env.call(
        "wide", "POST", "/parcels", {"jurisdiction_id": sibling, "code": "X-1", "geometry": PARCEL}
    )
    assert ok.status_code == 201
    assert (await env.call("alice", "GET", "/parcels")).json()["meta"]["total"] == 0
    assert (await env.call("wide", "GET", "/parcels")).json()["meta"]["total"] == 1


async def test_a_user_without_grants_is_forbidden_and_anonymous_is_unauthorized(env: Env) -> None:
    assert (await env.call("nobody", "GET", "/parcels")).status_code == 403
    assert (await env.client.get("/api/v1/parcels")).status_code == 401


async def test_assignee_must_hold_case_update_in_the_cases_jurisdiction(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    case = (await env.call("sam", "POST", "/cases", {"candidate_id": cid})).json()
    foreign = await env.call(
        "sam",
        "POST",
        f"/cases/{case['id']}/assignment",
        {"assignee_id": str(env.users["otto"]), "expected_version": case["version"]},
    )
    assert foreign.status_code == 422
    assert (await env.call("sam", "GET", f"/cases/{case['id']}")).json()["status"] == "created"


# -------------------------------------------------------------- spatial and data validation
async def test_parcel_geometry_validation_and_versioning(env: Env) -> None:
    jid = str(env.j["c1"])
    bad = [
        BOWTIE,
        {"type": "Point", "coordinates": [77, 12]},
        {"type": "Polygon", "coordinates": [[[77, 12], [77.1, 12], [77.1, 12.1], [77, 12.1]]]},
        {"type": "Polygon", "coordinates": [[[77, 91], [77.1, 91], [77.1, 92], [77, 91]]]},
        {"type": "Polygon", "coordinates": []},
        "not geometry",
    ]
    for index, geometry in enumerate(bad):
        response = await env.call(
            "alice",
            "POST",
            "/parcels",
            {"jurisdiction_id": jid, "code": f"B-{index}", "geometry": geometry},
        )
        assert response.status_code == 422, (index, response.text)
    parcel = await _parcel(env)
    duplicate = await env.call(
        "alice", "POST", "/parcels", {"jurisdiction_id": jid, "code": "p-100", "geometry": PARCEL}
    )
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "parcel_code_taken"

    revised = {
        "type": "MultiPolygon",
        "coordinates": [INSIDE["coordinates"], PARCEL["coordinates"]],
    }  # overlapping parts are not a valid multipolygon
    rejected = await env.call(
        "alice",
        "POST",
        f"/parcels/{parcel['id']}/geometry-versions",
        {"geometry": revised, "reason": "survey update", "expected_version": 1},
    )
    assert rejected.status_code == 422
    ok = await env.call(
        "alice",
        "POST",
        f"/parcels/{parcel['id']}/geometry-versions",
        {"geometry": NEIGHBOUR_OVERLAPPING, "reason": "resurvey", "expected_version": 1},
    )
    assert ok.status_code == 201 and ok.json()["current_version"] == 2
    stale = await env.call(
        "alice",
        "POST",
        f"/parcels/{parcel['id']}/geometry-versions",
        {"geometry": PARCEL, "reason": "stale write", "expected_version": 1},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "concurrency_conflict"
    versions = (await env.call("alice", "GET", f"/parcels/{parcel['id']}/geometry-versions")).json()
    assert [v["version"] for v in versions] == [1, 2]  # the earlier geometry is retained


async def test_overlapping_neighbours_are_flagged_not_hidden(env: Env) -> None:
    await _parcel(env, "P-100")
    second = await _parcel(env, "P-200", geometry=NEIGHBOUR_OVERLAPPING)
    assert second["topology_status"] == "overlaps_neighbour"
    assert second["topology_detail"]["overlaps"][0]["code"] == "P-100"
    flagged = (await env.call("alice", "GET", "/parcels?topology_status=overlaps_neighbour")).json()
    assert [p["code"] for p in flagged["items"]] == ["P-200"]


async def test_permit_matching_and_officer_resolution(env: Env) -> None:
    parcel = await _parcel(env)
    unmatched = (
        await env.call("alice", "POST", "/permits", _permit(env, declared_parcel_code="NOPE-1"))
    ).json()
    assert unmatched["match_status"] == "unmatched" and unmatched["parcel_id"] is None
    conflict = (
        await env.call(
            "alice",
            "POST",
            "/permits",
            _permit(env, permit_number="BP-2", declared_plot_area_sq_m=30000),
        )
    ).json()
    assert conflict["match_status"] == "conflict"
    listing = (await env.call("alice", "GET", "/permits?match_status=unmatched")).json()
    assert listing["meta"]["total"] == 1

    short = await env.call(
        "alice",
        "POST",
        f"/permits/{unmatched['id']}/match",
        {"parcel_id": parcel["id"], "reason": "short", "expected_version": 1},
    )
    assert short.status_code == 422
    resolved = await env.call(
        "alice",
        "POST",
        f"/permits/{unmatched['id']}/match",
        {
            "parcel_id": parcel["id"],
            "reason": "Code was keyed with a typo; plan sheet confirms the parcel.",
            "expected_version": unmatched["version"],
        },
    )
    assert resolved.status_code == 200 and resolved.json()["match_status"] == "matched"
    history = (await env.call("alice", "GET", f"/permits/{unmatched['id']}/history")).json()
    assert [h["event"] for h in history] == ["created", "match_resolved"]


async def test_permit_status_transitions_and_concurrency(env: Env) -> None:
    await _parcel(env)
    permit = (await env.call("alice", "POST", "/permits", _permit(env))).json()
    path = f"/permits/{permit['id']}/status"
    suspended = await env.call(
        "alice",
        "POST",
        path,
        {"status": "suspended", "reason": "stop-work notice", "expected_version": 1},
    )
    assert suspended.status_code == 200 and suspended.json()["version"] == 2
    stale = await env.call(
        "alice", "POST", path, {"status": "approved", "reason": "lifted", "expected_version": 1}
    )
    assert stale.status_code == 409
    revoked = await env.call(
        "alice", "POST", path, {"status": "revoked", "reason": "fraud", "expected_version": 2}
    )
    assert revoked.status_code == 200
    back = await env.call(
        "alice", "POST", path, {"status": "approved", "reason": "oops", "expected_version": 3}
    )
    assert back.status_code == 409 and back.json()["code"] == "invalid_state_transition"


async def test_request_validation_errors_are_structured(env: Env) -> None:
    await _parcel(env)
    late_image = {**IMAGERY[0], "acquired_on": "2026-06-01"}
    cases: list[tuple[str, dict[str, Any]]] = [
        ("/permits", _permit(env, sanctioned_floors=0)),
        ("/permits", _permit(env, valid_to="2024-01-01")),
        ("/permits", _permit(env, status="draft")),
        ("/permits", _permit(env, sanctioned_footprint_area_sq_m=-1)),
        ("/candidates", _candidate(env, confidence=1.5)),
        ("/candidates", _candidate(env, observed_on="2999-01-01")),
        ("/candidates", _candidate(env, model_name=None)),
        ("/candidates", _candidate(env, imagery_refs=[late_image])),
        ("/candidates", _candidate(env, footprint=BOWTIE)),
        ("/candidates", _candidate(env, footprint={"type": "MultiPolygon", "coordinates": []})),
        ("/properties", {"jurisdiction_id": str(env.j["c1"]), "parcel_id": str(uuid.uuid4()),
                         "property_ref": "a", "land_use": "castle"}),
    ]  # fmt: skip
    for path, body in cases:
        response = await env.call("alice", "POST", path, body)
        assert response.status_code in (404, 422), (path, body, response.text)
        assert response.headers["content-type"].startswith("application/problem+json")
    malformed = await env.client.post(
        "/api/v1/parcels",
        content=b"{not json",
        headers={**env.auth("alice"), "content-type": "application/json"},
    )
    assert malformed.status_code == 422


async def test_unknown_ids_and_bad_ids(env: Env) -> None:
    missing = uuid.uuid4()
    for path in (f"/parcels/{missing}", f"/permits/{missing}", f"/candidates/{missing}",
                 f"/cases/{missing}", f"/properties/{missing}"):  # fmt: skip
        assert (await env.call("alice", "GET", path)).status_code == 404
    assert (await env.call("alice", "GET", "/parcels/not-a-uuid")).status_code == 422
    nope = await env.call("sam", "POST", "/cases", {"candidate_id": str(missing)})
    assert nope.status_code == 404


async def test_candidate_without_a_matching_parcel_is_evaluated_as_unresolved(env: Env) -> None:
    cid = (await env.call("alice", "POST", "/candidates", _candidate(env))).json()["id"]
    evaluation = (await env.call("alice", "POST", f"/candidates/{cid}/evaluations")).json()
    assert evaluation["classification"] == "parcel_unresolved"
    assert evaluation["parcel_id"] is None


async def test_candidate_straddling_the_boundary_is_flagged(env: Env) -> None:
    await _parcel(env)
    await env.call("alice", "POST", "/permits", _permit(env, sanctioned_footprint_area_sq_m=900))
    cid = (
        await env.call("alice", "POST", "/candidates", _candidate(env, footprint=STRADDLING))
    ).json()["id"]
    evaluation = (await env.call("alice", "POST", f"/candidates/{cid}/evaluations")).json()
    assert "within_parcel_boundary" in evaluation["failed_rules"]


async def test_candidate_cannot_be_evaluated_after_a_final_decision(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    again = await env.call("alice", "POST", f"/candidates/{cid}/evaluations")
    assert again.status_code == 422


async def test_listing_filters_and_pagination(env: Env) -> None:
    await _parcel(env, "P-1")
    await _parcel(env, "P-2", geometry=NEIGHBOUR_OVERLAPPING)
    first = (await env.call("alice", "GET", "/parcels?size=1&page=1")).json()
    second = (await env.call("alice", "GET", "/parcels?size=1&page=2")).json()
    assert first["meta"]["total"] == 2 and first["meta"]["has_next"] is True
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert (await env.call("alice", "GET", "/parcels?size=0")).status_code == 422
    assert (await env.call("alice", "GET", "/parcels?size=100000")).status_code == 422
    await env.call("alice", "POST", "/candidates", _candidate(env, source_type="manual_report",
                                                              model_name=None, model_version=None,
                                                              confidence=None))  # fmt: skip
    ai = (await env.call("alice", "GET", "/candidates?source_type=ai_detection")).json()
    manual = (await env.call("alice", "GET", "/candidates?source_type=manual_report")).json()
    assert ai["meta"]["total"] == 0 and manual["meta"]["total"] == 1
    assert (await env.call("alice", "GET", "/candidates?status=bogus")).status_code == 422


async def test_finding_rules(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    case = (await env.call("sam", "POST", "/cases", {"candidate_id": cid})).json()
    finding = {"notes": "On site."}
    early = await env.call("alice", "POST", f"/cases/{case['id']}/findings", finding)
    assert early.status_code == 422  # a case with no owner cannot take findings
    assigned = (
        await env.call(
            "sam",
            "POST",
            f"/cases/{case['id']}/assignment",
            {"assignee_id": str(env.users["bob"]), "expected_version": case["version"]},
        )
    ).json()
    bad_digest = {
        "notes": "x",
        "evidence": [{"kind": "photo", "reference": "a", "sha256": "zz" * 32,
                      "captured_at": "2026-01-01T00:00:00+00:00"}],
    }  # fmt: skip
    assert (
        await env.call("bob", "POST", f"/cases/{case['id']}/findings", bad_digest)
    ).status_code == 422
    naive_time = {
        "notes": "x",
        "evidence": [{"kind": "photo", "reference": "a", "sha256": SHA,
                      "captured_at": "2026-01-01T00:00:00"}],
    }  # fmt: skip
    assert (
        await env.call("bob", "POST", f"/cases/{case['id']}/findings", naive_time)
    ).status_code == 422
    ok = await env.call("bob", "POST", f"/cases/{case['id']}/findings", finding)
    assert ok.status_code == 201
    dismissed = await env.call(
        "sam",
        "POST",
        f"/cases/{case['id']}/transitions",
        {
            "target": "dismissed",
            "reason": "duplicate report",
            "expected_version": assigned["version"],
        },
    )
    assert dismissed.status_code == 200
    late = await env.call("bob", "POST", f"/cases/{case['id']}/findings", finding)
    assert late.status_code == 422  # closed cases take no further findings


async def test_stale_case_versions_are_rejected(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    case = (await env.call("sam", "POST", "/cases", {"candidate_id": cid})).json()
    body = {"assignee_id": str(env.users["alice"]), "expected_version": case["version"]}
    assert (await env.call("sam", "POST", f"/cases/{case['id']}/assignment", body)).is_success
    stale = await env.call("sam", "POST", f"/cases/{case['id']}/assignment", body)
    assert stale.status_code == 409 and stale.json()["code"] == "concurrency_conflict"


async def test_simulated_data_stays_labelled(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    candidate = (await env.call("alice", "GET", f"/candidates/{cid}")).json()
    assert candidate["is_simulated"] is True
    permit = (await env.call("alice", "GET", "/permits")).json()["items"][0]
    assert permit["is_simulated"] is True
    registered = (await env.events("candidate.registered"))[-1]
    assert registered["details"]["simulated"] is True
