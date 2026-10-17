import { expect, test, type Page } from "@playwright/test";
import { CAND, CASE, TOKEN, installApi, type State } from "./support/stub-api";

/**
 * Real-browser accessibility checks (Chromium) that jsdom cannot make: rendered colour contrast in
 * both themes, keyboard focus order/visibility, modal isolation, and the accessibility tree a
 * screen reader is given. This is NOT a substitute for axe-core or for testing with NVDA/JAWS/
 * VoiceOver; it measures WCAG 2.2 AA contrast (1.4.3) and verifies keyboard operability (2.1.1,
 * 2.4.3, 2.4.7) and modal behaviour on the pages the officer workflow uses.
 */
const fresh = (over: Partial<State> = {}): State => ({
  status: "unverified",
  caseId: null,
  caseStatus: "created",
  caseVersion: 1,
  reviews: [],
  expired: false,
  ...over,
});

async function signIn(page: Page, path = "/dashboard") {
  await page.goto(path);
  await page.getByLabel("Access token").fill(TOKEN);
  await page.getByRole("button", { name: "Sign in" }).click();
}

interface ContrastFailure {
  text: string;
  ratio: number;
  required: number;
  fg: string;
  bg: string;
  selector: string;
}

/** Measures every visible, enabled text node against its effective (alpha-composited) background. */
async function contrastFailures(page: Page): Promise<ContrastFailure[]> {
  return page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    type RGBA = [number, number, number, number];
    const parse = (css: string): RGBA => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000";
      ctx.fillStyle = css;
      ctx.fillRect(0, 0, 1, 1);
      const d = ctx.getImageData(0, 0, 1, 1).data;
      // getImageData returns premultiplied-then-unpremultiplied 8-bit; fine at this precision.
      return [d[0]!, d[1]!, d[2]!, d[3]! / 255];
    };
    const over = (top: RGBA, below: RGBA): RGBA => {
      const a = top[3] + below[3] * (1 - top[3]);
      if (a === 0) return [0, 0, 0, 0];
      const mix = (i: 0 | 1 | 2) => (top[i] * top[3] + below[i] * below[3] * (1 - top[3])) / a;
      return [mix(0), mix(1), mix(2), a];
    };
    const lum = ([r, g, b]: RGBA) => {
      const f = (c: number) => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const bgOf = (el: Element): RGBA => {
      const chain: RGBA[] = [];
      for (let n: Element | null = el; n; n = n.parentElement) {
        const cs = getComputedStyle(n);
        if (cs.backgroundImage !== "none") chain.push([128, 128, 128, 1]); // unknown: flagged below
        chain.push(parse(cs.backgroundColor));
      }
      let acc: RGBA = [255, 255, 255, 1];
      for (const c of chain.reverse()) acc = over(c, acc);
      return acc;
    };
    const describe = (el: Element) =>
      el.tagName.toLowerCase() +
      (el.id ? `#${el.id}` : "") +
      (typeof el.className === "string" && el.className
        ? "." + el.className.split(/\s+/).slice(0, 3).join(".")
        : "");

    const failures: ContrastFailure[] = [];
    const seen = new Set<Element>();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.textContent?.trim();
      const el = node.parentElement;
      if (!text || !el || seen.has(el)) continue;
      seen.add(el);
      if (el.closest("script,style,noscript,[hidden],[inert]")) continue;
      const cs = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      if (cs.visibility === "hidden" || cs.display === "none" || rect.width === 0) continue;
      if (el.closest("[disabled],[aria-disabled=true]")) continue; // exempt by WCAG 1.4.3
      if (el.closest(".sr-only") && !el.matches(":focus")) continue;
      const bg = bgOf(el);
      const fg = over(parse(cs.color), bg);
      const [l1, l2] = [lum(fg), lum(bg)].sort((a, b) => b - a) as [number, number];
      const ratio = (l1 + 0.05) / (l2 + 0.05);
      const size = parseFloat(cs.fontSize);
      const bold = parseInt(cs.fontWeight, 10) >= 700;
      const required = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
      if (ratio < required)
        failures.push({
          text: text.slice(0, 40),
          ratio: Math.round(ratio * 100) / 100,
          required,
          fg: `rgb(${fg.slice(0, 3).map(Math.round)})`,
          bg: `rgb(${bg.slice(0, 3).map(Math.round)})`,
          selector: describe(el),
        });
    }
    return failures;
  });
}

