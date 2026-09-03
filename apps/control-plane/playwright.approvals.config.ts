import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "approval.spec.ts",
  workers: 1,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:3132",
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  projects: [
    { name: "approval-chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: "node tests/e2e/fake-approvals.mjs",
      port: 8132,
      reuseExistingServer: false,
    },
    {
      command: "node_modules/.bin/next start --hostname 127.0.0.1 --port 3132",
      port: 3132,
      reuseExistingServer: false,
      env: {
        APPROVAL_PUBLIC_ORIGIN: "http://127.0.0.1:3132",
        BACKEND_API_URL: "http://127.0.0.1:8132",
      },
    },
  ],
});
