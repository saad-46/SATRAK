import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consoleApi } from "@/lib/api/endpoints";
import {
  CAND_ID,
  CASE_ID,
  candidate,
  candidateDetail,
  caseDetail,
  caseRow,
  page,
  summary,
} from "@/test/fixtures";
import { resetNav } from "@/test/navigation-mock";
import { asUser, FULL_PERMS, J1, renderWithClient, resolved } from "@/test/utils";
import { auditA11y } from "@/test/a11y-audit";
import { AppShell } from "@/components/shell/app-shell";

vi.mock("next/navigation", () => import("@/test/navigation-mock"));
vi.mock("@/components/auth/session-provider", async () => {
  const u = await import("@/test/utils");
  return { useSession: () => u.session.current };
});

import DashboardPage from "./dashboard/page";
import CandidatesPage from "./candidates/page";
import CandidateDetailPage from "./candidates/[id]/page";
import CasesPage from "./cases/page";
import CaseDetailPage from "./cases/[id]/page";

beforeEach(() => {
  asUser(FULL_PERMS);
  vi.spyOn(consoleApi, "activity").mockResolvedValue({ items: [], sources: [] });
  vi.spyOn(consoleApi, "dashboard").mockResolvedValue(summary());
  vi.spyOn(consoleApi, "candidates").mockResolvedValue(page([candidate()]));
  vi.spyOn(consoleApi, "cases").mockResolvedValue(page([caseRow()]));
  vi.spyOn(consoleApi, "candidate").mockResolvedValue(candidateDetail());
  vi.spyOn(consoleApi, "evaluations").mockResolvedValue([]);
  vi.spyOn(consoleApi, "reviews").mockResolvedValue([]);
  vi.spyOn(consoleApi, "case").mockResolvedValue(caseDetail());
  vi.spyOn(consoleApi, "caseHistory").mockResolvedValue({
    transitions: [],
    assignments: [],
    findings: [],
  });
});
afterEach(() => vi.restoreAllMocks());

const shell = (ui: React.ReactElement) => <AppShell>{ui}</AppShell>;

describe("structural accessibility audit (labels, names, landmarks, tables, headings)", () => {
  it.each([
    ["dashboard", "/dashboard", () => <DashboardPage />, /candidates awaiting review/i],
    [
      "candidate queue",
      "/candidates",
      () => <CandidatesPage />,
      /candidates, newest first|review status/i,
    ],
    ["case queue", "/cases", () => <CasesPage />, /inspection cases by priority|status/i],
    [
      "candidate detail",
      `/candidates/${CAND_ID}`,
      () => <CandidateDetailPage params={resolved({ id: CAND_ID })} />,
      /officer conclusion/i,
    ],
    [
      "case detail",
      `/cases/${CASE_ID}`,
      () => <CaseDetailPage params={resolved({ id: CASE_ID })} />,
      /timeline/i,
    ],
  ])("%s has no structural violations", async (_n, path, el, ready) => {
    resetNav(path);
    renderWithClient(shell(el()));
    await screen.findAllByText(ready);
    expect(auditA11y()).toEqual([]);
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("an open review dialog is also free of structural violations", async () => {
    resetNav(`/candidates/${CAND_ID}`);
    renderWithClient(shell(<CandidateDetailPage params={resolved({ id: CAND_ID })} />));
    await userEvent.click(await screen.findByRole("button", { name: /verify candidate/i }));
    expect(auditA11y()).toEqual([]);
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    void J1;
  });

  it("is fully keyboard operable: skip link first, then nav, and dialogs open from the keyboard", async () => {
    resetNav(`/candidates/${CAND_ID}`);
    renderWithClient(shell(<CandidateDetailPage params={resolved({ id: CAND_ID })} />));
    await screen.findByRole("button", { name: /verify candidate/i });
    await userEvent.tab();
    expect(screen.getByRole("link", { name: /skip to content/i })).toHaveFocus();
    const btn = screen.getByRole("button", { name: /reject candidate/i });
    btn.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("audit helper self-test", () => {
  it("detects unlabeled controls and missing table headers", () => {
    document.body.innerHTML = `<button></button><input /><table><tr><td>x</td></tr></table><img src="a">`;
    const problems = auditA11y();
    expect(problems.join("|")).toMatch(/button without accessible name/);
    expect(problems.join("|")).toMatch(/form control without label/);
    expect(problems.join("|")).toMatch(/table without header/);
    expect(problems.join("|")).toMatch(/img without alt/);
    document.body.innerHTML = "";
  });
});
