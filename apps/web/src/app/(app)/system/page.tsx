"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/endpoints";

/**
 * System-status page. A foundation smoke screen (not a product feature) that
 * exercises the full client data path: API client → TanStack Query → render,
 * hitting the API's liveness and version endpoints.
 */
export default function SystemStatusPage() {
  const version = useQuery({ queryKey: ["meta", "version"], queryFn: api.version });
  const health = useQuery({ queryKey: ["health", "live"], queryFn: api.health });

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">System status</h1>
        <p className="text-muted-foreground text-sm">Live connectivity to the SATRAK API.</p>
      </div>

      <dl className="grid grid-cols-2 gap-3 text-sm">
        <dt className="text-muted-foreground">API liveness</dt>
        <dd>
          {health.isPending
            ? "checking…"
            : health.isError
              ? "unreachable"
              : (health.data?.status ?? "unknown")}
        </dd>

        <dt className="text-muted-foreground">API version</dt>
        <dd>{version.isPending ? "checking…" : version.isError ? "—" : version.data?.version}</dd>

        <dt className="text-muted-foreground">API environment</dt>
        <dd>{version.data?.environment ?? "—"}</dd>
      </dl>

      {(health.isError || version.isError) && (
        <p className="text-destructive text-sm">
          Could not reach the API. Ensure it is running and NEXT_PUBLIC_API_URL is correct.
        </p>
      )}
    </div>
  );
}
