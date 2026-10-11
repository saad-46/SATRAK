"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { use } from "react";
import { useSession } from "@/components/auth/session-provider";
import { CandidateStatusBadge, CaseStatusBadge } from "@/components/candidates/badges";
import { GeometryView } from "@/components/geo/geometry-view";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { consoleApi } from "@/lib/api/endpoints";
import { formatArea, formatDate, formatDateTime, humanize, shortId } from "@/lib/format";
import { MATCH_LABEL } from "@/lib/labels";
import { jurisdictionName } from "@/lib/permissions";

function Section<T>({
  title,
  query,
  empty,
  children,
}: {
  title: string;
  query: {
    isPending: boolean;
    isError: boolean;
    error: unknown;
    data?: T[];
    refetch: () => unknown;
  };
  empty: string;
  children: (rows: T[]) => React.ReactNode;
}) {
  return (
    <Card>
      <h2 className="mb-3 font-semibold">{title}</h2>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (query.data ?? []).length === 0 ? (
        <EmptyState title={empty} />
      ) : (
        children(query.data!)
      )}
    </Card>
  );
}

export default function ParcelDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me, can } = useSession();
  const parcel = useQuery({ queryKey: ["parcel", id], queryFn: () => consoleApi.parcel(id) });
  const versions = useQuery({
    queryKey: ["parcel-versions", id],
    queryFn: () => consoleApi.parcelVersions(id),
  });
  const props = useQuery({
    queryKey: ["properties", { parcel: id }],
    queryFn: async () => (await consoleApi.properties({ parcel_id: id, size: 50 })).items,
    enabled: can("property:read"),
  });
  const permits = useQuery({
    queryKey: ["permits", { parcel: id }],
    queryFn: async () => (await consoleApi.permits({ parcel_id: id, size: 50 })).items,
    enabled: can("permit:read"),
  });
  const candidates = useQuery({
    queryKey: ["candidates", { parcel: id }],
    queryFn: async () => (await consoleApi.candidates({ parcel_id: id, size: 50 })).items,
    enabled: can("candidate:read"),
  });
  const cases = useQuery({
    queryKey: ["cases", { parcel: id }],
    queryFn: async () => (await consoleApi.cases({ parcel_id: id, size: 50 })).items,
    enabled: can("case:read"),
  });

  if (parcel.isPending) return <LoadingState label="Loading parcel" />;
  if (parcel.isError)
    return <ErrorState error={parcel.error} onRetry={() => void parcel.refetch()} />;
  const p = parcel.data;

  return (
    <>
      <PageHeader
        title={`Parcel ${p.code}`}
        description="Stored boundary and everything linked to it. Linked records are context; none of them is by itself a finding."
        actions={
          p.topology_status === "clean" ? (
            <Badge tone="success">Topology clean</Badge>
          ) : (
            <Badge tone="warning">Overlaps a neighbour</Badge>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 font-semibold">Current boundary</h2>
          <dl className="mb-3 grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted-foreground text-xs">Area (computed)</dt>
              <dd>{formatArea(p.area_sq_m)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Geometry version</dt>
              <dd>v{p.current_version}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Jurisdiction</dt>
              <dd>{jurisdictionName(me, p.jurisdiction_id)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Updated</dt>
              <dd>{formatDateTime(p.updated_at)}</dd>
            </div>
          </dl>
          <GeometryView
            label={`Boundary of parcel ${p.code}`}
            layers={[
              {
                key: "parcel",
                name: `Parcel ${p.code} v${p.current_version}`,
                geometry: p.geometry,
              },
            ]}
          />
        </Card>

        <Section title="Geometry versions" query={versions} empty="No geometry history">
          {(rows) => (
            <ol className="space-y-2 text-sm">
              {[...rows].reverse().map((v) => (
                <li key={v.version} className="rounded-md border p-2">
                  <strong>v{v.version}</strong> · {formatArea(v.area_sq_m)} ·{" "}
                  {humanize(v.topology_status)}
                  <p className="text-muted-foreground text-xs">
                    {formatDateTime(v.created_at)} · recorded by {shortId(v.recorded_by)}
                  </p>
                  {v.reason && <p>{v.reason}</p>}
                </li>
              ))}
            </ol>
          )}
        </Section>

        {can("property:read") && (
          <Section title="Properties" query={props} empty="No properties linked">
            {(rows) => (
              <ul className="space-y-1 text-sm">
                {rows.map((r) => (
                  <li key={r.id}>
                    <strong>{r.property_ref}</strong> · {humanize(r.land_use)}
                    {r.address_text ? ` · ${r.address_text}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        )}
        {can("permit:read") && (
          <Section
            title="Permits"
            query={permits}
            empty="No permit records linked (a data gap, not a violation)"
          >
            {(rows) => (
              <ul className="space-y-2 text-sm">
                {rows.map((r) => (
                  <li key={r.id}>
                    <Link
                      className="text-primary font-medium hover:underline"
                      href={`/permits/${r.id}` as Route}
                    >
                      {r.permit_number}
                    </Link>{" "}
                    <Badge>{humanize(r.status)}</Badge>{" "}
                    <Badge tone={MATCH_LABEL[r.match_status].tone}>
                      {MATCH_LABEL[r.match_status].label}
                    </Badge>{" "}
                    {r.is_simulated && <Badge tone="warning">Simulated data</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        )}
        {can("candidate:read") && (
          <Section title="Candidates on this parcel" query={candidates} empty="No candidates">
            {(rows) => (
              <ul className="space-y-1 text-sm">
                {rows.map((r) => (
                  <li key={r.id}>
                    <Link
                      className="text-primary hover:underline"
                      href={`/candidates/${r.id}` as Route}
                    >
                      Candidate {shortId(r.id)}
                    </Link>{" "}
                    · observed {formatDate(r.observed_on)}{" "}
                    <CandidateStatusBadge status={r.status} />
                  </li>
                ))}
              </ul>
            )}
          </Section>
        )}
        {can("case:read") && (
          <Section title="Inspection cases" query={cases} empty="No cases">
            {(rows) => (
              <ul className="space-y-1 text-sm">
                {rows.map((r) => (
                  <li key={r.id}>
                    <Link className="text-primary hover:underline" href={`/cases/${r.id}` as Route}>
                      Case {shortId(r.id)}
                    </Link>{" "}
                    <CaseStatusBadge status={r.status} />
                  </li>
                ))}
              </ul>
            )}
          </Section>
        )}
      </div>
    </>
  );
}
