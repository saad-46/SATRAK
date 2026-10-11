"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { use, useState } from "react";
import { useSession } from "@/components/auth/session-provider";
import { CandidateStatusBadge, SimulatedBadge } from "@/components/candidates/badges";
import { OpenCaseButton } from "@/components/candidates/open-case-button";
import { ReviewDialog } from "@/components/candidates/review-dialog";
import { GeometryView } from "@/components/geo/geometry-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState, StaleNotice } from "@/components/ui/states";
import { consoleApi, type ReviewDecision } from "@/lib/api/endpoints";
import {
  formatArea,
  formatConfidence,
  formatDate,
  formatDateTime,
  humanize,
  shortId,
} from "@/lib/format";
import { DECISION_LABEL, MATCH_LABEL, SOURCE_LABEL } from "@/lib/labels";
import { jurisdictionName } from "@/lib/permissions";

const BLOCKER_TEXT: Record<string, string> = {
  evaluation: "Verification needs a compliance evaluation of this candidate first.",
  provenance: "Verification needs imagery references or a provenance note on the candidate.",
  no_permission: "You do not hold the permission to open cases here.",
  not_evaluated: "The candidate needs a compliance evaluation before a case can be opened.",
  not_verified: "Only an officer-verified candidate can open an inspection case.",
  case_exists: "A case already exists for this candidate.",
};

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

