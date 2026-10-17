"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { Suspense } from "react";
import { CandidateStatusBadge, SimulatedBadge } from "@/components/candidates/badges";
import { useSession } from "@/components/auth/session-provider";
import { Card } from "@/components/ui/card";
import { FilterSelect } from "@/components/ui/filter-select";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState, ErrorState, LoadingState, StaleNotice } from "@/components/ui/states";
import { Button } from "@/components/ui/button";
import { consoleApi, type CandidateSource, type CandidateStatus } from "@/lib/api/endpoints";
import { formatArea, formatConfidence, formatDate, humanize } from "@/lib/format";
import { CANDIDATE_STATUS, SOURCE_LABEL } from "@/lib/labels";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { jurisdictionName } from "@/lib/permissions";

const PAGE_SIZE = 20;

function CandidateQueue() {
  const { me } = useSession();
  const url = useUrlState();
  const status = url.get("status") as CandidateStatus | "";
  const source = url.get("source_type") as CandidateSource | "";
  const jurisdiction = url.get("jurisdiction_id");

  const q = useQuery({
    queryKey: ["candidates", { status, source, jurisdiction, page: url.page }],
    queryFn: () =>
      consoleApi.candidates({
        page: url.page,
        size: PAGE_SIZE,
        status: status || undefined,
        source_type: source || undefined,
        jurisdiction_id: jurisdiction || undefined,
      }),
    placeholderData: keepPreviousData,
  });

  const filtered = Boolean(status || source || jurisdiction);

  return (
    <>
      <PageHeader
        title="Candidates"
        description="Candidates are unverified leads from AI detection, reports or imports. A confidence score is the model's own number, not proof. Only an authorised officer's verification makes a candidate eligible for an inspection case."
      />
      <Card className="mb-4">
        <form
          className="flex flex-wrap items-end gap-3"
          aria-label="Filter candidates"
          onSubmit={(e) => e.preventDefault()}
        >
          <FilterSelect
            label="Review status"
            value={status}
            onChange={(v) => url.set({ status: v })}
            options={(Object.keys(CANDIDATE_STATUS) as CandidateStatus[]).map((s) => ({
              value: s,
              label: CANDIDATE_STATUS[s].label,
            }))}
          />
          <FilterSelect
            label="Source"
            value={source}
            onChange={(v) => url.set({ source_type: v })}
            options={Object.entries(SOURCE_LABEL).map(([value, label]) => ({ value, label }))}
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
              onClick={() => url.set({ status: null, source_type: null, jurisdiction_id: null })}
            >
              Clear filters
            </Button>
          )}
        </form>
      </Card>

      {q.isError && q.data && <StaleNotice error={q.error} />}
      {q.isPending ? (
        <LoadingState label="Loading candidates" />
      ) : q.isError && !q.data ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data!.items.length === 0 ? (
        <EmptyState
          title={filtered ? "No candidates match these filters" : "No candidates yet"}
          hint={
            filtered
              ? "Clear the filters to see everything you can access."
              : "New detections appear here once they are ingested."
          }
        />
      ) : (
        <div className="space-y-3" aria-busy={q.isFetching}>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[40rem] text-sm">
              <caption className="sr-only">Construction change candidates, newest first</caption>
              <thead className="bg-muted/50 text-muted-foreground text-left">
                <tr>
                  <th scope="col" className="p-3 font-medium">
                    Observed
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Change
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Source
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Model score
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Footprint
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Jurisdiction
                  </th>
                  <th scope="col" className="p-3 font-medium">
                    Review status
                  </th>
                </tr>
              </thead>
              <tbody>
                {q.data!.items.map((c) => (
                  <tr key={c.id} className="hover:bg-accent/30 border-t">
                    <td className="p-3">
                      <Link
                        href={`/candidates/${c.id}` as Route}
                        className="text-primary font-medium underline-offset-4 hover:underline"
                      >
                        {formatDate(c.observed_on)}
                      </Link>
                    </td>
                    <td className="p-3">{humanize(c.change_type)}</td>
                    <td className="p-3">
                      {SOURCE_LABEL[c.source_type] ?? c.source_type}{" "}
                      <SimulatedBadge simulated={c.is_simulated} />
                    </td>
                    <td className="p-3">{formatConfidence(c.confidence)}</td>
                    <td className="p-3">{formatArea(c.footprint_area_sq_m)}</td>
                    <td className="p-3">{jurisdictionName(me, c.jurisdiction_id)}</td>
                    <td className="p-3">
                      <CandidateStatusBadge status={c.status} />
                    </td>
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

export default function CandidatesPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <CandidateQueue />
    </Suspense>
  );
}
