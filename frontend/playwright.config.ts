import process from "node:process";
import { defineConfig, devices } from "@playwright/test";
import { baseUrl, environment } from "./e2e/profile.ts";

// Browser tests against the production build behind FastAPI: its real CSP, cookie and sign-in.
const ci = Boolean(process.env.CI);

export default defineConfig({
  testDir: "e2e",
  testMatch: /\.e2e\.ts$/u,
  outputDir: "test-results",
  forbidOnly: ci,
  reporter: ci ? [["github"], ["list"]] : "list",
  // biome-ignore lint/style/useNamingConvention: Playwright's option
  use: { ...devices["Desktop Chrome"], baseURL: baseUrl, trace: "retain-on-failure" },
  projects: [
    // Signs in once per role through the form; the specs reuse the saved sessions.
    { name: "sign-in", testMatch: /\.setup\.ts$/u },
    // Every spec in both colour schemes, so axe checks the contrast of each.
    { name: "light", dependencies: ["sign-in"], use: { colorScheme: "light" } },
    { name: "dark", dependencies: ["sign-in"], use: { colorScheme: "dark" } },
  ],
  webServer: {
    command: "frontend/e2e/server.sh",
    cwd: "..",
    env: environment,
    url: `${baseUrl}/readyz`,
    reuseExistingServer: false, // never test whatever else listens on the port
    timeout: 180_000, // the build included
    gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
  },
});
