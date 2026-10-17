"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { devTokenAllowed, setDevToken } from "@/lib/auth/token-source";
import { useSession } from "./session-provider";

function Centered({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md space-y-4">{children}</Card>
    </main>
  );
}

function SignIn({ expired }: { expired: boolean }) {
  const [value, setValue] = useState("");
  const allowed = devTokenAllowed();

  function submit(event: FormEvent) {
    event.preventDefault();
    if (value.trim()) setDevToken(value);
  }

  return (
    <Centered>
      <h1 className="text-xl font-semibold">SATRAK officer console</h1>
      {expired && (
        <p role="alert" className="bg-warning/15 text-warning rounded-md border px-3 py-2 text-sm">
          Your session has expired or your access token was rejected. Sign in again.
        </p>
      )}
      {allowed ? (
        <form onSubmit={submit} className="space-y-3">
          <p className="text-muted-foreground text-sm">
            Development sign-in. Paste an access token issued for this environment. It is kept in
            this tab only and is never stored permanently.
          </p>
          <label htmlFor="token" className="block text-sm font-medium">
            Access token
          </label>
          <textarea
            id="token"
            name="token"
            autoComplete="off"
            spellCheck={false}
            rows={4}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="bg-background w-full rounded-md border p-2 font-mono text-xs"
          />
          <Button type="submit" disabled={!value.trim()}>
            Sign in
          </Button>
        </form>
      ) : (
        <p className="text-muted-foreground text-sm">
          Sign-in through the organisation identity provider is not configured in this build, so the
          console cannot authenticate users. Contact the platform team.
        </p>
      )}
    </Centered>
  );
}

/** Blocks the console until there is a verified session; renders the right recovery screen. */
export function AuthGate({ children }: { children: ReactNode }) {
  const session = useSession();
  switch (session.status) {
    case "signed-out":
    case "expired":
      return <SignIn expired={session.status === "expired"} />;
    case "loading":
      return (
        <Centered>
          <LoadingState label="Checking your session" />
        </Centered>
      );
    case "forbidden":
    case "no-access":
      return (
        <Centered>
          <h1 className="text-xl font-semibold">No access</h1>
          <p className="text-muted-foreground text-sm">
            You are signed in, but no role in this system grants you access to the officer console.
            Ask your administrator to assign one.
          </p>
          <Button variant="outline" onClick={session.signOut}>
            Sign out
          </Button>
        </Centered>
      );
    case "error":
      return (
        <Centered>
          <ErrorState error={session.error} onRetry={session.retry} />
          <Button variant="outline" onClick={session.signOut}>
            Sign out
          </Button>
        </Centered>
      );
    default:
      return <>{children}</>;
  }
}
