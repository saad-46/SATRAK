"""Officer-console read models against real PostgreSQL/PostGIS (identity, dashboard, activity).

Same real stack as ``test_compliance_api``: SQL access store, tenant-scoped sessions under
row-level security, hash-chained audit log, fake OIDC issuer. Data is synthetic and labelled.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.db import test_compliance_api as _base
from tests.db.conftest import requires_database
from tests.db.test_compliance_api import (
    Env,
    _candidate,
    _confirmed_candidate,
    _parcel,
    _permit,
)

env = _base.env  # the shared real-stack fixture, registered in this module as well

pytestmark = [pytest.mark.integration, requires_database]


async def _json(env_: Env, who: str, path: str, status: int = 200) -> Any:
    response = await env_.call(who, "GET", path)
    assert response.status_code == status, response.text
    return response.json()


# ------------------------------------------------------------------------------- /me
async def test_me_lists_the_callers_grants_and_only_their_jurisdictions(env: Env) -> None:
    alice = await _json(env, "alice", "/me")
    assert alice["user_id"] == str(env.users["alice"])
    assert str(env.j["c1"]) in alice["permissions"]["parcel:read"]
    assert "finding:verify" not in alice["permissions"]
    assert [j["code"].split("-")[0] for j in alice["jurisdictions"]] == ["C1"]

    otto = await _json(env, "otto", "/me")
    assert [j["code"].split("-")[0] for j in otto["jurisdictions"]] == ["C3"]
    assert str(env.j["c1"]) not in {i for v in otto["permissions"].values() for i in v}


async def test_me_for_a_user_without_grants_is_empty_not_an_error(env: Env) -> None:
    nobody = await _json(env, "nobody", "/me")
    assert nobody["permissions"] == {} and nobody["jurisdictions"] == []


async def test_me_requires_authentication(env: Env) -> None:
    assert (await env.client.get("/api/v1/me")).status_code == 401


# -------------------------------------------------------------------------- dashboard
async def test_dashboard_counts_are_real_and_scoped(env: Env) -> None:
    await _confirmed_candidate(env)  # confirmed, evaluated, no case yet, in c1
    second = await env.call("alice", "POST", "/candidates", _candidate(env))
    assert second.status_code == 201

    summary = await _json(env, "sam", "/dashboard/summary")
    assert summary["candidates"]["by_status"] == {"confirmed": 1, "unverified": 1}
    assert summary["candidates"]["verified_awaiting_case"] == 1
    assert summary["candidates"]["simulated"] == 2
    assert summary["candidates"]["pending_by_jurisdiction"] == [
        {"jurisdiction_id": str(env.j["c1"]), "pending": 1}
    ]
    assert summary["cases"]["by_status"] == {} and summary["cases"]["unassigned_open"] == 0
    assert summary["sla"]["available"] is False

    # Another jurisdiction's officer sees none of it.
    otto = await _json(env, "otto", "/dashboard/summary")
    assert otto["candidates"]["by_status"] == {}


async def test_dashboard_sections_follow_the_callers_permissions(env: Env) -> None:
    await _confirmed_candidate(env)
    vera = await _json(env, "vera", "/dashboard/summary")  # candidate:read, no case:read
    assert vera["candidates"] is not None and vera["cases"] is None
    assert (await env.call("nobody", "GET", "/dashboard/summary")).status_code == 403


async def test_dashboard_case_counts_track_assignment(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    created = await env.call("sam", "POST", "/cases", {"candidate_id": cid})
    assert created.status_code == 201
    summary = await _json(env, "sam", "/dashboard/summary")
    assert summary["cases"]["by_status"] == {"created": 1}
    assert summary["cases"]["unassigned_open"] == 1
    assert summary["candidates"]["verified_awaiting_case"] == 0
    case = created.json()
    assigned = await env.call(
        "sam",
        "POST",
        f"/cases/{case['id']}/assignment",
        {"assignee_id": str(env.users["alice"]), "expected_version": case["version"]},
    )
    assert assigned.status_code == 200, assigned.text
    again = await _json(env, "sam", "/dashboard/summary")
    assert again["cases"]["unassigned_open"] == 0
    assert again["cases"]["by_status"] == {"assigned": 1}


# ---------------------------------------------------------------------------- activity
async def test_activity_is_newest_first_scoped_and_permission_filtered(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    activity = await _json(env, "alice", "/activity?limit=10")  # reads all four sources
    kinds = {i["kind"] for i in activity["items"]}
    assert {"candidate.reviewed", "parcel.geometry_version"} <= kinds
    assert any(k.startswith("permit.") for k in kinds)
    times = [i["occurred_at"] for i in activity["items"]]
    assert times == sorted(times, reverse=True)
    assert all(i["jurisdiction_id"] == str(env.j["c1"]) for i in activity["items"])

    vera = await _json(env, "vera", "/activity")  # candidate:read only
    assert vera["sources"] == ["candidate:read"]
    assert {i["kind"] for i in vera["items"]} == {"candidate.reviewed"}
    assert vera["items"][0]["entity_id"] == cid

    assert (await _json(env, "otto", "/activity"))["items"] == []
    assert (await env.call("nobody", "GET", "/activity")).status_code == 403
    assert (await env.call("alice", "GET", "/activity?limit=500")).status_code == 422


# ------------------------------------------------------------ candidate / case actions
async def _fresh_candidate(env_: Env) -> str:
    await _parcel(env_)
    assert (await env_.call("alice", "POST", "/permits", _permit(env_))).status_code == 201
    created = await env_.call("alice", "POST", "/candidates", _candidate(env_))
    assert created.status_code == 201
    return str(created.json()["id"])


async def test_candidate_actions_reflect_state_permission_and_prerequisites(env: Env) -> None:
    cid = await _fresh_candidate(env)

    vera = (await _json(env, "vera", f"/candidates/{cid}"))["actions"]
    assert vera["can_review"] is True
    assert vera["allowed_decisions"] == ["reject", "request_evidence"]  # confirm needs evaluation
    assert vera["confirm_blockers"] == ["evaluation"]
    assert vera["can_open_case"] is False

    alice = (await _json(env, "alice", f"/candidates/{cid}"))["actions"]
    assert alice["can_review"] is False and alice["allowed_decisions"] == []

    assert (await env.call("alice", "POST", f"/candidates/{cid}/evaluations")).status_code == 201
    evaluated = await _json(env, "vera", f"/candidates/{cid}")
    assert evaluated["evaluated"] is True
    assert evaluated["actions"]["allowed_decisions"] == ["confirm", "reject", "request_evidence"]
    assert evaluated["actions"]["confirm_blockers"] == []

    review = {"decision": "confirm", "justification": "Visible new structure on two images."}
    assert (await env.call("vera", "POST", f"/candidates/{cid}/reviews", review)).status_code == 201
    confirmed = await _json(env, "sam", f"/candidates/{cid}")
    assert confirmed["status"] == "confirmed" and confirmed["case_id"] is None
    assert confirmed["actions"]["can_open_case"] is True  # sam holds case:create
    assert (
        "no_permission"
        in (await _json(env, "vera", f"/candidates/{cid}"))["actions"]["open_case_blockers"]
    )


async def test_candidate_with_an_open_case_offers_no_review_and_links_the_case(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    case = (await env.call("sam", "POST", "/cases", {"candidate_id": cid})).json()
    detail = await _json(env, "vera", f"/candidates/{cid}")
    assert detail["case_id"] == case["id"]
    assert detail["actions"]["allowed_decisions"] == []
    assert (
        "case_exists"
        in (await _json(env, "sam", f"/candidates/{cid}"))["actions"]["open_case_blockers"]
    )
    # Server still refuses what the UI would not offer.
    reversal = {"decision": "reject", "justification": "Changed my mind about this."}
    assert (
        await env.call("vera", "POST", f"/candidates/{cid}/reviews", reversal)
    ).status_code == 409


async def test_case_actions_list_only_transitions_the_server_would_accept(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    case = (await env.call("sam", "POST", "/cases", {"candidate_id": cid})).json()
    first = await _json(env, "sam", f"/cases/{case['id']}")
    assert first["actions"] == {
        "can_assign": True,
        "can_add_finding": False,  # not assigned yet
        "allowed_transitions": ["dismissed"],
    }
    alice_view = await _json(env, "alice", f"/cases/{case['id']}")
    assert alice_view["actions"]["can_assign"] is False
    assert alice_view["actions"]["allowed_transitions"] == []  # no case:resolve

    body = {"assignee_id": str(env.users["alice"]), "expected_version": case["version"]}
    assigned = (await env.call("sam", "POST", f"/cases/{case['id']}/assignment", body)).json()
    mid = await _json(env, "sam", f"/cases/{case['id']}")
    assert mid["version"] == assigned["version"]
    assert set(mid["actions"]["allowed_transitions"]) == {"under_investigation", "dismissed"}
    assert "notice_issued" not in mid["actions"]["allowed_transitions"]

    started = {"target": "under_investigation", "expected_version": assigned["version"]}
    moved = await env.call("sam", "POST", f"/cases/{case['id']}/transitions", started)
    assert moved.status_code == 200, moved.text
    after = await _json(env, "sam", f"/cases/{case['id']}")
    assert "notice_issued" not in after["actions"]["allowed_transitions"]  # needs a finding
    assert set(after["actions"]["allowed_transitions"]) == {"resolved", "dismissed"}

    forbidden = {"target": "notice_issued", "expected_version": moved.json()["version"]}
    refused = await env.call("sam", "POST", f"/cases/{case['id']}/transitions", forbidden)
    assert refused.status_code == 409


# ----------------------------------------------------------------------------- filters
async def test_list_filters_for_the_console(env: Env) -> None:
    cid = await _confirmed_candidate(env)
    case = (await env.call("sam", "POST", "/cases", {"candidate_id": cid})).json()
    other = await env.call("alice", "POST", "/candidates", _candidate(env))
    assert other.status_code == 201

    c1 = str(env.j["c1"])
    pending = await _json(env, "sam", f"/candidates?status=unverified&jurisdiction_id={c1}")
    assert [i["id"] for i in pending["items"]] == [other.json()["id"]]
    assert (await _json(env, "sam", f"/candidates?jurisdiction_id={env.j['c3']}"))["items"] == []

    by_parcel = await _json(env, "sam", f"/candidates?parcel_id={case['parcel_id']}")
    assert cid in {i["id"] for i in by_parcel["items"]}

    assert (await _json(env, "sam", f"/cases?candidate_id={cid}"))["meta"]["total"] == 1
    assert (await _json(env, "sam", "/cases?unassigned=true"))["meta"]["total"] == 1
    assert (await _json(env, "sam", f"/cases?parcel_id={case['parcel_id']}"))["meta"]["total"] == 1
    assert (await _json(env, "alice", f"/permits?parcel_id={case['parcel_id']}"))["meta"][
        "total"
    ] == 1
    assert (await _json(env, "alice", f"/permits?parcel_id={env.j['c1']}"))["meta"]["total"] == 0
