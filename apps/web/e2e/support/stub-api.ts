import type { Page, Route } from "@playwright/test";

/**
 * Stubbed SATRAK API shared by the browser specs (no database, no identity provider). It mirrors
 * the API contract (docs/OFFICER_CONSOLE.md) and keeps state. It proves UI behaviour only;
 * authorisation, RLS and the release gate are proven against real PostgreSQL by fullstack.spec.ts
 * and apps/api tests/db.
 */
export const API = "http://localhost:8000/api/v1";
export const J1 = "11111111-1111-4111-8111-111111111111";
export const USER = "99999999-9999-4999-8999-999999999999";
export const CAND = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const CASE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
export const TOKEN = "e2e.stub.token";
const footprint = {
  type: "Polygon",
  coordinates: [
    [
      [77.5, 12.9],
      [77.501, 12.9],
      [77.501, 12.901],
      [77.5, 12.901],
      [77.5, 12.9],
    ],
  ],
};

export interface State {
  status: string;
  caseId: string | null;
  caseStatus: string;
  caseVersion: number;
  reviews: unknown[];
  expired: boolean;
}

function candidate(s: State) {
  return {
    id: CAND,
    jurisdiction_id: J1,
    source_type: "ai_detection",
    is_simulated: true,
    observed_on: "2026-09-01",
    change_type: "new_structure",
    footprint,
    footprint_area_sq_m: 120,
    estimated_floors: 2,
    confidence: 0.87,
    model_name: "stub-model",
    model_version: "0",
    imagery_refs: [{ source: "stub", reference: "scene-1", acquired_on: "2026-09-01" }],
    provenance_note: "stub",
    parcel_id: null,
    status: s.status,
    created_at: "2026-09-02T10:00:00Z",
  };
}

