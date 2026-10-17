import type { ReactNode } from "react";
import { AuthGate } from "@/components/auth/auth-gate";
import { SessionProvider } from "@/components/auth/session-provider";
import { AppShell } from "@/components/shell/app-shell";

/**
 * Authenticated officer-console surface. Authentication is established client-side from a bearer
 * token (see lib/auth/token-source); every API route still enforces its own authorisation, so
 * hiding navigation here is a usability aid, not a security boundary.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <AuthGate>
        <AppShell>{children}</AppShell>
      </AuthGate>
    </SessionProvider>
  );
}
