import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PE_CONVERGENCE_BASE_URL;
if (baseURL === undefined || !/^http:\/\/127\.0\.0\.1:\d{4,5}$/u.test(baseURL)) {
  throw new Error("PE_CONVERGENCE_BASE_URL must name the disposable IPv4 loopback host");
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: "loopback-built.spec.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  reporter: "list",
  outputDir: "../test-results/loopback-built-playwright",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-built-loopback",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
