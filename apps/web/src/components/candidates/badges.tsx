import { Badge } from "@/components/ui/badge";
import type { CandidateStatus, CaseStatus } from "@/lib/api/endpoints";
import { CANDIDATE_STATUS, CASE_STATUS } from "@/lib/labels";

export function CandidateStatusBadge({ status }: { status: CandidateStatus }) {
  const s = CANDIDATE_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  const s = CASE_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function SimulatedBadge({ simulated }: { simulated: boolean }) {
  return simulated ? <Badge tone="warning">Simulated data</Badge> : null;
}