export async function installApi(page: Page, s: State) {
  const cors = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "*",
    "access-control-allow-methods": "*",
  };
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({
      status,
      headers: {
        ...cors,
        "content-type": status >= 400 ? "application/problem+json" : "application/json",
      },
      body: JSON.stringify(body),
    });
  const pageOf = (items: unknown[]) => ({
    items,
    meta: {
      page: 1,
      size: 20,
      total: items.length,
      total_pages: 1,
      has_next: false,
      has_previous: false,
    },
  });
  const caseOut = () => ({
    id: CASE,
    jurisdiction_id: J1,
    candidate_id: CAND,
    evaluation_id: "e1",
    parcel_id: null,
    source_type: "ai_detection",
    severity: "high",
    priority_score: 70,
    status: s.caseStatus,
    assigned_to: null,
    opened_by: USER,
    version: s.caseVersion,
    created_at: "2026-09-03T10:00:00Z",
    updated_at: "2026-09-03T10:00:00Z",
  });

  await page.route(`${API}/**`, async (route) => {
    const req = route.request();
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    if (s.expired)
      return json(route, { title: "Unauthorized", status: 401, code: "unauthenticated" }, 401);
    const url = new URL(req.url());
    const path = url.pathname.replace("/api/v1", "");
    const method = req.method();
    if (path === "/me")
      return json(route, {
        user_id: USER,
        status: "active",
        jurisdictions: [{ id: J1, code: "W1", name: "Ward 1", level: "ward" }],
        permissions: Object.fromEntries(
          [
            "candidate:read",
            "finding:verify",
            "case:read",
            "case:create",
            "case:assign",
            "case:update",
            "parcel:read",
            "permit:read",
            "property:read",
          ].map((p) => [p, [J1]]),
        ),
      });
    if (path === "/dashboard/summary") {
      const pending = s.status === "unverified" ? 1 : 0;
      return json(route, {
        candidates: {
          by_status: { [s.status]: 1 },
          verified_awaiting_case: s.status === "confirmed" && !s.caseId ? 1 : 0,
          simulated: 1,
          pending_by_jurisdiction: pending ? [{ jurisdiction_id: J1, pending }] : [],
        },
        cases: {
          by_status: s.caseId ? { [s.caseStatus]: 1 } : {},
          unassigned_open: s.caseId ? 1 : 0,
          open_by_jurisdiction: s.caseId ? [{ jurisdiction_id: J1, open: 1 }] : [],
        },
        sla: { available: false },
        generated_at: "2026-10-11T06:00:00Z",
      });
    }
    if (path === "/activity") return json(route, { items: [], sources: ["candidate:read"] });
    if (path === "/candidates" && method === "GET")
      return json(
        route,
        pageOf(
          [candidate(s)].filter(
            (c) => !url.searchParams.get("status") || c.status === url.searchParams.get("status"),
          ),
        ),
      );
    if (path === `/candidates/${CAND}` && method === "GET") {
      const confirmed = s.status === "confirmed";
      return json(route, {
        ...candidate(s),
        case_id: s.caseId,
        evaluated: true,
        actions: {
          can_review: true,
          allowed_decisions: s.caseId
            ? []
            : confirmed
              ? ["reject", "request_evidence"]
              : ["confirm", "reject", "request_evidence"],
          confirm_blockers: [],
          can_open_case: confirmed && !s.caseId,
          open_case_blockers: confirmed ? (s.caseId ? ["case_exists"] : []) : ["not_verified"],
        },
      });
    }
    if (path === `/candidates/${CAND}/evaluations`)
      return json(route, [
        {
          id: "e1",
          seq: 1,
          classification: "no_matching_permit",
          severity: "high",
          failed_rules: ["permit_exists"],
          result: {},
          parcel_id: null,
          evaluated_by: USER,
          created_at: "2026-09-02T11:00:00Z",
        },
      ]);
    if (path === `/candidates/${CAND}/reviews` && method === "GET") return json(route, s.reviews);
    if (path === `/candidates/${CAND}/reviews` && method === "POST") {
      const body = req.postDataJSON() as { decision: string; justification: string };
      if (s.status !== "unverified")
        return json(
          route,
          {
            title: "Conflict",
            status: 409,
            code: "invalid_state_transition",
            detail: "already decided",
          },
          409,
        );
      s.status = body.decision === "confirm" ? "confirmed" : "rejected";
      const review = {
        seq: 1,
        decision: body.decision,
        resulting_status: s.status,
        justification: body.justification,
        evidence_refs: [],
        is_reversal: false,
        reviewer_id: USER,
        created_at: "2026-10-11T06:10:00Z",
      };
      s.reviews.push(review);
      return json(route, review, 201);
    }
    if (path === "/cases" && method === "POST") {
      s.caseId = CASE;
      return json(route, caseOut(), 201);
    }
    if (path === "/cases" && method === "GET")
      return json(route, pageOf(s.caseId ? [caseOut()] : []));
    if (path === `/cases/${CASE}` && method === "GET")
      return json(route, {
        ...caseOut(),
        actions: {
          can_assign: true,
          can_add_finding: true,
          allowed_transitions:
            s.caseStatus === "created" ? ["assigned", "dismissed"] : ["under_investigation"],
        },
      });
    if (path === `/cases/${CASE}/history`)
      return json(route, {
        transitions: [
          {
            seq: 1,
            from_status: null,
            to_status: "created",
            actor_id: USER,
            reason: null,
            created_at: "2026-09-03T10:00:00Z",
          },
        ],
        assignments: [],
        findings: [],
      });
    if (path === `/cases/${CASE}/transitions` && method === "POST") {
      const body = req.postDataJSON() as { target: string; expected_version: number };
      if (body.expected_version !== s.caseVersion)
        return json(route, { title: "Conflict", status: 409, code: "version_conflict" }, 409);
      s.caseStatus = body.target;
      s.caseVersion += 1;
      return json(route, caseOut());
    }
    return json(route, { title: "Not found", status: 404, code: "not_found" }, 404);
  });
}
