import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nav, resetNav } from "@/test/navigation-mock";
import { asUser, J1, J2, session } from "@/test/utils";
import { breadcrumbsFor } from "./nav-config";

vi.mock("next/navigation", () => import("@/test/navigation-mock"));
vi.mock("@/components/auth/session-provider", async () => {
  const u = await import("@/test/utils");
  return { useSession: () => u.session.current };
});

import { AppShell } from "./app-shell";

beforeEach(() => resetNav("/candidates"));

describe("AppShell", () => {
  it("shows only navigation the user holds permissions for", () => {
    asUser({ "candidate:read": [J1], "finding:verify": [J1] });
    render(
      <AppShell>
        <p>page</p>
      </AppShell>,
    );
    const primary = screen.getAllByRole("navigation", { name: "Primary" })[0]!;
    const links = within(primary)
      .getAllByRole("link")
      .map((l) => l.textContent);
    expect(links).toEqual(["Dashboard", "Candidates", "Activity"]);
    expect(within(primary).queryByRole("link", { name: /permits/i })).not.toBeInTheDocument();
    expect(within(primary).queryByRole("link", { name: /cases/i })).not.toBeInTheDocument();
  });

  it("marks the current page and exposes a skip link and main landmark", () => {
    asUser({ "candidate:read": [J1] });
    render(
      <AppShell>
        <p>page</p>
      </AppShell>,
    );
    expect(screen.getAllByRole("link", { name: "Candidates" })[0]).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: /skip to content/i })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("summarises jurisdiction scope and the user, and signs out", async () => {
    asUser({ "case:read": [J1, J2] }, [J1, J2]);
    render(
      <AppShell>
        <p>page</p>
      </AppShell>,
    );
    expect(screen.getByText("2 jurisdictions")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /sign out/i }));
    expect(session.current.signOut).toHaveBeenCalled();
  });

  it("toggles the mobile navigation with correct aria state", async () => {
    asUser({ "case:read": [J1] });
    render(
      <AppShell>
        <p>page</p>
      </AppShell>,
    );
    const toggle = screen.getByRole("button", { name: /open navigation/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: /close navigation/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(document.getElementById("mobile-nav")).toBeInTheDocument();
  });

  it("renders breadcrumbs on detail pages", () => {
    nav.pathname = "/candidates/abcdef12-0000";
    asUser({ "candidate:read": [J1] });
    render(
      <AppShell>
        <p>page</p>
      </AppShell>,
    );
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Candidates" })).toHaveAttribute(
      "href",
      "/candidates",
    );
    expect(within(crumbs).getByText("abcdef12")).toHaveAttribute("aria-current", "page");
  });
});

describe("breadcrumbsFor", () => {
  it("builds cumulative hrefs", () => {
    expect(breadcrumbsFor("/cases/12345678-aaaa")).toEqual([
      { href: "/cases", label: "Inspection cases" },
      { href: "/cases/12345678-aaaa", label: "12345678" },
    ]);
  });
});
