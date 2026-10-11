import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consoleApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/types";
import { CASE_ID, caseDetail, caseRow, page } from "@/test/fixtures";
import { nav, resetNav } from "@/test/navigation-mock";
import { asUser, FULL_PERMS, J1, renderWithClient, resolved } from "@/test/utils";

vi.mock("next/navigation", () => import("@/test/navigation-mock"));
vi.mock("@/components/auth/session-provider", async () => {
  const u = await import("@/test/utils");
  return { useSession: () => u.session.current };
});

import CasesPage from "./page";
import CaseDetailPage from "./[id]/page";

const history = {
  transitions: [
    {
      seq: 1,
      from_status: null,
      to_status: "created",
      actor_id: "aaaaaaaa-1",
      reason: null,
      created_at: "2026-09-03T10:00:00Z",
    },
  ],
  assignments: [
    {
      seq: 1,
      assigned_to: "bbbbbbbb-2",
      assigned_by: "aaaaaaaa-1",
      reason: "nearest officer",
      created_at: "2026-09-03T11:00:00Z",
    },
  ],
  findings: [
    {
      seq: 1,
      author_id: "bbbbbbbb-2",
      notes: "Site visited; slab poured.",
      measurements: {},
      evidence: [],
      created_at: "2026-09-04T09:00:00Z",
    },
  ],
};

beforeEach(() => asUser(FULL_PERMS));
afterEach(() => vi.restoreAllMocks());

describe("case queue", () => {
  it("lists cases from the server with filters from the URL", async () => {
    resetNav("/cases", "status=assigned&unassigned=true");
    const spy = vi
      .spyOn(consoleApi, "cases")
      .mockResolvedValue(
        page([caseRow(), caseRow({ id: "d", status: "resolved", assigned_to: "bbbbbbbb-2" })]),
      );
    renderWithClient(<CasesPage />);
    expect(await screen.findByText("Unassigned")).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ status: "assigned", unassigned: true, page: 1, size: 20 }),
    );
    expect(screen.getByLabelText("Status")).toHaveValue("assigned");
  });

  it("shows an empty state and an error state", async () => {
    resetNav("/cases");
    const spy = vi.spyOn(consoleApi, "cases").mockResolvedValueOnce(page([]));
    renderWithClient(<CasesPage />);
    expect(await screen.findByText("No cases yet")).toBeInTheDocument();
    spy.mockRejectedValue(new ApiError(0, "network_error", "x"));
    vi.restoreAllMocks();
    vi.spyOn(consoleApi, "cases").mockRejectedValue(new ApiError(0, "network_error", "x"));
    renderWithClient(<CasesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/offline/i);
  });
});

function setupDetail(detail = caseDetail()) {
  resetNav(`/cases/${CASE_ID}`);
  vi.spyOn(consoleApi, "case").mockResolvedValue(detail);
  vi.spyOn(consoleApi, "caseHistory").mockResolvedValue(history as never);
  return renderWithClient(<CaseDetailPage params={resolved({ id: CASE_ID })} />);
}

