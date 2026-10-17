"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/** Reads/writes list state (filters, page) in the URL so views are shareable and survive reload. */
export function useUrlState(defaults: Record<string, string> = {}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const get = useCallback(
    (key: string) => params.get(key) ?? defaults[key] ?? "",
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [params],
  );

  const set = useCallback(
    (patch: Record<string, string | number | null>, { resetPage = true } = {}) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === "" || v === defaults[k]) next.delete(k);
        else next.set(k, String(v));
      }
      if (resetPage && !("page" in patch)) next.delete("page");
      const qs = next.toString();
      router.replace((qs ? `${pathname}?${qs}` : pathname) as Route, { scroll: false });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [params, pathname, router],
  );

  return { get, set, page: Math.max(1, Number(params.get("page")) || 1) };
}
