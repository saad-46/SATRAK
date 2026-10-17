import { ApiError } from "@/lib/api/types";
import { Button } from "@/components/ui/button";

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="text-muted-foreground p-6 text-sm">
      <span className="bg-muted mr-2 inline-block h-2 w-2 animate-pulse rounded-full" aria-hidden />
      {label}…
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
      <p className="text-foreground font-medium">{title}</p>
      {hint && <p className="mt-1">{hint}</p>}
    </div>
  );
}

/** Maps an API failure to what the officer can act on. Never shows raw server internals. */
export function describeError(error: unknown): { title: string; detail: string } {
  if (error instanceof ApiError) {
    if (error.isNetwork)
      return {
        title: "You appear to be offline or the API is unreachable",
        detail: "Check your connection. Data shown may be out of date.",
      };
    if (error.isUnauthenticated)
      return { title: "Your session has expired", detail: "Sign in again to continue." };
    if (error.isForbidden)
      return {
        title: "You do not have access to this",
        detail: "Your role does not include this permission in this jurisdiction.",
      };
    if (error.status === 404)
      return {
        title: "Not found",
        detail: "It may not exist, or may be outside the jurisdictions you can access.",
      };
    if (error.status === 429)
      return { title: "Too many requests", detail: "Wait a moment and try again." };
    return {
      title: "The request failed",
      detail: error.requestId ? `${error.message} (reference ${error.requestId})` : error.message,
    };
  }
  return { title: "Something went wrong", detail: "Try again." };
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { title, detail } = describeError(error);
  return (
    <div role="alert" className="border-destructive/50 bg-destructive/10 rounded-lg border p-4">
      <p className="font-medium">{title}</p>
      <p className="text-muted-foreground mt-1 text-sm">{detail}</p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function StaleNotice({ error }: { error: unknown }) {
  const { title } = describeError(error);
  return (
    <p role="status" className="bg-warning/15 text-warning rounded-md border px-3 py-2 text-sm">
      {title}. Showing the last data received.
    </p>
  );
}
