import type { Tone } from "@/components/ui/badge";
import type { CandidateStatus, CaseStatus, PermitMatch, ReviewDecision } from "@/lib/api/endpoints";

/**
 * Terminology (ADR-0014 Amendment 1): AI output is a "candidate", never a "finding" or a
 * "violation". Only an officer-verified candidate may open an inspection case, and "case finding"
 * is the field inspector's site-visit record.
 */
export const CANDIDATE_STATUS: Record<CandidateStatus, { label: string; tone: Tone }> = {
  unverified: { label: "Unverified", tone: "warning" },
  needs_evidence: { label: "Evidence requested", tone: "warning" },
  confirmed: { label: "Verified by officer", tone: "success" },
  rejected: { label: "Rejected by officer", tone: "neutral" },
};

export const CASE_STATUS: Record<CaseStatus, { label: string; tone: Tone }> = {
  created: { label: "Created", tone: "info" },
  assigned: { label: "Assigned", tone: "info" },
  under_investigation: { label: "Under investigation", tone: "info" },
  notice_issued: { label: "Notice issued", tone: "warning" },
  resolved: { label: "Resolved", tone: "success" },
  dismissed: { label: "Dismissed", tone: "neutral" },
};

export const DECISION_LABEL: Record<ReviewDecision, string> = {
  confirm: "Verify candidate",
  reject: "Reject candidate",
  request_evidence: "Request more evidence",
};

export const TRANSITION_LABEL: Record<string, string> = {
  assigned: "Mark assigned",
  under_investigation: "Start investigation",
  notice_issued: "Issue notice",
  resolved: "Resolve case",
  dismissed: "Dismiss case",
};

export const SOURCE_LABEL: Record<string, string> = {
  ai_detection: "AI detection",
  manual_report: "Manual report",
  imported: "Imported",
};

export const MATCH_LABEL: Record<PermitMatch, { label: string; tone: Tone; hint: string }> = {
  matched: { label: "Matched to parcel", tone: "success", hint: "Linked to a stored parcel." },
  unmatched: {
    label: "Unmatched",
    tone: "warning",
    hint: "No parcel matches the declared code. This is a data gap, not evidence of a violation.",
  },
  conflict: {
    label: "Match conflict",
    tone: "danger",
    hint: "More than one parcel could match; an authorised user must resolve it.",
  },
};

export const OPEN_CASE_STATUSES: CaseStatus[] = [
  "created",
  "assigned",
  "under_investigation",
  "notice_issued",
];
