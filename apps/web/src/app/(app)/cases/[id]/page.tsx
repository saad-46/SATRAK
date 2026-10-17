"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { use, useState } from "react";
import { useSession } from "@/components/auth/session-provider";
import { CaseStatusBadge } from "@/components/candidates/badges";
import { AssignDialog, FindingDialog, TransitionDialog } from "@/components/cases/case-actions";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorState, LoadingState, StaleNotice } from "@/components/ui/states";
import { consoleApi, type CaseTarget } from "@/lib/api/endpoints";
import { formatDateTime, humanize, shortId } from "@/lib/format";
import { CASE_STATUS, TRANSITION_LABEL } from "@/lib/labels";
import { jurisdictionName } from "@/lib/permissions";

interface TimelineEntry {
  at: string;
  title: string;
  detail?: string;
  actor?: string;
  kind: string;
}

export default function CaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me } = useSession();
  const [target, setTarget] = useState<CaseTarget | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [finding, setFinding] = useState(false);
  const [announce, setAnnounce] = useState("");

  const detail = useQuery({ queryKey: ["case", id], queryFn: () => consoleApi.case(id) });
  const history = useQuery({
    queryKey: ["case-history", id],
    queryFn: () => consoleApi.caseHistory(id),
  });

  if (detail.isPending) return <LoadingState label="Loading case" />;
  if (detail.isError && !detail.data)
    return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  const c = detail.data!;
  const a = c.actions;
  const done = (message?: string) => {
    if (message) setAnnounce(message);
  };

  const timeline: TimelineEntry[] = history.data
    ? [
        ...history.data.transitions.map((t) => ({
          at: String(t.created_at),
          kind: "transition",
          title: `${t.from_status ? humanize(String(t.from_status)) : "Opened"} → ${humanize(String(t.to_status))}`,
          detail: t.reason ? String(t.reason) : undefined,
          actor: String(t.actor_id ?? ""),
        })),
        ...history.data.assignments.map((x) => ({
          at: String(x.created_at),
          kind: "assignment",
          title: `Assigned to ${shortId(String(x.assigned_to))}`,
          detail: x.reason ? String(x.reason) : undefined,
          actor: String(x.assigned_by ?? ""),
        })),
        ...history.data.findings.map((f) => ({
          at: f.created_at,
          kind: "finding",
          title: `Case finding #${f.seq} (field inspection)`,
          detail: f.notes,
          actor: f.author_id,
        })),
      ].sort((x, y) => x.at.localeCompare(y.at))
    : [];

  return (
    <>
      <PageHeader
        title={`Case ${shortId(c.id)}`}
        description="Inspection case opened from an officer-verified candidate."
        actions={<CaseStatusBadge status={c.status} />}
      />
      {detail.isError && <StaleNotice error={detail.error} />}
      <p role="status" aria-live="polite" className="sr-only">
        {announce}
      </p>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card aria-labelledby="case-facts">
            <h2 id="case-facts" className="mb-3 font-semibold">
              Case details
            </h2>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground text-xs">Jurisdiction</dt>
                <dd>{jurisdictionName(me, c.jurisdiction_id)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs">
                  Severity (from compliance evaluation)
                </dt>
                <dd>{humanize(c.severity)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs">Priority score</dt>
                <dd>{c.priority_score}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs">Assignee</dt>
                <dd>
                  {c.assigned_to ? (
                    <span className="font-mono">{shortId(c.assigned_to)}</span>
                  ) : (
                    "Unassigned"
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs">Opened by</dt>
                <dd className="font-mono">{shortId(c.opened_by)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs">Opened</dt>
                <dd>{formatDateTime(c.created_at)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs">Source candidate</dt>
                <dd>
                  <Link
                    className="text-primary hover:underline"
                    href={`/candidates/${c.candidate_id}` as Route}
                  >
                    Candidate {shortId(c.candidate_id)}
                  </Link>
                </dd>
              </div>
              {c.parcel_id && (
                <div>
                  <dt className="text-muted-foreground text-xs">Parcel</dt>
                  <dd>
                    <Link
                      className="text-primary hover:underline"
                      href={`/parcels/${c.parcel_id}` as Route}
                    >
                      Parcel {shortId(c.parcel_id)}
                    </Link>
                  </dd>
                </div>
              )}
            </dl>
          </Card>

          <Card aria-labelledby="timeline">
            <h2 id="timeline" className="mb-3 font-semibold">
              Timeline
            </h2>
            {history.isPending ? (
              <LoadingState />
            ) : history.isError ? (
              <ErrorState error={history.error} onRetry={() => void history.refetch()} />
            ) : (
              <ol className="space-y-3">
                {timeline.map((t, i) => (
                  <li key={i} className="border-l-2 pl-3 text-sm">
                    <p className="font-medium">{t.title}</p>
                    <p className="text-muted-foreground text-xs">
                      <time dateTime={t.at}>{formatDateTime(t.at)}</time>
                      {t.actor ? ` · ${shortId(t.actor)}` : ""}
                    </p>
                    {t.detail && <p className="mt-1 whitespace-pre-wrap">{t.detail}</p>}
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>

        <Card aria-labelledby="case-actions" className="h-fit">
          <h2 id="case-actions" className="mb-1 font-semibold">
            Actions
          </h2>
          <p className="text-muted-foreground mb-3 text-xs">
            Only transitions the server would accept for you are offered. Each is validated again
            when submitted.
          </p>
          <div className="flex flex-col gap-2">
            {a.allowed_transitions.map((t) => (
              <Button
                key={t}
                variant={t === "dismissed" ? "outline" : "default"}
                onClick={() => setTarget(t)}
              >
                {TRANSITION_LABEL[t] ?? t}
              </Button>
            ))}
            {a.can_assign && (
              <Button variant="outline" onClick={() => setAssigning(true)}>
                {c.assigned_to ? "Reassign" : "Assign"}
              </Button>
            )}
            {a.can_add_finding && (
              <Button variant="outline" onClick={() => setFinding(true)}>
                Record case finding
              </Button>
            )}
            {a.allowed_transitions.length === 0 && !a.can_assign && !a.can_add_finding && (
              <p className="text-muted-foreground text-sm">
                No actions available
                {["resolved", "dismissed"].includes(c.status)
                  ? ` — the case is ${CASE_STATUS[c.status].label.toLowerCase()}`
                  : " for your role"}
                .
              </p>
            )}
          </div>
        </Card>
      </div>

      <TransitionDialog
        c={c}
        target={target}
        onClose={(m) => {
          setTarget(null);
          done(m);
        }}
      />
      <AssignDialog
        c={c}
        open={assigning}
        onClose={(m) => {
          setAssigning(false);
          done(m);
        }}
      />
      <FindingDialog
        c={c}
        open={finding}
        onClose={(m) => {
          setFinding(false);
          done(m);
        }}
      />
    </>
  );
}