describe("case detail", () => {
  it("offers only the transitions the server allows and keeps findings distinct from candidates", async () => {
    setupDetail(
      caseDetail({
        actions: {
          can_assign: false,
          can_add_finding: true,
          allowed_transitions: ["under_investigation"],
        },
      }),
    );
    expect(await screen.findByRole("button", { name: "Start investigation" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /dismiss|resolve|issue notice/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^assign|reassign/i })).not.toBeInTheDocument();
    expect(await screen.findByText(/Case finding #1 \(field inspection\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /candidate aaaaaaaa/i })).toBeInTheDocument();
  });

  it("builds a chronological timeline of transitions, assignments and field findings", async () => {
    setupDetail();
    const items = await screen.findAllByRole("listitem");
    const text = items.map((i) => i.textContent ?? "").join("|");
    expect(text.indexOf("Opened → Created")).toBeLessThan(text.indexOf("Assigned to bbbbbbbb"));
    expect(text.indexOf("Assigned to bbbbbbbb")).toBeLessThan(text.indexOf("Case finding #1"));
    expect(text).toContain("Site visited; slab poured.");
  });

  it("shows no actions on a closed case", async () => {
    setupDetail(
      caseDetail({
        status: "resolved",
        actions: { can_assign: false, can_add_finding: false, allowed_transitions: [] },
      }),
    );
    expect(
      await screen.findByText(/no actions available — the case is resolved/i),
    ).toBeInTheDocument();
  });

  it("sends the case version with a transition (optimistic concurrency) and refreshes", async () => {
    const t = vi.spyOn(consoleApi, "transition").mockResolvedValue(caseRow({ status: "assigned" }));
    setupDetail();
    await userEvent.click(await screen.findByRole("button", { name: "Mark assigned" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/reason/i), "ready");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(t).toHaveBeenCalledWith(CASE_ID, "assigned", 3, "ready");
    expect(await screen.findByText(/case moved to assigned/i)).toBeInTheDocument();
  });

  it("explains a stale-version conflict and reloads the case", async () => {
    vi.spyOn(consoleApi, "transition").mockRejectedValue(
      new ApiError(409, "version_conflict", "stale"),
    );
    setupDetail();
    const reload = vi.mocked(consoleApi.case);
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss case" }));
    const before = reload.mock.calls.length;
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/changed since you opened it/i);
    await waitFor(() => expect(reload.mock.calls.length).toBeGreaterThan(before));
  });

  it("does not double-submit a transition", async () => {
    let release!: (v: unknown) => void;
    const t = vi.spyOn(consoleApi, "transition").mockImplementation(
      () =>
        new Promise((r) => {
          release = r;
        }) as never,
    );
    setupDetail();
    await userEvent.click(await screen.findByRole("button", { name: "Mark assigned" }));
    const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" });
    await userEvent.dblClick(confirm);
    expect(t).toHaveBeenCalledTimes(1);
    release(caseRow());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("assigns by validated user id and surfaces the server's refusal", async () => {
    const a = vi
      .spyOn(consoleApi, "assign")
      .mockRejectedValue(
        new ApiError(
          422,
          "validation_error",
          "the assignee does not hold case:update in the case's jurisdiction",
        ),
      );
    setupDetail();
    await userEvent.click(await screen.findByRole("button", { name: "Assign" }));
    const dialog = screen.getByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Assign" });
    expect(submit).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/assignee user id/i), "not-a-uuid");
    expect(submit).toBeDisabled();
    await userEvent.clear(within(dialog).getByLabelText(/assignee user id/i));
    await userEvent.type(
      within(dialog).getByLabelText(/assignee user id/i),
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    );
    await userEvent.click(submit);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/does not hold case:update/);
    expect(a).toHaveBeenCalledWith(CASE_ID, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", 3, "");
  });

  it("records a case finding with notes", async () => {
    const f = vi.spyOn(consoleApi, "addFinding").mockResolvedValue(history.findings[0] as never);
    setupDetail();
    await userEvent.click(await screen.findByRole("button", { name: /record case finding/i }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: /record finding/i })).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/site-visit notes/i), "Foundation only.");
    await userEvent.type(within(dialog).getByLabelText(/measurement name/i), "floors");
    await userEvent.type(within(dialog).getByLabelText("Value"), "2");
    await userEvent.click(within(dialog).getByRole("button", { name: /record finding/i }));
    await waitFor(() =>
      expect(f).toHaveBeenCalledWith(CASE_ID, {
        notes: "Foundation only.",
        measurements: { floors: 2 },
      }),
    );
  });

  it("shows not-found for a case in another jurisdiction", async () => {
    resetNav("/cases/x");
    vi.spyOn(consoleApi, "case").mockRejectedValue(new ApiError(404, "not_found", "x"));
    vi.spyOn(consoleApi, "caseHistory").mockResolvedValue(history as never);
    renderWithClient(<CaseDetailPage params={resolved({ id: "x" })} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
    void nav;
    void J1;
  });
});
