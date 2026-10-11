"use client";

import { useQuery } from "@tanstack/react-query";
import { ActivityList } from "@/components/shell/activity-list";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { consoleApi } from "@/lib/api/endpoints";

export default function ActivityPage() {
  const q = useQuery({ queryKey: ["activity", 50], queryFn: () => consoleApi.activity(50) });
  return (
    <>
      <PageHeader
        title="Activity"
        description="Newest workflow history across the areas you may read: reviews, case transitions, field findings, permit and parcel changes. Security audit records are not shown here."
      />
      <Card>
        {q.isPending ? (
          <LoadingState />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : q.data.items.length === 0 ? (
          <EmptyState title="No activity yet" />
        ) : (
          <ActivityList items={q.data.items} />
        )}
      </Card>
    </>
  );
}
