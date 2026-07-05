import type { ReactNode } from "react";

/**
 * Public route group — unauthenticated, marketing/landing surface.
 * Route groups organize the app by access boundary without affecting URLs
 * (this group's pages still live at the root path). The future `(app)` group
 * will carry the authenticated officer/admin shell.
 */
export default function PublicLayout({ children }: { children: ReactNode }) {
  return <div className="min-h-screen">{children}</div>;
}
