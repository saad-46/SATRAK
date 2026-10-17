"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { Suspense } from "react";
import { useSession } from "@/components/auth/session-provider";
import { CaseStatusBadge } from "@/components/candidates/badges";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FilterSelect } from "@/components/ui/filter-select";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState, ErrorState, LoadingState, StaleNotice } from "@/components/ui/states";
import { consoleApi, type CaseStatus } from "@/lib/api/endpoints";
import { formatDate, humanize, shortId } from "@/lib/format";
import { CASE_STATUS } from "@/lib/labels";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { jurisdictionName } from "@/lib/permissions";

function CaseQueue() {
  const { me } = useSession();
  const url = useUrlState();
  const status = url.get("status") as CaseStatus | "";
  const unassigned = url.get("unassigned") === "true";
  const jurisdiction = url.get("jurisdiction_id");
  const q = useQuery({
    queryKey: ["cases", { status, unassigned, jurisdiction, page: url.page }],
    queryFn: () =>
      consoleApi.cases({
        page: url.page,
        size: 20,
        status: status || undefined,
        unassigned: unassigned || undefined,
        jurisdiction_id: jurisdiction || undefined,
      }),
    placeholderData: keepPreviousData,
  });
  const filtered = Boolean(status || unassigned || jurisdiction);
  return (
    <>
      <PageHeader
        title="Inspection cases"
        description="Cases are opened only from officer-verified candidates. Highest priority first."
      />
      <Card className="mb-4">
        <form
          className="flex flex-wrap items-end gap-3"
          aria-label="Filter cases"
          onSubmit={(e) => e.preventDefault()}
        >
          <FilterSelect
            label="Status"
            value={status}
            onChange={(v) => url.set({ status: v })}
            options={(Object.keys(CASE_STATUS) as CaseStatus[]).map((s) => ({
              value: s,
              label: CASE_STATUS[s].label,
            }))}
          />
          <FilterSelect
            label="Assignment"
            value={unassigned ? "true" : ""}
            onChange={(v) => url.set({ unassigned: v })}
            options={[{ value: "true", label: "Unassigned only" }]}
          />
          {(me?.jurisdictions.length ?? 0) > 1 && (
            <FilterSelect
              label="Jurisdiction"
              value={jurisdiction}
              onChange={(v) => url.set({ jurisdiction_id: v })}
              options={(me?.jurisdictions ?? []).map((j) => ({ value: j.id, label: j.name }))}
            />
          )}
          {filtered && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => url.set({ status: null, unassigned: null, jurisdiction_id: null })}
            >
              Clear filters
            </Button>
          )}
        </form>
      </Card>
      {q.isError && q.data && <StaleNotice error={q.error} />}
      {q.isPending ? (
        <LoadingState label="Loading cases" />
      ) : q.isError && !q.data ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data!.items.length === 0 ? (
        <EmptyState
          title={filtered ? "No cases match these filters" : "No cases yet"}
          hint={
            filtered
              ? "Clear the filters to see everything you can access."
              : "Verify a candidate, then open a case from it."
          }
        />
      ) : (
        <div className="space-y-3" aria-busy={q.isFetching}>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[40rem] text-sm">
              <caption className="sr-only">Inspection cases by priority</caption>
              <thead className="bg-muted/50 text-muted-foreground text-left">
                <tr>
                  {[
                    "Case",
                    "Status",
                    "Severity",
                    "Priority",
                    "Assignee",
                    "Jurisdiction",
                    "Opened",
                  ].map((h) => (
                    <th key={h} scope="col" className="p-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {q.data!.items.map((c) => (
                  <tr key={c.id} className="hover:bg-accent/30 border-t">
                    <td className="p-3">
                      <Link
                        href={`/cases/${c.id}` as Route}
                        className="text-primary font-medium hover:underline"
                      >
                        {shortId(c.id)}
                      </Link>
                    </td>
                    <td className="p-3">
                      <CaseStatusBadge status={c.status} />
                    </td>
                    <td className="p-3">{humanize(c.severity)}</td>
                    <td className="p-3 tabular-nums">{c.priority_score}</td>
                    <td className="p-3">
                      {c.assigned_to ? (
                        <span className="font-mono text-xs">{shortId(c.assigned_to)}</span>
                      ) : (
                        <span className="text-muted-foreground">Unassigned</span>
                      )}
                    </td>
                    <td className="p-3">{jurisdictionName(me, c.jurisdiction_id)}</td>
                    <td className="p-3">{formatDate(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            meta={q.data!.meta}
            onPage={(page) => url.set({ page }, { resetPage: false })}
          />
        </div>
      )}
    </>
  );
}

export default function CasesPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <CaseQueue />
    </Suspense>
  );
}
