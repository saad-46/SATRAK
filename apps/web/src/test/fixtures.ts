import type {
  Candidate,
  CandidateDetail,
  Case,
  CaseDetail,
  DashboardSummary,
} from "@/lib/api/endpoints";
import { J1, USER } from "./utils";

export const CAND_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const CASE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
export const PARCEL_ID = "pppppppp-pppp-4ppp-8ppp-pppppppppppp".replace(/p/g, "b");

export const footprint = {
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

export function candidate(over: Partial<Candidate> = {}): Candidate {
  return {
    id: CAND_ID,
    jurisdiction_id: J1,
    source_type: "ai_detection",
    is_simulated: false,
    observed_on: "2026-09-01",
    change_type: "new_structure",
    footprint,
    footprint_area_sq_m: 120,
    estimated_floors: 2,
    confidence: 0.87,
    model_name: "detector",
    model_version: "1.2",
    imagery_refs: [{ source: "sat-a", reference: "scene-1", acquired_on: "2026-09-01" }],
    provenance_note: null,
    parcel_id: null,
    status: "unverified",
    created_at: "2026-09-02T10:00:00Z",
    ...over,
  };
}
export function candidateDetail(over: Partial<CandidateDetail> = {}): CandidateDetail {
  return {
    ...candidate(),
    case_id: null,
    evaluated: true,
    actions: {
      can_review: true,
      allowed_decisions: ["confirm", "reject", "request_evidence"],
      confirm_blockers: [],
      can_open_case: false,
      open_case_blockers: ["not_verified"],
    },
    ...over,
  };
}
export function caseRow(over: Partial<Case> = {}): Case {
  return {
    id: CASE_ID,
    jurisdiction_id: J1,
    candidate_id: CAND_ID,
    evaluation_id: "e",
    parcel_id: null,
    source_type: "ai_detection",
    severity: "high",
    priority_score: 80,
    status: "created",
    assigned_to: null,
    opened_by: USER,
    version: 3,
    created_at: "2026-09-03T10:00:00Z",
    updated_at: "2026-09-03T10:00:00Z",
    ...over,
  };
}
export function caseDetail(over: Partial<CaseDetail> = {}): CaseDetail {
  return {
    ...caseRow(),
    actions: {
      can_assign: true,
      can_add_finding: true,
      allowed_transitions: ["assigned", "dismissed"],
    },
    ...over,
  };
}
export function page<T>(
  items: T[],
  over: Partial<{
    page: number;
    size: number;
    total: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  }> = {},
) {
  return {
    items,
    meta: {
      page: 1,
      size: 20,
      total: items.length,
      total_pages: 1,
      has_next: false,
      has_previous: false,
      ...over,
    },
  };
}
export function summary(over: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    candidates: {
      by_status: { unverified: 4, needs_evidence: 1, confirmed: 3 },
      verified_awaiting_case: 2,
      simulated: 0,
      pending_by_jurisdiction: [{ jurisdiction_id: J1, pending: 5 }],
    },
    cases: {
      by_status: { created: 2, assigned: 1, resolved: 7 },
      unassigned_open: 2,
      open_by_jurisdiction: [{ jurisdiction_id: J1, open: 3 }],
    },
    sla: { available: false, reason: "n/a" },
    generated_at: "2026-10-11T06:00:00Z",
    ...over,
  };
}
