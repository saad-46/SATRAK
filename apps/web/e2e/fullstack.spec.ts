import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

/**
 * Real-API journey. Runs only when E2E_STACK_FILE points at the JSON written by
 * `python -m tests.e2e_stack.serve` (apps/api), i.e. the real FastAPI app on PostgreSQL/PostGIS
 * with row-level security, the hash-chained audit log and a fake OIDC issuer. Skipped otherwise,
 * so the default `playwright test` stays hermetic.
 */
const file = process.env.E2E_STACK_FILE;
test.skip(!file, "E2E_STACK_FILE not set: no real API stack running");
test.describe.configure({ mode: "serial" });

interface Stack {
  tokens: Record<string, string>;
  user_ids: Record<string, string>;
  candidate_id: string;
}
const stack = (): Stack => JSON.parse(readFileSync(file!, "utf-8")) as Stack;

async function signIn(page: Page, who: string, path = "/dashboard") {
  await page.goto(path);
  await page.getByLabel("Access token").fill(stack().tokens[who]!);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("a rejected token returns to sign-in with an expiry message (real 401)", async ({ page }) => {
  await page.goto("/dashboard");
  await page.getByLabel("Access token").fill("not.a.token");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/your session has expired/i)).toBeVisible();
});

test("a user without any grant is shown no-access, not an empty console", async ({ page }) => {
  await signIn(page, "nobody");
  await expect(page.getByRole("heading", { name: "No access" })).toBeVisible();
});

test("another jurisdiction's officer sees no candidates and cannot open this one", async ({
  page,
}) => {
  await signIn(page, "outsider");
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  await expect(
    page.getByText("Candidates awaiting review").locator("..").getByText("0"),
  ).toBeVisible();
  await page.goto(`/candidates/${stack().candidate_id}`);
  await expect(page.getByText("Not found", { exact: true })).toBeVisible();
});

test("a supervisor can read the candidate but is not offered verification", async ({ page }) => {
  await signIn(page, "supervisor", `/candidates/${stack().candidate_id}`);
  await expect(page.getByRole("heading", { name: "Officer conclusion" })).toBeVisible();
  await expect(page.getByText(/does not include verification/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Verify candidate" })).toHaveCount(0);
});

test("reviewer: dashboard, candidate, verify, open case, assign, investigate, field finding", async ({
  page,
}) => {
  const s = stack();
  await signIn(page, "reviewer");
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  await expect(
    page.getByText("Candidates awaiting review").locator("..").getByText("1"),
  ).toBeVisible();

  await page.getByRole("link", { name: /candidates awaiting review/i }).click();
  await page.getByRole("link", { name: /1 Mar 2026/ }).click();

  await expect(page.getByRole("heading", { name: /model inference/i })).toBeVisible();
  await expect(page.getByText("87%")).toBeVisible();
  await page.getByRole("button", { name: "Verify candidate" }).click();
  const dialog = page.getByRole("dialog", { name: "Verify candidate" });
  await dialog
    .getByLabel(/justification/i)
    .fill("Frame visible on the tile and no matching permit footprint.");
  await dialog.getByRole("button", { name: "Continue" }).click();
  await dialog.getByRole("button", { name: "Record decision" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Verified by officer").first()).toBeVisible();

  await page.getByRole("button", { name: "Open inspection case" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Open case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}/);
  await expect(page.getByRole("heading", { name: /^Case [0-9a-f]{8}$/, level: 1 })).toBeVisible();

  await page.getByRole("button", { name: "Assign", exact: true }).click();
  const assign = page.getByRole("dialog", { name: "Assign case" });
  await assign.getByLabel(/assignee user id/i).fill(s.user_ids.reviewer!);
  await assign.getByRole("button", { name: "Assign", exact: true }).click();
  await expect(assign).toBeHidden();

  await page.getByRole("button", { name: "Start investigation" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("Under investigation").first()).toBeVisible();

  await page.getByRole("button", { name: /record case finding/i }).click();
  const finding = page.getByRole("dialog", { name: "Record case finding" });
  await finding
    .getByLabel(/site-visit notes/i)
    .fill("Site visit: slab and columns present, no sanction board.");
  await finding.getByRole("button", { name: "Record finding" }).click();
  await expect(finding).toBeHidden();
  await expect(page.getByText(/Case finding #1 \(field inspection\)/)).toBeVisible();

  // The candidate page now links to the case and offers no further decisions.
  await page.goto(`/candidates/${s.candidate_id}`);
  await expect(page.getByRole("link", { name: /open case/i })).toBeVisible();
  await expect(page.getByText(/already has an open case/i)).toBeVisible();
});
