import { expect, test, type Page } from "@playwright/test";
import { CAND, CASE, TOKEN, installApi, type State } from "./support/stub-api";

/**
 * Officer-console journey against a *stubbed* API (no database, no identity provider):
 * dashboard -> candidate queue -> candidate -> verify -> open case -> case transition.
 * The stub mirrors the API contract (see docs/OFFICER_CONSOLE.md) and keeps state, so the
 * UI is exercised end to end. It proves the UI flow, not the server; server-side authorisation,
 * RLS and the release gate are covered by apps/api tests/db against real PostgreSQL.
 */
async function signIn(page: Page) {
  await page.goto("/dashboard");
  await page.getByLabel("Access token").fill(TOKEN);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("officer journey: dashboard, candidate, verify, open case, transition", async ({ page }) => {
  const s: State = {
    status: "unverified",
    caseId: null,
    caseStatus: "created",
    caseVersion: 1,
    reviews: [],
    expired: false,
  };
  await installApi(page, s);
  await signIn(page);

  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  await expect(page.getByText("Simulated test data", { exact: false }).first()).toBeVisible();
  await expect(page.getByText(/no overdue figure is shown/i)).toBeVisible();

  await page.getByRole("link", { name: /candidates awaiting review/i }).click();
  await expect(page).toHaveURL(/\/candidates\?status=unverified/);
  await expect(page.getByRole("heading", { name: "Candidates", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: /1 Sept 2026/ }).click();

  await expect(page.getByRole("heading", { name: /^Candidate aaaaaaaa/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /candidate footprint/i })).toBeVisible();
  await page.getByRole("button", { name: "Verify candidate" }).click();
  const dialog = page.getByRole("dialog", { name: "Verify candidate" });
  await dialog
    .getByLabel(/justification/i)
    .fill("Roof slab visible in scene-1; no permit located.");
  await dialog.getByRole("button", { name: "Continue" }).click();
  await dialog.getByRole("button", { name: "Record decision" }).click();
  await expect(dialog).toBeHidden();
  await expect(
    page.getByText("Decision recorded: Verify candidate", { exact: false }),
  ).toBeAttached();
  await expect(page.getByText("Verified by officer").first()).toBeVisible();

  await page.getByRole("button", { name: "Open inspection case" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Open case" }).click();
  await expect(page).toHaveURL(new RegExp(`/cases/${CASE}`));
  await expect(page.getByRole("heading", { name: /^Case cccccccc/ })).toBeVisible();

  await page.getByRole("button", { name: "Mark assigned" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("button", { name: "Start investigation" })).toBeVisible();
});

test("expired session returns the officer to sign-in with an explanation", async ({ page }) => {
  const s: State = {
    status: "unverified",
    caseId: null,
    caseStatus: "created",
    caseVersion: 1,
    reviews: [],
    expired: false,
  };
  await installApi(page, s);
  await signIn(page);
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  s.expired = true;
  await page.getByRole("link", { name: "Candidates", exact: true }).first().click();
  await expect(page.getByText(/your session has expired/i)).toBeVisible();
  await expect(page.getByLabel("Access token")).toBeVisible();
});

test("a candidate decided elsewhere is reported as a conflict, not silently overwritten", async ({
  page,
}) => {
  const s: State = {
    status: "unverified",
    caseId: null,
    caseStatus: "created",
    caseVersion: 1,
    reviews: [],
    expired: false,
  };
  await installApi(page, s);
  await signIn(page);
  await page.goto(`/candidates/${CAND}`);
  await page.getByRole("button", { name: "Reject candidate" }).click();
  s.status = "confirmed"; // another officer decided in the meantime
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/justification/i).fill("Looks like an existing structure.");
  await dialog.getByRole("button", { name: "Continue" }).click();
  await dialog.getByRole("button", { name: "Record decision" }).click();
  await expect(dialog.getByRole("alert")).toContainText(/changed since you opened it/i);
});
