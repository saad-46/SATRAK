import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config. Runs against a locally-built app; CI builds once then serves.
 * Kept to Chromium for the foundation smoke test; more browsers added later.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "pnpm start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      SKIP_ENV_VALIDATION: "true",
      NEXT_PUBLIC_API_URL: "http://localhost:8000",
    },
  },
});
