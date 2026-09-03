import { defineConfig, devices } from "@playwright/test";

const authPort = 55421;
const appPort = 3100;

export default defineConfig({
  testDir: "./tests/e2e",
  testIgnore: "approval.spec.ts", // Separate production-CSP configuration, no proof-bearing traces.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: `http://127.0.0.1:${appPort}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "node tests/e2e/fake-supabase.mjs",
      port: authPort,
      reuseExistingServer: false,
      env: { FAKE_SUPABASE_PORT: String(authPort) },
    },
    {
      command: "node tests/e2e/fake-dashboard.mjs",
      port: 8000,
      reuseExistingServer: false,
    },
    {
      command: `node_modules/.bin/next dev --webpack --hostname 127.0.0.1 --port ${appPort}`,
      port: appPort,
      reuseExistingServer: false,
      env: {
        NEXT_PUBLIC_SUPABASE_URL: `http://127.0.0.1:${authPort}`,
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_local_e2e",
        BACKEND_API_URL: "http://127.0.0.1:8000",
      },
    },
  ],
});
