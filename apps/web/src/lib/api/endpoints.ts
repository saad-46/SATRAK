import { apiFetch } from "./client";
import type { PageResponse } from "./types";

/** Foundation-level API calls (health / version). */
export interface VersionInfo {
  name: string;
  version: string;
  environment: string;
}
export interface HealthStatus {
  status: string;
}

export const api = {
  health: () => apiFetch<HealthStatus>({ path: "/api/v1/health/live" }),
  version: () => apiFetch<VersionInfo>({ path: "/api/v1/meta/version" }),
};

// ---------------------------------------------------------------- shared vocabulary
export type CandidateStatus = "unverified" | "needs_evidence" | "confirmed" | "rejected";
export type CandidateSource = "ai_detection" | "manual_report" | "imported";
export type ReviewDecision = "confirm" | "reject" | "request_evidence";
export type CaseStatus =
  "created" | "assigned" | "under_investigation" | "notice_issued" | "resolved" | "dismissed";
export type CaseTarget = Exclude<CaseStatus, "created">;
export type GeoJsonGeometry = { type: string; coordinates: unknown };

// ---------------------------------------------------------------- /me, dashboard, activity
export interface Jurisdiction {
  id: string;
  code: string;
  name: string;
  level: string;
}
export interface Me {
  user_id: string;
  status: string;
  /** permission -> jurisdiction ids where the caller holds it */
  permissions: Record<string, string[]>;
  jurisdictions: Jurisdiction[];
}
export interface CandidateDashboard {
  by_status: Record<string, number>;
  verified_awaiting_case: number;
  simulated: number;
  pending_by_jurisdiction: Array<{ jurisdiction_id: string; pending: number }>;
}
export interface CaseDashboard {
  by_status: Record<string, number>;
  unassigned_open: number;
  open_by_jurisdiction: Array<{ jurisdiction_id: string; open: number }>;
}
export interface DashboardSummary {
  candidates: CandidateDashboard | null;
  cases: CaseDashboard | null;
  sla: { available: boolean; reason?: string };
  generated_at: string;
}
export interface ActivityItem {
  kind: string;
  occurred_at: string;
  actor_id: string | null;
  entity_type: string;
  entity_id: string;
  jurisdiction_id: string;
  summary: string;
}
export interface Activity {
  items: ActivityItem[];
  sources: string[];
}

// ---------------------------------------------------------------- candidates
export interface ImageryRef {
  source?: string;
  reference?: string;
  acquired_on?: string;
}
export interface Candidate {
  id: string;
  jurisdiction_id: string;
  source_type: CandidateSource;
  is_simulated: boolean;
  observed_on: string;
  change_type: string;
  footprint: GeoJsonGeometry;
  footprint_area_sq_m: number;
  estimated_floors: number | null;
  confidence: number | null;
  model_name: string | null;
  model_version: string | null;
  imagery_refs: ImageryRef[];
  provenance_note: string | null;
  parcel_id: string | null;
  status: CandidateStatus;
  created_at: string;
}
export interface CandidateActions {
  can_review: boolean;
  allowed_decisions: ReviewDecision[];
  confirm_blockers: Array<"evaluation" | "provenance">;
  can_open_case: boolean;
  open_case_blockers: string[];
}
export interface CandidateDetail extends Candidate {
  case_id: string | null;
  evaluated: boolean;
  actions: CandidateActions;
}
export interface Evaluation {
  id: string;
  seq: number;
  classification: string;
  severity: string;
  failed_rules: string[];
  result: Record<string, unknown>;
  parcel_id: string | null;
  evaluated_by: string;
  created_at: string;
}
export interface Review {
  seq: number;
  decision: string;
  resulting_status: string;
  justification: string;
  evidence_refs: Array<Record<string, unknown>>;
  is_reversal: boolean;
  reviewer_id: string;
  created_at: string;
}
export interface ReviewInput {
  decision: ReviewDecision;
  justification: string;
  evidence_refs?: Array<Record<string, unknown>>;
}
export interface CandidateFilters {
  page?: number;
  size?: number;
  sort?: string;
  status?: CandidateStatus;
  source_type?: CandidateSource;
  jurisdiction_id?: string;
  parcel_id?: string;
}

// ---------------------------------------------------------------- cases
export interface Case {
  id: string;
  jurisdiction_id: string;
  candidate_id: string;
  evaluation_id: string;
  parcel_id: string | null;
  source_type: string;
  severity: string;
  priority_score: number;
  status: CaseStatus;
  assigned_to: string | null;
  opened_by: string;
  version: number;
  created_at: string;
  updated_at: string;
}
export interface CaseActions {
  can_assign: boolean;
  can_add_finding: boolean;
  allowed_transitions: CaseTarget[];
}
export interface CaseDetail extends Case {
  actions: CaseActions;
}
export interface CaseFinding {
  seq: number;
  author_id: string;
  notes: string;
  measurements: Record<string, unknown>;
  evidence: Array<Record<string, unknown>>;
  created_at: string;
}
export interface CaseHistory {
  transitions: Array<Record<string, unknown>>;
  assignments: Array<Record<string, unknown>>;
  findings: CaseFinding[];
}
export interface CaseFilters {
  page?: number;
  size?: number;
  sort?: string;
  status?: CaseStatus;
  assigned_to?: string;
  unassigned?: boolean;
  jurisdiction_id?: string;
  candidate_id?: string;
  parcel_id?: string;
}
export interface FindingInput {
  notes: string;
  measurements?: Record<string, string | number>;
  evidence?: Array<{ kind: string; reference: string; sha256: string; captured_at: string }>;
}

