"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { use } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { consoleApi } from "@/lib/api/endpoints";
import { formatArea, formatDate, formatDateTime, humanize, shortId } from "@/lib/format";
import { MATCH_LABEL } from "@/lib/labels";

export default function PermitDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const permit = useQuery({ queryKey: ["permit", id], queryFn: () => consoleApi.permit(id) });
  const history = useQuery({
    queryKey: ["permit-history", id],
    queryFn: () => consoleApi.permitHistory(id),
  });
  if (permit.isPending) return <LoadingState label="Loading permit" />;
  if (permit.isError)
    return <ErrorState error={permit.error} onRetry={() => void permit.refetch()} />;
  const p = permit.data;
  const m = MATCH_LABEL[p.match_status];
  return (
    <>
      <PageHeader
        title={`Permit ${p.permit_number}`}
        description={m.hint}
        actions={
          <div className="flex gap-2">
            <Badge>{humanize(p.status)}</Badge>
            <Badge tone={m.tone}>{m.label}</Badge>
            {p.is_simulated && <Badge tone="warning">Simulated data</Badge>}
          </div>
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card aria-labelledby="permit-facts">
          <h2 id="permit-facts" className="mb-3 font-semibold">
            Permit record (as imported)
          </h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted-foreground text-xs">Valid from</dt>
              <dd>{formatDate(p.valid_from)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Valid to</dt>
              <dd>{formatDate(p.valid_to)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Sanctioned floors</dt>
              <dd>{p.sanctioned_floors}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Sanctioned footprint</dt>
              <dd>{formatArea(p.sanctioned_footprint_area_sq_m)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Sanctioned built-up area</dt>
              <dd>{formatArea(p.sanctioned_built_up_area_sq_m)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Declared plot area</dt>
              <dd>{formatArea(p.declared_plot_area_sq_m)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Declared parcel code</dt>
              <dd>{p.declared_parcel_code}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Linked parcel</dt>
              <dd>
                {p.parcel_id ? (
                  <Link
                    className="text-primary hover:underline"
                    href={`/parcels/${p.parcel_id}` as Route}
                  >
                    Parcel {shortId(p.parcel_id)}
                  </Link>
                ) : (
                  "None"
                )}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Source system</dt>
              <dd>
                {p.source_system}
                {p.source_record_ref ? ` · ${p.source_record_ref}` : ""}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Record version</dt>
              <dd>v{p.version}</dd>
            </div>
          </dl>
        </Card>
        <Card aria-labelledby="permit-history">
          <h2 id="permit-history" className="mb-3 font-semibold">
            History
          </h2>
          {history.isPending ? (
            <LoadingState />
          ) : history.isError ? (
            <ErrorState error={history.error} onRetry={() => void history.refetch()} />
          ) : history.data.length === 0 ? (
            <EmptyState title="No history recorded" />
          ) : (
            <ol className="space-y-2 text-sm">
              {history.data.map((h, i) => (
                <li key={i} className="rounded-md border p-2">
                  <p className="font-medium">
                    {humanize(String(h.event ?? h.kind ?? h.to_status ?? "change"))}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {formatDateTime(String(h.created_at ?? ""))}
                  </p>
                  {h.reason ? <p>{String(h.reason)}</p> : null}
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
    </>
  );
}
