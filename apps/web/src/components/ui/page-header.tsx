"use client";

import type { ReactNode } from "react";
import { usePageTitle } from "@/lib/hooks/use-page-title";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  usePageTitle(title);
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="text-muted-foreground mt-1 max-w-2xl text-sm">{description}</p>
        )}
      </div>
      {actions}
    </div>
  );
}
