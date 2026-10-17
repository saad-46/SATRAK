import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consoleApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/types";
import { summary } from "@/test/fixtures";
import { resetNav } from "@/test/navigation-mock";
import { asUser, FULL_PERMS, J1, renderWithClient } from "@/test/utils";

vi.mock("next/navigation", () => import("@/test/navigation-mock"));
vi.mock("@/components/auth/session-provider", async () => {
  const u = await import("@/test/utils");
  return { useSession: () => u.session.current };
});

import DashboardPage from "./page";

const activity = {
  items: [
    {
      kind: "candidate.reviewed",
      occurred_at: "2026-10-11T05:00:00Z",
      actor_id: "a",
      entity_type: "candidate",
      entity_id: "aaaaaaaa-1111",
      jurisdiction_id: J1,
      summary: "confirm -> confirmed",
    },
  ],
  sources: ["candidate:read"],
};

beforeEach(() => {
  resetNav("/dashboard");
  asUser(FULL_PERMS);
  vi.spyOn(consoleApi, "activity").mockResolvedValue(activity);
});
afterEach(() => vi.restoreAllMocks());

describe("dashboard", () => {
  it("renders server-computed counts with links into filtered queues", async () => {
    vi.spyOn(consoleApi, "dashboard").mockResolvedValue(summary());
    renderWithClient(<DashboardPage />);
    const card = (await screen.findByText("Candidates awaiting review")).closest("a")!;
    expect(within(card).getByText("5")).toBeInTheDocument();
    expect(card).toHaveAttribute("href", "/candidates?status=unverified");
    expect(screen.getByText("Verified, no case yet").closest("a")).toHaveAttribute(
      "href",
      "/candidates?status=confirmed",
    );
    expect(
      within(screen.getByText("Open inspection cases").closest("a")!).getByText("3"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByText("Unassigned open cases").closest("a")!).getByText("2"),
    ).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /per jurisdiction/i })).toBeInTheDocument();
  });

  it("does not invent an overdue figure when SLA data does not exist", async () => {
    vi.spyOn(consoleApi, "dashboard").mockResolvedValue(summary());
    renderWithClient(<DashboardPage />);
    expect(
      await screen.findByText(
        /service-level clocks are not implemented yet, so no overdue figure/i,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/overdue:\s*\d/i)).not.toBeInTheDocument();
  });

  it("says a section is unavailable when the role lacks it (null from the API)", async () => {
    vi.spyOn(consoleApi, "dashboard").mockResolvedValue(summary({ cases: null }));
    renderWithClient(<DashboardPage />);
    expect(
      await screen.findByText(/case counts are not available for your role/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("Open inspection cases")).not.toBeInTheDocument();
  });

  it("flags simulated candidates so they are not mistaken for detections", async () => {
    vi.spyOn(consoleApi, "dashboard").mockResolvedValue(
      summary({ candidates: { ...summary().candidates!, simulated: 2 } }),
    );
    renderWithClient(<DashboardPage />);
    expect(await screen.findByText(/2 candidates are simulated test data/i)).toBeInTheDocument();
  });

  it("shows recent activity with entity links and no request metadata", async () => {
    vi.spyOn(consoleApi, "dashboard").mockResolvedValue(summary());
    renderWithClient(<DashboardPage />);
    const link = await screen.findByRole("link", { name: /candidate aaaaaaaa/i });
    expect(link).toHaveAttribute("href", "/candidates/aaaaaaaa-1111");
    expect(document.body.textContent).not.toMatch(/ip_address|user_agent|request_id/i);
  });

  it("shows loading then an error with retry", async () => {
    vi.spyOn(consoleApi, "dashboard").mockRejectedValue(
      new ApiError(500, "internal", "boom", "req-9"),
    );
    renderWithClient(<DashboardPage />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading dashboard/i);
    expect(await screen.findByRole("alert")).toHaveTextContent(/reference req-9/);
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
