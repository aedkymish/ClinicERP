import { defineConfig, devices } from "@playwright/test";

// Runs against a live stack (API + Next). Credentials of an admin account come from the environment:
//   E2E_BASE_URL (default http://localhost:3000), E2E_USER, E2E_PASSWORD
// E2E_CHANNEL=chrome uses the locally installed Google Chrome instead of the bundled Chromium.
const channel = process.env.E2E_CHANNEL;
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel } },
    { name: "phone", use: { ...devices["Pixel 7"], viewport: { width: 360, height: 780 }, channel } },
  ],
});
