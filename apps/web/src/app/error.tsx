"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

/** Route-segment error boundary. Catches render-time errors below the root layout. */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Foundation stub: report to the observability stack here (Sentry/OTel) with
    // the request-correlation id once wired. Never silently swallow.
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <h2 className="text-xl font-semibold">Something went wrong</h2>
      <p className="text-muted-foreground max-w-md text-sm">
        An unexpected error occurred. You can try again, or contact support if it persists.
      </p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