test("contrast checker detects a failing pair (negative control)", async ({ page }) => {
  await page.setContent(
    '<body style="background:#fff"><p id="bad" style="color:#aaa">low contrast</p>' +
      '<p style="color:#000">ok</p></body>',
  );
  const failures = await contrastFailures(page);
  expect(failures.map((f) => f.text)).toEqual(["low contrast"]);
  expect(failures[0]!.ratio).toBeLessThan(2.5);
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });

    test("text contrast meets WCAG AA on sign-in and every officer page", async ({ page }) => {
      const state = fresh();
      await installApi(page, state);
      const report: Record<string, ContrastFailure[]> = {};

      await page.goto("/dashboard");
      await expect(page.getByLabel("Access token")).toBeVisible();
      report["sign-in"] = await contrastFailures(page);

      await signIn(page);
      await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
      report["dashboard"] = await contrastFailures(page);

      for (const [name, path, heading] of [
        ["candidates", "/candidates", "Candidates"],
        ["candidate", `/candidates/${CAND}`, /^Candidate aaaaaaaa/],
      ] as const) {
        await page.goto(path);
        await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
        report[name] = await contrastFailures(page);
      }

      await page.getByRole("button", { name: "Verify candidate" }).click();
      await expect(page.getByRole("dialog", { name: "Verify candidate" })).toBeVisible();
      report["verify-dialog"] = await contrastFailures(page);
      await page.keyboard.press("Escape");

      state.status = "confirmed";
      state.caseId = CASE;
      await page.goto(`/cases/${CASE}`);
      await expect(page.getByRole("heading", { name: /^Case cccccccc/, level: 1 })).toBeVisible();
      report["case"] = await contrastFailures(page);
      await page.goto("/cases");
      await expect(page.getByRole("heading", { name: "Cases", level: 1 })).toBeVisible();
      report["cases"] = await contrastFailures(page);

      await test.info().attach(`contrast-${scheme}.json`, {
        body: JSON.stringify(report, null, 2),
        contentType: "application/json",
      });
      expect(report).toEqual(Object.fromEntries(Object.keys(report).map((k) => [k, []])));
    });
  });
}

test("keyboard: skip link is first, focus is always visible, the whole verify flow works", async ({
  page,
}) => {
  await installApi(page, fresh());
  await signIn(page, `/candidates/${CAND}`);
  await expect(page.getByRole("heading", { name: /^Candidate aaaaaaaa/ })).toBeVisible();

  // First Tab stop on a freshly loaded page is the skip link.
  await page.goto(`/candidates/${CAND}`);
  await expect(page.getByRole("heading", { name: /^Candidate aaaaaaaa/ })).toBeVisible();
  await page.locator("body").press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();

  // Every tab stop up to the Verify button has a visible focus indicator.
  const verify = page.getByRole("button", { name: "Verify candidate" });
  const unindicated: string[] = [];
  for (let i = 0; i < 40; i++) {
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      const outlined = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
      const shadowed = cs.boxShadow !== "none";
      return {
        label: (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 30),
        ok: outlined || shadowed,
        name: el.tagName,
      };
    });
    if (info && !info.ok) unindicated.push(`${info.name}:${info.label}`);
    if (await verify.evaluate((n) => n === document.activeElement)) break;
    await page.keyboard.press("Tab");
  }
  expect(unindicated).toEqual([]);
  await expect(verify).toBeFocused();

  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Verify candidate" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel(/justification/i)).toBeFocused();
  await page.keyboard.type("Frame visible on the tile and no matching permit footprint.");
  await dialog.getByRole("button", { name: "Continue" }).focus();
  await page.keyboard.press("Enter");
  await dialog.getByRole("button", { name: "Record decision" }).focus();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Verified by officer").first()).toBeVisible();
});

test("modal: background is inert, Tab/Shift+Tab never leave the dialog, Escape restores focus", async ({
  page,
}) => {
  await installApi(page, fresh());
  await signIn(page, `/candidates/${CAND}`);
  const trigger = page.getByRole("button", { name: "Verify candidate" });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Verify candidate" });
  await expect(dialog).toBeVisible();

  // The page behind the dialog is removed from the accessibility tree and from the tab order.
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Skip to content" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  expect(await page.evaluate(() => document.querySelectorAll("[inert]").length)).toBeGreaterThan(0);

  const outside: string[] = [];
  for (const key of ["Tab", "Tab", "Tab", "Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab"]) {
    await page.keyboard.press(key);
    const inside = await dialog.evaluate((d) => d.contains(document.activeElement));
    if (!inside) outside.push(key);
  }
  expect(outside).toEqual([]);

  // Pointer clicks on the backdrop must not reach the page underneath.
  await page.mouse.click(5, 5);
  await expect(dialog).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(page.getByRole("navigation", { name: "Primary" }).first()).toBeVisible();
  expect(await page.evaluate(() => document.querySelectorAll("[inert]").length)).toBe(0);
});

test("screen reader tree: landmarks, one h1, labelled dialog, status announcements", async ({
  page,
}) => {
  await installApi(page, fresh());
  await signIn(page, `/candidates/${CAND}`);
  await expect(page.getByRole("heading", { name: /^Candidate aaaaaaaa/ })).toBeVisible();

  await expect(page.getByRole("banner")).toHaveCount(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("navigation", { name: "Primary" }).first()).toBeAttached();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);

  const main = await page.getByRole("main").ariaSnapshot();
  await test.info().attach("aria-snapshot-candidate.yml", {
    body: main,
    contentType: "text/yaml",
  });
  // Decision controls are real buttons with names, never bare divs.
  expect(main).toMatch(/button "Verify candidate"/);
  // The footprint graphic is exposed as a labelled image with a text alternative.
  expect(main).toMatch(/img "[^"]*footprint/i);

  await page.getByRole("button", { name: "Verify candidate" }).click();
  const dialog = page.getByRole("dialog", { name: "Verify candidate" });
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  const snap = await dialog.ariaSnapshot();
  await test.info().attach("aria-snapshot-dialog.yml", { body: snap, contentType: "text/yaml" });
  expect(snap).toMatch(/heading "Verify candidate"/);
  expect(snap).toMatch(/textbox "[^"]*justification/i);
});
