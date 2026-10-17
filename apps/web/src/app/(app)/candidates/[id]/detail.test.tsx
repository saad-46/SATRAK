import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { consoleApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/types";
import { CAND_ID, candidate, candidateDetail, footprint, page } from "@/test/fixtures";
import { resetNav, nav } from "@/test/navigation-mock";
import { asUser, FULL_PERMS, J1, jsonResponse, renderWithClient, resolved } from "@/test/utils";

vi.mock("next/navigation", () => import("@/test/navigation-mock"));
vi.mock("@/components/auth/session-provider", async () => {
  const u = await import("@/test/utils");
  return { useSession: () => u.session.current };
});

import CandidateDetailPage from "./page";

const review = {
  seq: 1,
  decision: "confirm",
  resulting_status: "confirmed",
  justification: "x",
  evidence_refs: [],
  is_reversal: false,
  reviewer_id: "r",
  created_at: "2026-09-05T10:00:00Z",
};
const longText = "Roof and walls visible in the scene; no permit on file for this plot.";

function setup(
  detail = candidateDetail(),
  opts: { evaluations?: unknown[]; reviews?: unknown[] } = {},
) {
  resetNav(`/candidates/${CAND_ID}`);
  asUser(FULL_PERMS);
  vi.spyOn(consoleApi, "candidate").mockResolvedValue(detail);
  vi.spyOn(consoleApi, "evaluations").mockResolvedValue((opts.evaluations ?? []) as never);
  vi.spyOn(consoleApi, "reviews").mockResolvedValue((opts.reviews ?? []) as never);
  vi.spyOn(consoleApi, "parcel").mockResolvedValue({
    id: "p",
    code: "PCL-1",
    geometry: footprint,
    current_version: 1,
  } as never);
  vi.spyOn(consoleApi, "permits").mockResolvedValue(page([]) as never);
  return renderWithClient(<CandidateDetailPage params={resolved({ id: CAND_ID })} />);
}

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("candidate detail", () => {
  it("separates observed facts, model inference and officer conclusion without fabricating imagery", async () => {
    setup(candidateDetail({ imagery_refs: [] }));
    expect(await screen.findByRole("heading", { name: /observed facts/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /model inference/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /officer conclusion/i })).toBeInTheDocument();
    expect(
      screen.getByText(/no before\/after imagery is shown because none is available/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/not a probability of violation/i)).toBeInTheDocument();
    expect(screen.getByText("87%")).toBeInTheDocument();
    expect(screen.getByText(/not reviewed|No officer has reviewed/i)).toBeInTheDocument();
  });

  it("draws valid stored geometry and refuses to draw malformed geometry", async () => {
    const { unmount } = setup();
    const img = await screen.findByRole("img", { name: /candidate footprint/i });
    expect(img.querySelectorAll("path")).toHaveLength(1);
    unmount();
    vi.restoreAllMocks();
    setup(
      candidateDetail({
        footprint: {
          type: "Polygon",
          coordinates: [
            [
              [0, 0],
              [1, 1],
            ],
          ],
        },
      }),
    );
    expect(await screen.findByText(/footprint not drawn/i)).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /candidate footprint/i }).querySelectorAll("path"),
    ).toHaveLength(0);
  });

  it("shows permit context honestly: no permit is a data gap, not a violation", async () => {
    setup(candidateDetail({ parcel_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" }));
    expect(
      await screen.findByText(/data gap and does not by itself mean the work is unauthorised/i),
    ).toBeInTheDocument();
  });

  it("offers exactly the decisions the server allows and explains missing ones", async () => {
    setup(
      candidateDetail({
        actions: {
          can_review: true,
          allowed_decisions: ["reject", "request_evidence"],
          confirm_blockers: ["evaluation", "provenance"],
          can_open_case: false,
          open_case_blockers: ["not_verified"],
        },
      }),
    );
    await screen.findByRole("heading", { name: /officer conclusion/i });
    expect(screen.queryByRole("button", { name: /verify candidate/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject candidate/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /request more evidence/i })).toBeInTheDocument();
    expect(screen.getByText(/needs a compliance evaluation/i)).toBeInTheDocument();
    expect(screen.getByText(/imagery references or a provenance note/i)).toBeInTheDocument();
  });

  it("hides every decision control from users without review permission", async () => {
    setup(
      candidateDetail({
        actions: {
          can_review: false,
          allowed_decisions: [],
          confirm_blockers: [],
          can_open_case: false,
          open_case_blockers: ["no_permission"],
        },
      }),
    );
    await screen.findByRole("heading", { name: /officer conclusion/i });
    expect(screen.queryByRole("button", { name: /candidate|evidence/i })).not.toBeInTheDocument();
    expect(screen.getByText(/does not include verification/i)).toBeInTheDocument();
  });

  it("blocks decisions while a case is open", async () => {
    setup(
      candidateDetail({
        status: "confirmed",
        case_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        actions: {
          can_review: true,
          allowed_decisions: [],
          confirm_blockers: [],
          can_open_case: false,
          open_case_blockers: ["case_exists"],
        },
      }),
    );
    expect(await screen.findByText(/already has an open case/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open case cccccccc/i })).toHaveAttribute(
      "href",
      expect.stringContaining("/cases/"),
    );
  });

  it("offers case creation only when the server says it is allowed", async () => {
    setup(
      candidateDetail({
        status: "confirmed",
        actions: {
          can_review: true,
          allowed_decisions: ["reject"],
          confirm_blockers: [],
          can_open_case: true,
          open_case_blockers: [],
        },
      }),
    );
    expect(
      await screen.findByRole("button", { name: /open inspection case/i }),
    ).toBeInTheDocument();
  });
});