export default function CandidateDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me, can } = useSession();
  const [decision, setDecision] = useState<ReviewDecision | null>(null);
  const [announce, setAnnounce] = useState("");

  const detail = useQuery({ queryKey: ["candidate", id], queryFn: () => consoleApi.candidate(id) });
  const evaluations = useQuery({
    queryKey: ["candidate-evaluations", id],
    queryFn: () => consoleApi.evaluations(id),
  });
  const reviews = useQuery({
    queryKey: ["candidate-reviews", id],
    queryFn: () => consoleApi.reviews(id),
  });
  const c = detail.data;
  const parcelId = c?.parcel_id ?? null;
  const parcel = useQuery({
    queryKey: ["parcel", parcelId],
    queryFn: () => consoleApi.parcel(parcelId!),
    enabled: Boolean(parcelId) && can("parcel:read"),
  });
  const permits = useQuery({
    queryKey: ["permits", { parcel: parcelId }],
    queryFn: () => consoleApi.permits({ parcel_id: parcelId!, size: 20 }),
    enabled: Boolean(parcelId) && can("permit:read"),
  });

  if (detail.isPending) return <LoadingState label="Loading candidate" />;
  if (detail.isError && !c)
    return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  const cand = c!;
  const a = cand.actions;
  const latestEval = evaluations.data?.[evaluations.data.length - 1];

  return (
    <>
      <PageHeader
        title={`Candidate ${shortId(cand.id)}`}
        description="An unverified lead. Observed facts, model inferences and officer conclusions are kept separate below."
        actions={
          <div className="flex items-center gap-2">
            <CandidateStatusBadge status={cand.status} />
            <SimulatedBadge simulated={cand.is_simulated} />
          </div>
        }
      />
      {detail.isError && <StaleNotice error={detail.error} />}
      <p role="status" aria-live="polite" className="sr-only">
        {announce}
      </p>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card aria-labelledby="facts">
            <h2 id="facts" className="mb-3 font-semibold">
              Observed facts and stored data
            </h2>
            <dl className="grid gap-3 sm:grid-cols-2">
              <Fact label="Observed on">{formatDate(cand.observed_on)}</Fact>
              <Fact label="Source">{SOURCE_LABEL[cand.source_type] ?? cand.source_type}</Fact>
              <Fact label="Change type (as recorded)">{humanize(cand.change_type)}</Fact>
              <Fact label="Footprint area (computed from stored geometry)">
                {formatArea(cand.footprint_area_sq_m)}
              </Fact>
              <Fact label="Jurisdiction">{jurisdictionName(me, cand.jurisdiction_id)}</Fact>
              <Fact label="Ingested">{formatDateTime(cand.created_at)}</Fact>
            </dl>
            <div className="mt-4">
              <GeometryView
                label="Candidate footprint and linked parcel boundary"
                layers={[
                  { key: "footprint", name: "Candidate footprint", geometry: cand.footprint },
                  ...(parcel.data
                    ? [
                        {
                          key: "parcel",
                          name: `Parcel ${parcel.data.code}`,
                          geometry: parcel.data.geometry,
                        },
                      ]
                    : []),
                ]}
              />
            </div>
          </Card>

          <Card aria-labelledby="inference">
            <h2 id="inference" className="mb-1 font-semibold">
              Model inference
            </h2>
            <p className="text-muted-foreground mb-3 text-xs">
              Output of an automated model or an external report. It is not verified and not proof.
            </p>
            <dl className="grid gap-3 sm:grid-cols-2">
              <Fact label="Model score (not a probability of violation)">
                {formatConfidence(cand.confidence)}
              </Fact>
              <Fact label="Estimated floors">{cand.estimated_floors ?? "not provided"}</Fact>
              <Fact label="Model">
                {cand.model_name
                  ? `${cand.model_name} ${cand.model_version ?? ""}`
                  : "not provided"}
              </Fact>
              <Fact label="Provenance note">{cand.provenance_note ?? "none recorded"}</Fact>
            </dl>
            <h3 className="mt-4 text-sm font-medium">Imagery references</h3>
            {cand.imagery_refs.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No imagery references are stored. No before/after imagery is shown because none is
                available.
              </p>
            ) : (
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                {cand.imagery_refs.map((r, i) => (
                  <li key={i}>
                    {r.source ?? "source unknown"} · {r.reference ?? "no reference"} · acquired{" "}
                    {formatDate(r.acquired_on)}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card aria-labelledby="evals">
            <h2 id="evals" className="mb-1 font-semibold">
              Compliance evaluations
            </h2>
            <p className="text-muted-foreground mb-3 text-xs">
              Rule-engine output comparing the candidate with permit and parcel data. A missing or
              unmatched permit is a data condition, not a conclusion that construction is
              unauthorised.
            </p>
            {evaluations.isPending ? (
              <LoadingState />
            ) : evaluations.isError ? (
              <ErrorState error={evaluations.error} onRetry={() => void evaluations.refetch()} />
            ) : evaluations.data.length === 0 ? (
              <EmptyState title="Not evaluated yet" />
            ) : (
              <ol className="space-y-2">
                {evaluations.data.map((e) => (
                  <li key={e.id} className="rounded-md border p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <strong>
                        #{e.seq} {humanize(e.classification)}
                      </strong>
                      <Badge tone="info">Severity: {humanize(e.severity)}</Badge>
                      <time
                        dateTime={e.created_at}
                        className="text-muted-foreground ml-auto text-xs"
                      >
                        {formatDateTime(e.created_at)}
                      </time>
                    </div>
                    {e.failed_rules.length > 0 && (
                      <p className="text-muted-foreground mt-1">
                        Rules not satisfied: {e.failed_rules.map(humanize).join(", ")}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </Card>

          <Card aria-labelledby="permits">
            <h2 id="permits" className="mb-3 font-semibold">
              Permit context
            </h2>
            {!parcelId ? (
              <p className="text-muted-foreground text-sm">
                This candidate is not linked to a stored parcel, so no permit context can be shown.
              </p>
            ) : !can("permit:read") ? (
              <p className="text-muted-foreground text-sm">
                Permit data is not available for your role.
              </p>
            ) : permits.isPending ? (
              <LoadingState />
            ) : permits.isError ? (
              <ErrorState error={permits.error} onRetry={() => void permits.refetch()} />
            ) : permits.data.items.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No permit records are linked to this parcel. That is a data gap and does not by
                itself mean the work is unauthorised.
              </p>
            ) : (
              <ul className="space-y-2">
                {permits.data.items.map((p) => (
                  <li key={p.id} className="rounded-md border p-3 text-sm">
                    <Link
                      href={`/permits/${p.id}` as Route}
                      className="text-primary font-medium hover:underline"
                    >
                      {p.permit_number}
                    </Link>{" "}
                    <Badge>{humanize(p.status)}</Badge>{" "}
                    <Badge tone={MATCH_LABEL[p.match_status].tone}>
                      {MATCH_LABEL[p.match_status].label}
                    </Badge>{" "}
                    {p.is_simulated && <Badge tone="warning">Simulated data</Badge>}
                    <p className="text-muted-foreground mt-1">
                      Sanctioned {p.sanctioned_floors} floors, footprint{" "}
                      {formatArea(p.sanctioned_footprint_area_sq_m)}; valid{" "}
                      {formatDate(p.valid_from)} – {formatDate(p.valid_to)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            {parcelId && can("parcel:read") && (
              <p className="mt-3 text-sm">
                <Link
                  href={`/parcels/${parcelId}` as Route}
                  className="text-primary hover:underline"
                >
                  Open parcel {parcel.data?.code ?? shortId(parcelId)}
                </Link>
              </p>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card aria-labelledby="decision">
            <h2 id="decision" className="mb-1 font-semibold">
              Officer conclusion
            </h2>
            <p className="text-muted-foreground mb-3 text-xs">
              Decisions are recorded under your identity with a server timestamp.
            </p>
            {a.can_review ? (
              <div className="flex flex-col gap-2">
                {(["confirm", "reject", "request_evidence"] as ReviewDecision[]).map((d) =>
                  a.allowed_decisions.includes(d) ? (
                    <Button
                      key={d}
                      variant={d === "confirm" ? "default" : "outline"}
                      onClick={() => setDecision(d)}
                    >
                      {DECISION_LABEL[d]}
                    </Button>
                  ) : null,
                )}
                {a.allowed_decisions.length === 0 && (
                  <p className="text-muted-foreground text-sm">
                    No decision is available: this candidate already has an open case. Resolve or
                    dismiss the case first.
                  </p>
                )}
                {a.confirm_blockers.length > 0 && (
                  <ul className="text-muted-foreground list-disc pl-5 text-sm">
                    {a.confirm_blockers.map((b) => (
                      <li key={b}>{BLOCKER_TEXT[b] ?? b}</li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">
                You can view this candidate but your role does not include verification here.
              </p>
            )}
          </Card>

          <Card aria-labelledby="case">
            <h2 id="case" className="mb-2 font-semibold">
              Inspection case
            </h2>
            {cand.case_id ? (
              <Link
                href={`/cases/${cand.case_id}` as Route}
                className="text-primary text-sm hover:underline"
              >
                Open case {shortId(cand.case_id)}
              </Link>
            ) : a.can_open_case ? (
              <OpenCaseButton candidateId={cand.id} />
            ) : (
              <ul className="text-muted-foreground list-disc pl-5 text-sm">
                {a.open_case_blockers.map((b) => (
                  <li key={b}>{BLOCKER_TEXT[b] ?? humanize(b)}</li>
                ))}
              </ul>
            )}
          </Card>

          <Card aria-labelledby="history">
            <h2 id="history" className="mb-3 font-semibold">
              Review history
            </h2>
            {reviews.isPending ? (
              <LoadingState />
            ) : reviews.isError ? (
              <ErrorState error={reviews.error} onRetry={() => void reviews.refetch()} />
            ) : reviews.data.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No officer has reviewed this candidate.
              </p>
            ) : (
              <ol className="space-y-3">
                {reviews.data.map((r) => (
                  <li key={r.seq} className="text-sm">
                    <p>
                      <strong>{humanize(r.decision)}</strong> → {humanize(r.resulting_status)}
                      {r.is_reversal && " (reversal)"}
                    </p>
                    <p className="text-muted-foreground text-xs">
                      Officer {shortId(r.reviewer_id)} · {formatDateTime(r.created_at)}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap">{r.justification}</p>
                  </li>
                ))}
              </ol>
            )}
          </Card>
          {latestEval && (
            <p className="text-muted-foreground text-xs">
              Latest evaluation #{latestEval.seq}, {formatDateTime(latestEval.created_at)}
            </p>
          )}
        </div>
      </div>

      <ReviewDialog
        candidateId={cand.id}
        decision={decision}
        onClose={(result) => {
          setDecision(null);
          if (result)
            setAnnounce(
              `Decision recorded: ${DECISION_LABEL[result.decision]}. Status is now ${humanize(result.status)}.`,
            );
        }}
      />
    </>
  );
}
