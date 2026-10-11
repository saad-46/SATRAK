"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { Suspense } from "react";
import { useSession } from "@/components/auth/session-provider";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { FilterSelect } from "@/components/ui/filter-select";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState, ErrorState, LoadingState, StaleNotice } from "@/components/ui/states";
import { consoleApi, type PermitMatch } from "@/lib/api/endpoints";
import { formatArea, formatDate, humanize } from "@/lib/format";
import { MATCH_LABEL } from "@/lib/labels";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { jurisdictionName } from "@/lib/permissions";

function PermitList() {
  const { me } = useSession();
  const url = useUrlState();
  const match = url.get("match_status") as PermitMatch | "";
  const status = url.get("status");
  const q = useQuery({
    queryKey: ["permits", { match, status, page: url.page }],
    queryFn: () =>
      consoleApi.permits({
        page: url.page,
        size: 20,
        match_status: match || undefined,
        status: status || undefined,
      }),
    placeholderData: keepPreviousData,
  });
  return (
    <>
      <PageHeader
        title="Permits"
        description="Permit records imported from source systems. An unmatched or conflicting permit is a data-matching condition. It is never treated here as evidence that construction is unauthorised."
      />
      <Card className="mb-4">
        <form
          className="flex flex-wrap gap-3"
          aria-label="Filter permits"
          onSubmit={(e) => e.preventDefault()}
        >
          <FilterSelect
            label="Parcel match"
            value={match}
            onChange={(v) => url.set({ match_status: v })}
            options={(Object.keys(MATCH_LABEL) as PermitMatch[]).map((m) => ({
              value: m,
              label: MATCH_LABEL[m].label,
            }))}
          />
          <FilterSelect
            label="Permit status"
            value={status}
            onChange={(v) => url.set({ status: v })}
            options={["approved", "suspended", "revoked", "closed"].map((s) => ({
              value: s,
              label: humanize(s),
            }))}
          />
        </form>
      </Card>
      {q.isError && q.data && <StaleNotice error={q.error} />}
      {q.isPending ? (
        <LoadingState label="Loading permits" />
      ) : q.isError && !q.data ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data!.items.length === 0 ? (
        <EmptyState
          title="No permits found"
          hint={match || status ? "Clear the filters to see all permits." : undefined}
        />
      ) : (
        <div className="space-y-3" aria-busy={q.isFetching}>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[44rem] text-sm">
              <caption className="sr-only">Permits</caption>
              <thead className="bg-muted/50 text-muted-foreground text-left">
                <tr>
                  {[
                    "Permit",
                    "Status",
                    "Valid",
                    "Sanctioned",
                    "Declared parcel",
                    "Parcel match",
                    "Jurisdiction",
                  ].map((h) => (
                    <th key={h} scope="col" className="p-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {q.data!.items.map((p) => (
                  <tr key={p.id} className="hover:bg-accent/30 border-t">
                    <td className="p-3">
                      <Link
                        href={`/permits/${p.id}` as Route}
                        className="text-primary font-medium hover:underline"
                      >
                        {p.permit_number}
                      </Link>{" "}
                      {p.is_simulated && <Badge tone="warning">Simulated data</Badge>}
                    </td>
                    <td className="p-3">{humanize(p.status)}</td>
                    <td className="p-3">
                      {formatDate(p.valid_from)} – {formatDate(p.valid_to)}
                    </td>
                    <td className="p-3">
                      {p.sanctioned_floors} fl · {formatArea(p.sanctioned_footprint_area_sq_m)}
                    </td>
                    <td className="p-3">{p.declared_parcel_code}</td>
                    <td className="p-3">
                      <Badge tone={MATCH_LABEL[p.match_status].tone}>
                        {MATCH_LABEL[p.match_status].label}
                      </Badge>
                    </td>
                    <td className="p-3">{jurisdictionName(me, p.jurisdiction_id)}</td>
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

export default function PermitsPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <PermitList />
    </Suspense>
  );
}
