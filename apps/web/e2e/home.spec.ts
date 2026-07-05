import { expect, test } from "@playwright/test";

test("landing page renders the SATRAK shell", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "SATRAK", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "System status" })).toBeVisible();
});

test("unknown route shows the 404 page", async ({ page }) => {
  await page.goto("/this-route-does-not-exist");
  await expect(page.getByText("404")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
});
