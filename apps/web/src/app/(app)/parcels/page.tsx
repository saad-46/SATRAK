"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { Suspense } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { FilterSelect } from "@/components/ui/filter-select";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState, ErrorState, LoadingState, StaleNotice } from "@/components/ui/states";
import { consoleApi } from "@/lib/api/endpoints";
import { useSession } from "@/components/auth/session-provider";
import { formatArea } from "@/lib/format";
import { useUrlState } from "@/lib/hooks/use-url-state";
import { jurisdictionName } from "@/lib/permissions";

function ParcelList() {
  const { me } = useSession();
  const url = useUrlState();
  const topology = url.get("topology_status") as "clean" | "overlaps_neighbour" | "";
  const q = useQuery({
    queryKey: ["parcels", { topology, page: url.page }],
    queryFn: () =>
      consoleApi.parcels({ page: url.page, size: 20, topology_status: topology || undefined }),
    placeholderData: keepPreviousData,
  });
  return (
    <>
      <PageHeader
        title="Parcels & properties"
        description="Stored parcel boundaries (EPSG:4326) with versioned geometry. A topology flag marks a boundary that overlaps a neighbour; it is a data-quality signal, not a legal finding."
      />
      <Card className="mb-4">
        <form aria-label="Filter parcels" onSubmit={(e) => e.preventDefault()}>
          <FilterSelect
            label="Topology"
            value={topology}
            onChange={(v) => url.set({ topology_status: v })}
            options={[
              { value: "clean", label: "Clean" },
              { value: "overlaps_neighbour", label: "Overlaps a neighbour" },
            ]}
          />
        </form>
      </Card>
      {q.isError && q.data && <StaleNotice error={q.error} />}
      {q.isPending ? (
        <LoadingState label="Loading parcels" />
      ) : q.isError && !q.data ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data!.items.length === 0 ? (
        <EmptyState
          title="No parcels found"
          hint={topology ? "Clear the filter to see all parcels." : undefined}
        />
      ) : (
        <div className="space-y-3" aria-busy={q.isFetching}>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[32rem] text-sm">
              <caption className="sr-only">Parcels</caption>
              <thead className="bg-muted/50 text-muted-foreground text-left">
                <tr>
                  {["Parcel code", "Area", "Geometry version", "Topology", "Jurisdiction"].map(
                    (h) => (
                      <th key={h} scope="col" className="p-3 font-medium">
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {q.data!.items.map((p) => (
                  <tr key={p.id} className="hover:bg-accent/30 border-t">
                    <td className="p-3">
                      <Link
                        href={`/parcels/${p.id}` as Route}
                        className="text-primary font-medium hover:underline"
                      >
                        {p.code}
                      </Link>
                    </td>
                    <td className="p-3">{formatArea(p.area_sq_m)}</td>
                    <td className="p-3 tabular-nums">v{p.current_version}</td>
                    <td className="p-3">
                      {p.topology_status === "clean" ? (
                        <Badge tone="success">Clean</Badge>
                      ) : (
                        <Badge tone="warning">Overlaps a neighbour</Badge>
                      )}
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

export default function ParcelsPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <ParcelList />
    </Suspense>
  );
}
