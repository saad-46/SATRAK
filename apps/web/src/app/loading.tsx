import { Loader2 } from "lucide-react";

/** Root route-level loading UI (shown during navigation/suspense). */
export default function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center" role="status" aria-live="polite">
      <Loader2 className="text-muted-foreground size-6 animate-spin" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}
