"use client";

import { Menu, X } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { shortId } from "@/lib/format";
import { useSession } from "@/components/auth/session-provider";
import { breadcrumbsFor, NAV_ITEMS } from "./nav-config";

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { can } = useSession();
  const items = NAV_ITEMS.filter((item) => item.anyOf.some((p) => can(p)));
  return (
    <nav aria-label="Primary">
      <ul className="space-y-1">
        {items.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={href}>
              <Link
                href={href as Route}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm",
                  active
                    ? "bg-primary/20 text-sidebar-foreground font-medium"
                    : "text-sidebar-foreground/80 hover:bg-white/10",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function Breadcrumbs() {
  const pathname = usePathname();
  const crumbs = breadcrumbsFor(pathname);
  if (crumbs.length < 2) return null;
  return (
    <nav aria-label="Breadcrumb" className="text-muted-foreground mb-4 text-sm">
      <ol className="flex flex-wrap items-center gap-1">
        {crumbs.map((crumb, i) => (
          <li key={crumb.href} className="flex items-center gap-1">
            {i > 0 && <span aria-hidden>/</span>}
            {i === crumbs.length - 1 ? (
              <span aria-current="page" className="text-foreground">
                {crumb.label}
              </span>
            ) : (
              <Link href={crumb.href as Route} className="hover:underline">
                {crumb.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { me, signOut } = useSession();
  const [open, setOpen] = useState(false);

  useEffect(() => setOpen(false), [pathname]);

  const jurisdictions = me?.jurisdictions ?? [];
  const scope =
    jurisdictions.length === 0
      ? "No jurisdictions"
      : jurisdictions.length === 1
        ? jurisdictions[0]!.name
        : `${jurisdictions.length} jurisdictions`;

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[16rem_1fr]">
      <a
        href="#main"
        className="bg-primary text-primary-foreground sr-only z-50 rounded-md p-2 focus:not-sr-only focus:fixed focus:left-2 focus:top-2"
      >
        Skip to content
      </a>

      <aside className="bg-sidebar text-sidebar-foreground hidden flex-col gap-6 p-4 lg:flex">
        <div className="px-3 pt-2 text-lg font-semibold">SATRAK</div>
        <NavList />
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="bg-card/80 sticky top-0 z-30 flex h-14 items-center gap-3 border-b px-4 backdrop-blur">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label={open ? "Close navigation" : "Open navigation"}
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X aria-hidden /> : <Menu aria-hidden />}
          </Button>
          <span className="font-semibold lg:hidden">SATRAK</span>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-muted-foreground hidden sm:inline" title="Jurisdiction scope">
              {scope}
            </span>
            <span className="text-muted-foreground font-mono text-xs" title="Signed-in user id">
              {shortId(me?.user_id)}
            </span>
            <Button variant="outline" size="sm" onClick={signOut}>
              Sign out
            </Button>
          </div>
        </header>

        {open && (
          <div
            id="mobile-nav"
            className="bg-sidebar text-sidebar-foreground border-b p-3 lg:hidden"
          >
            <NavList onNavigate={() => setOpen(false)} />
          </div>
        )}

        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6">
          <Breadcrumbs />
          {children}
        </main>
      </div>
    </div>
  );
}