describe("verification workflow", () => {
  async function openDialog(name: RegExp) {
    await userEvent.click(await screen.findByRole("button", { name }));
    return screen.getByRole("dialog");
  }

  it("requires a justification, shows a confirmation step, then records the decision", async () => {
    const submit = vi.spyOn(consoleApi, "submitReview").mockResolvedValue(review as never);
    setup();
    const dialog = await openDialog(/verify candidate/i);
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const cont = within(dialog).getByRole("button", { name: /continue/i });
    expect(cont).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/justification/i), "too short");
    expect(cont).toBeDisabled();
    await userEvent.clear(within(dialog).getByLabelText(/justification/i));
    await userEvent.type(within(dialog).getByLabelText(/justification/i), longText);
    await userEvent.click(cont);
    expect(submit).not.toHaveBeenCalled();
    expect(
      within(dialog).getByText(/server records your identity and the time/i),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(longText)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: /record decision/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith(CAND_ID, { decision: "confirm", justification: longText });
    // The request carries no reviewer or timestamp: the server supplies both.
    expect(Object.keys(submit.mock.calls[0]![1] as object).sort()).toEqual([
      "decision",
      "justification",
    ]);
    expect(await screen.findByText(/decision recorded: verify candidate/i)).toBeInTheDocument();
  });

  it("guards against duplicate submits while the request is in flight", async () => {
    let release!: (v: unknown) => void;
    const submit = vi.spyOn(consoleApi, "submitReview").mockImplementation(
      () =>
        new Promise((r) => {
          release = r;
        }) as never,
    );
    setup();
    const dialog = await openDialog(/reject candidate/i);
    await userEvent.type(within(dialog).getByLabelText(/justification/i), longText);
    await userEvent.click(within(dialog).getByRole("button", { name: /continue/i }));
    const record = within(dialog).getByRole("button", { name: /record decision/i });
    await userEvent.dblClick(record);
    await userEvent.click(record);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(within(dialog).getByRole("button", { name: /recording/i })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument(); // cannot dismiss mid-flight
    release(review);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("surfaces a server validation failure and keeps the dialog open for correction", async () => {
    vi.spyOn(consoleApi, "submitReview").mockRejectedValue(
      new ApiError(
        422,
        "validation_error",
        "a justification of at least 10 characters is required",
      ),
    );
    setup();
    const dialog = await openDialog(/verify candidate/i);
    await userEvent.type(within(dialog).getByLabelText(/justification/i), longText);
    await userEvent.click(within(dialog).getByRole("button", { name: /continue/i }));
    await userEvent.click(within(dialog).getByRole("button", { name: /record decision/i }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/at least 10 characters/);
    expect(within(dialog).getByLabelText(/justification/i)).toHaveValue(longText);
  });

  it("handles a concurrent change (409): explains it and reloads the candidate", async () => {
    vi.spyOn(consoleApi, "submitReview").mockRejectedValue(
      new ApiError(409, "invalid_state_transition", "already decided"),
    );
    setup();
    const detail = vi.mocked(consoleApi.candidate);
    const dialog = await openDialog(/verify candidate/i);
    await userEvent.type(within(dialog).getByLabelText(/justification/i), longText);
    await userEvent.click(within(dialog).getByRole("button", { name: /continue/i }));
    const before = detail.mock.calls.length;
    await userEvent.click(within(dialog).getByRole("button", { name: /record decision/i }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /changed since you opened it/i,
    );
    await waitFor(() => expect(detail.mock.calls.length).toBeGreaterThan(before));
  });

  it("reports a forbidden decision without leaking server detail", async () => {
    vi.spyOn(consoleApi, "submitReview").mockRejectedValue(
      new ApiError(403, "forbidden", "internal rule x"),
    );
    setup();
    const dialog = await openDialog(/verify candidate/i);
    await userEvent.type(within(dialog).getByLabelText(/justification/i), longText);
    await userEvent.click(within(dialog).getByRole("button", { name: /continue/i }));
    await userEvent.click(within(dialog).getByRole("button", { name: /record decision/i }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(/not permitted to review/i);
    expect(alert).not.toHaveTextContent(/internal rule/);
  });

  it("closes with Escape and returns focus to the trigger", async () => {
    setup();
    const trigger = await screen.findByRole("button", { name: /request more evidence/i });
    await userEvent.click(trigger);
    expect(screen.getByLabelText(/justification/i)).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("opens a case from a verified candidate and navigates to it", async () => {
    const open = vi
      .spyOn(consoleApi, "openCase")
      .mockResolvedValue({ id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc" } as never);
    setup(
      candidateDetail({
        status: "confirmed",
        actions: {
          can_review: true,
          allowed_decisions: ["reject"],
          confirm_blockers: [],
          can_open_case: true,
          open_case_blockers: [],
        },
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /open inspection case/i }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /open case/i }),
    );
    await waitFor(() =>
      expect(nav.push).toHaveBeenCalledWith("/cases/cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
    );
    expect(open).toHaveBeenCalledWith(CAND_ID);
  });

  it("shows the API's release-gate refusal when opening a case fails", async () => {
    vi.spyOn(consoleApi, "openCase").mockRejectedValue(
      new ApiError(
        409,
        "verification_required",
        "only an officer-verified candidate can be released",
      ),
    );
    setup(
      candidateDetail({
        status: "confirmed",
        actions: {
          can_review: true,
          allowed_decisions: ["reject"],
          confirm_blockers: [],
          can_open_case: true,
          open_case_blockers: [],
        },
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /open inspection case/i }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /open case/i }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/officer-verified/);
    expect(nav.push).not.toHaveBeenCalled();
  });
});

describe("candidate detail states", () => {
  it("shows an error with retry when the candidate cannot be loaded (e.g. other jurisdiction)", async () => {
    resetNav();
    asUser(FULL_PERMS);
    vi.spyOn(consoleApi, "candidate").mockRejectedValue(new ApiError(404, "not_found", "x"));
    vi.spyOn(consoleApi, "evaluations").mockResolvedValue([]);
    vi.spyOn(consoleApi, "reviews").mockResolvedValue([]);
    renderWithClient(<CandidateDetailPage params={resolved({ id: CAND_ID })} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
    expect(screen.getByRole("alert")).toHaveTextContent(
      /outside the jurisdictions you can access/i,
    );
    void footprint;
    void candidate;
    void jsonResponse;
    void J1;
  });
});
