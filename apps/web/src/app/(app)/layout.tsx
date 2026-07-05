import type { ReactNode } from "react";

/**
 * Authenticated application shell (officer/commissioner/admin surface).
 *
 * In the foundation this is an intentionally minimal wrapper. The real shell
 * (top bar, role-scoped side nav, notification tray) and a route-level auth
 * guard (middleware checking the session cookie + role claim) are added by the
 * Authentication epic. Route groups keep this access boundary explicit.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="flex h-14 items-center border-b px-6">
        <span className="font-semibold">SATRAK</span>
        <span className="text-muted-foreground ml-2 text-xs">Console</span>
      </header>
      <div className="p-6">{children}</div>
    </div>
  );
}
