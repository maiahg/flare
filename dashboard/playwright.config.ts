import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config. Assumes the FastAPI backend is already running on :8000 with a
 * migrated DB + Redis (make up && make run), and starts the Next.js dev server
 * itself via `webServer`.
 *
 * Run: `pnpm exec playwright install chromium` once, then `pnpm test:e2e`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
