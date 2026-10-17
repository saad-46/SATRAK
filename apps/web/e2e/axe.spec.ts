import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { CAND, CASE, TOKEN, installApi, type State } from "./support/stub-api";

/**
 * axe-core scan (WCAG 2.0/2.1/2.2 A and AA rules) of the officer console against the stubbed API,
 * in both colour schemes. Automated rules find roughly a third of accessibility problems; this is
 * a regression gate, not a conformance claim, and it does not replace a manual screen-reader pass.
 */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const state = (): State => ({
  status: "confirmed",
  caseId: CASE,
  caseStatus: "created",
  caseVersion: 1,
  reviews: [],
  expired: false,
});

async function scan(page: Page, label: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  await test.info().attach(`axe-${label}.json`, {
    body: JSON.stringify(violations, null, 2),
    contentType: "application/json",
  });
  return violations.map((v) => `${label}: ${v.id} (${v.impact}) x${v.nodes.length} - ${v.help}`);
}

test("axe negative control: a page with known defects is reported", async ({ page }) => {
  await page.setContent(
    '<html lang="en"><body><main><img src="x.png"><button></button></main></body></html>',
  );
  const found = await scan(page, "control");
  expect(found.join("\n")).toMatch(/image-alt/);
  expect(found.join("\n")).toMatch(/button-name/);
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`axe, ${scheme} theme`, () => {
    test.use({ colorScheme: scheme });

    test("sign-in and the main officer pages have no WCAG A/AA violations", async ({ page }) => {
      await installApi(page, state());
      const found: string[] = [];

      await page.goto("/dashboard");
      await expect(page.getByLabel("Access token")).toBeVisible();
      found.push(...(await scan(page, "sign-in")));

      await page.getByLabel("Access token").fill(TOKEN);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
      found.push(...(await scan(page, "dashboard")));

      for (const [label, path, heading] of [
        ["candidates", "/candidates", "Candidates"],
        ["candidate", `/candidates/${CAND}`, /^Candidate aaaaaaaa/],
        ["cases", "/cases", "Cases"],
        ["case", `/cases/${CASE}`, /^Case cccccccc/],
        ["activity", "/activity", "Activity"],
      ] as const) {
        await page.goto(path);
        await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
        found.push(...(await scan(page, label)));
      }

      expect(found).toEqual([]);
    });

    test("the verify dialog (page behind it inert) has no violations", async ({ page }) => {
      await installApi(page, { ...state(), status: "unverified", caseId: null });
      await page.goto(`/candidates/${CAND}`);
      await page.getByLabel("Access token").fill(TOKEN);
      await page.getByRole("button", { name: "Sign in" }).click();
      await page.getByRole("button", { name: "Verify candidate" }).click();
      await expect(page.getByRole("dialog", { name: "Verify candidate" })).toBeVisible();
      expect(await scan(page, "verify-dialog")).toEqual([]);
    });
  });
}