// ---------------------------------------------------------------- parcels / properties / permits
export interface Parcel {
  id: string;
  jurisdiction_id: string;
  code: string;
  current_version: number;
  area_sq_m: number;
  topology_status: "clean" | "overlaps_neighbour";
  topology_detail: Record<string, unknown>;
  geometry: GeoJsonGeometry;
  created_at: string;
  updated_at: string;
}
export interface GeometryVersion {
  version: number;
  area_sq_m: number;
  topology_status: string;
  topology_detail: Record<string, unknown>;
  reason: string | null;
  recorded_by: string;
  created_at: string;
  geometry: GeoJsonGeometry;
}
export interface Property {
  id: string;
  jurisdiction_id: string;
  parcel_id: string;
  property_ref: string;
  land_use: string;
  address_text: string | null;
  created_at: string;
}
export type PermitMatch = "matched" | "unmatched" | "conflict";
export interface Permit {
  id: string;
  jurisdiction_id: string;
  permit_number: string;
  status: string;
  valid_from: string;
  valid_to: string | null;
  sanctioned_floors: number;
  sanctioned_footprint_area_sq_m: number;
  sanctioned_built_up_area_sq_m: number | null;
  declared_plot_area_sq_m: number | null;
  declared_parcel_code: string;
  parcel_id: string | null;
  match_status: PermitMatch;
  match_detail: Record<string, unknown>;
  source_system: string;
  source_record_ref: string | null;
  is_simulated: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}
export interface ListFilters {
  page?: number;
  size?: number;
  sort?: string;
  parcel_id?: string;
  status?: string;
  topology_status?: "clean" | "overlaps_neighbour";
}

const base = "/api/v1";
const q = (o: object) => o as Record<string, string | number | boolean | undefined>;

export const consoleApi = {
  me: () => apiFetch<Me>({ path: `${base}/me` }),
  dashboard: () => apiFetch<DashboardSummary>({ path: `${base}/dashboard/summary` }),
  activity: (limit = 20) => apiFetch<Activity>({ path: `${base}/activity`, query: { limit } }),

  candidates: (f: CandidateFilters) =>
    apiFetch<PageResponse<Candidate>>({ path: `${base}/candidates`, query: q(f) }),
  candidate: (id: string) => apiFetch<CandidateDetail>({ path: `${base}/candidates/${id}` }),
  evaluations: (id: string) =>
    apiFetch<Evaluation[]>({ path: `${base}/candidates/${id}/evaluations` }),
  reviews: (id: string) => apiFetch<Review[]>({ path: `${base}/candidates/${id}/reviews` }),
  submitReview: (id: string, input: ReviewInput) =>
    apiFetch<Review>({
      path: `${base}/candidates/${id}/reviews`,
      method: "POST",
      json: { evidence_refs: [], ...input },
    }),
  openCase: (candidateId: string) =>
    apiFetch<Case>({ path: `${base}/cases`, method: "POST", json: { candidate_id: candidateId } }),

  cases: (f: CaseFilters) => apiFetch<PageResponse<Case>>({ path: `${base}/cases`, query: q(f) }),
  case: (id: string) => apiFetch<CaseDetail>({ path: `${base}/cases/${id}` }),
  caseHistory: (id: string) => apiFetch<CaseHistory>({ path: `${base}/cases/${id}/history` }),
  transition: (id: string, target: CaseTarget, expected_version: number, reason?: string) =>
    apiFetch<Case>({
      path: `${base}/cases/${id}/transitions`,
      method: "POST",
      json: { target, expected_version, reason: reason || null },
    }),
  assign: (id: string, assignee_id: string, expected_version: number, reason?: string) =>
    apiFetch<Case>({
      path: `${base}/cases/${id}/assignment`,
      method: "POST",
      json: { assignee_id, expected_version, reason: reason || null },
    }),
  addFinding: (id: string, input: FindingInput) =>
    apiFetch<CaseFinding>({
      path: `${base}/cases/${id}/findings`,
      method: "POST",
      json: { measurements: {}, evidence: [], ...input },
    }),

  parcels: (f: ListFilters) =>
    apiFetch<PageResponse<Parcel>>({ path: `${base}/parcels`, query: q(f) }),
  parcel: (id: string) => apiFetch<Parcel>({ path: `${base}/parcels/${id}` }),
  parcelVersions: (id: string) =>
    apiFetch<GeometryVersion[]>({ path: `${base}/parcels/${id}/geometry-versions` }),
  properties: (f: ListFilters) =>
    apiFetch<PageResponse<Property>>({ path: `${base}/properties`, query: q(f) }),
  permits: (f: ListFilters & { match_status?: PermitMatch }) =>
    apiFetch<PageResponse<Permit>>({ path: `${base}/permits`, query: q(f) }),
  permit: (id: string) => apiFetch<Permit>({ path: `${base}/permits/${id}` }),
  permitHistory: (id: string) =>
    apiFetch<Array<Record<string, unknown>>>({ path: `${base}/permits/${id}/history` }),
};
