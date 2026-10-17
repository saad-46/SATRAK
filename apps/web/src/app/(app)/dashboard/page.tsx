"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { useSession } from "@/components/auth/session-provider";
import { ActivityList } from "@/components/shell/activity-list";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";
import { EmptyState, ErrorState, LoadingState, StaleNotice } from "@/components/ui/states";
import { consoleApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";
import { CASE_STATUS, OPEN_CASE_STATUSES } from "@/lib/labels";
import { jurisdictionName } from "@/lib/permissions";

export default function DashboardPage() {
  const { me } = useSession();
  const summary = useQuery({ queryKey: ["dashboard"], queryFn: consoleApi.dashboard });
  const activity = useQuery({ queryKey: ["activity", 8], queryFn: () => consoleApi.activity(8) });

  if (summary.isPending) return <LoadingState label="Loading dashboard" />;
  if (summary.isError && !summary.data)
    return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;
  const s = summary.data!;
  const c = s.candidates;
  const k = s.cases;
  const pending = c ? (c.by_status.unverified ?? 0) + (c.by_status.needs_evidence ?? 0) : 0;
  const open = k ? OPEN_CASE_STATUSES.reduce((n, st) => n + (k.by_status[st] ?? 0), 0) : 0;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Counts are computed on the server for the jurisdictions you can access. Candidates are unverified AI or reported leads, not established violations."
      />
      {summary.isError && <StaleNotice error={summary.error} />}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {c ? (
          <>
            <StatCard
              label="Candidates awaiting review"
              value={pending}
              href="/candidates?status=unverified"
              hint="Unverified or evidence requested"
            />
            <StatCard
              label="Verified, no case yet"
              value={c.verified_awaiting_case}
              href="/candidates?status=confirmed"
              hint="Officer-verified candidates"
            />
          </>
        ) : (
          <Card className="text-muted-foreground text-sm sm:col-span-2">
            Candidate counts are not available for your role.
          </Card>
        )}
        {k ? (
          <>
            <StatCard label="Open inspection cases" value={open} href="/cases" />
            <StatCard
              label="Unassigned open cases"
              value={k.unassigned_open}
              href="/cases?unassigned=true"
            />
          </>
        ) : (
          <Card className="text-muted-foreground text-sm sm:col-span-2">
            Case counts are not available for your role.
          </Card>
        )}
      </div>

      {c && c.simulated > 0 && (
        <p className="bg-warning/15 text-warning mt-4 rounded-md border px-3 py-2 text-sm">
          {c.simulated} candidate{c.simulated === 1 ? " is" : "s are"} simulated test data and must
          not be treated as real detections.
        </p>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {k && (
          <Card aria-labelledby="cases-by-status">
            <h2 id="cases-by-status" className="mb-3 font-semibold">
              Cases by status
            </h2>
            <ul className="space-y-1 text-sm">
              {(Object.keys(CASE_STATUS) as Array<keyof typeof CASE_STATUS>).map((st) => (
                <li key={st} className="flex justify-between">
                  <Link href={`/cases?status=${st}` as Route} className="hover:underline">
                    {CASE_STATUS[st].label}
                  </Link>
                  <span className="tabular-nums">{k.by_status[st] ?? 0}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}
        <Card aria-labelledby="by-jurisdiction">
          <h2 id="by-jurisdiction" className="mb-3 font-semibold">
            By jurisdiction
          </h2>
          {(c?.pending_by_jurisdiction.length ?? 0) + (k?.open_by_jurisdiction.length ?? 0) ===
          0 ? (
            <EmptyState title="Nothing pending in any jurisdiction" />
          ) : (
            <table className="w-full text-sm">
              <caption className="sr-only">
                Pending candidates and open cases per jurisdiction
              </caption>
              <thead className="text-muted-foreground text-left">
                <tr>
                  <th scope="col" className="pb-1 font-medium">
                    Jurisdiction
                  </th>
                  <th scope="col" className="pb-1 text-right font-medium">
                    Candidates pending
                  </th>
                  <th scope="col" className="pb-1 text-right font-medium">
                    Open cases
                  </th>
                </tr>
              </thead>
              <tbody>
                {Array.from(
                  new Set([
                    ...(c?.pending_by_jurisdiction ?? []).map((r) => r.jurisdiction_id),
                    ...(k?.open_by_jurisdiction ?? []).map((r) => r.jurisdiction_id),
                  ]),
                ).map((id) => (
                  <tr key={id} className="border-t">
                    <th scope="row" className="py-1 text-left font-normal">
                      {jurisdictionName(me, id)}
                    </th>
                    <td className="py-1 text-right tabular-nums">
                      {c?.pending_by_jurisdiction.find((r) => r.jurisdiction_id === id)?.pending ??
                        0}
                    </td>
                    <td className="py-1 text-right tabular-nums">
                      {k?.open_by_jurisdiction.find((r) => r.jurisdiction_id === id)?.open ?? 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card className="mt-4" aria-labelledby="sla">
        <h2 id="sla" className="font-semibold">
          Overdue and SLA
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {s.sla.available
            ? "SLA clocks are active."
            : "Not available: service-level clocks are not implemented yet, so no overdue figure is shown."}
        </p>
      </Card>

      <Card className="mt-4" aria-labelledby="recent">
        <div className="mb-2 flex items-center justify-between">
          <h2 id="recent" className="font-semibold">
            Recent activity
          </h2>
          <Link href={"/activity" as Route} className="text-primary text-sm hover:underline">
            View all
          </Link>
        </div>
        {activity.isPending ? (
          <LoadingState />
        ) : activity.isError ? (
          <ErrorState error={activity.error} onRetry={() => void activity.refetch()} />
        ) : activity.data.items.length === 0 ? (
          <EmptyState title="No activity yet" />
        ) : (
          <ActivityList items={activity.data.items} />
        )}
      </Card>

      <p className="text-muted-foreground mt-4 text-xs">
        Generated {formatDateTime(s.generated_at)}
      </p>
    </>
  );
}
