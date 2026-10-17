import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { consoleApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/types";
import { candidate, page } from "@/test/fixtures";
import { nav, resetNav } from "@/test/navigation-mock";
import { asUser, J1, J2, renderWithClient } from "@/test/utils";

vi.mock("next/navigation", () => import("@/test/navigation-mock"));
vi.mock("@/components/auth/session-provider", async () => {
  const u = await import("@/test/utils");
  return { useSession: () => u.session.current };
});

import CandidatesPage from "./page";

beforeEach(() => {
  resetNav("/candidates");
  asUser({ "candidate:read": [J1] });
});
afterEach(() => vi.restoreAllMocks());

describe("candidate queue", () => {
  it("lists candidates with unverified labelling and never calls them violations", async () => {
    vi.spyOn(consoleApi, "candidates").mockResolvedValue(
      page([
        candidate(),
        candidate({ id: "b", status: "confirmed", is_simulated: true, confidence: null }),
      ]),
    );
    renderWithClient(<CandidatesPage />);
    expect(await screen.findByText("Unverified", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Verified by officer", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("87%")).toBeInTheDocument();
    expect(screen.getByText("not provided")).toBeInTheDocument();
    expect(screen.getByText("Simulated data")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(
      /confirmed violation|illegal|unauthori[sz]ed construction detected/i,
    );
    expect(screen.getByText(/not proof/i)).toBeInTheDocument();
  });

  it("sends server-side page, size and URL-derived filters", async () => {
    resetNav("/candidates", "status=needs_evidence&page=3");
    const spy = vi.spyOn(consoleApi, "candidates").mockResolvedValue(
      page([candidate({ status: "needs_evidence" })], {
        page: 3,
        total: 41,
        total_pages: 3,
        has_previous: true,
      }),
    );
    renderWithClient(<CandidatesPage />);
    await screen.findByText("Evidence requested", { selector: "span" });
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ page: 3, size: 20, status: "needs_evidence" }),
    );
    expect(screen.getByLabelText("Review status")).toHaveValue("needs_evidence");
    expect(screen.getByText(/Page 3 of 3/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("writes filter and page changes to the URL and resets the page when filtering", async () => {
    vi.spyOn(consoleApi, "candidates").mockResolvedValue(
      page([candidate()], { total: 40, total_pages: 2, has_next: true }),
    );
    renderWithClient(<CandidatesPage />);
    await screen.findByText("Unverified", { selector: "span" });
    await userEvent.selectOptions(screen.getByLabelText("Review status"), "confirmed");
    expect(nav.replace).toHaveBeenLastCalledWith("/candidates?status=confirmed", { scroll: false });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(nav.replace).toHaveBeenLastCalledWith(expect.stringContaining("page=2"), {
      scroll: false,
    });
  });

  it("shows a filtered empty state with a way back, and a first-run empty state", async () => {
    resetNav("/candidates", "status=rejected");
    vi.spyOn(consoleApi, "candidates").mockResolvedValue(page([]));
    renderWithClient(<CandidatesPage />);
    expect(await screen.findByText("No candidates match these filters")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(nav.replace).toHaveBeenLastCalledWith("/candidates", { scroll: false });
  });

  it("shows an error with retry, mapping 403 to a no-access message", async () => {
    const spy = vi
      .spyOn(consoleApi, "candidates")
      .mockRejectedValueOnce(new ApiError(403, "forbidden", "x"))
      .mockResolvedValue(page([candidate()]));
    renderWithClient(<CandidatesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have access/i);
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("offers a jurisdiction filter only to multi-jurisdiction users", async () => {
    asUser({ "candidate:read": [J1, J2] }, [J1, J2]);
    vi.spyOn(consoleApi, "candidates").mockResolvedValue(page([candidate()]));
    renderWithClient(<CandidatesPage />);
    const select = await screen.findByLabelText("Jurisdiction");
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["All", "Ward 1", "Ward 2"]);
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
  });

  it("renders a labelled, scoped table", async () => {
    vi.spyOn(consoleApi, "candidates").mockResolvedValue(page([candidate()]));
    renderWithClient(<CandidatesPage />);
    const table = await screen.findByRole("table", { name: /candidates/i });
    expect(within(table).getAllByRole("columnheader")).toHaveLength(7);
  });
});
