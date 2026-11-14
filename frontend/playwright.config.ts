import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests",
  timeout: 30000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8008",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {},
  },
  webServer: {
    command: `${process.env.NAVIGATOR_TEST_PYTHON || "../.venv/bin/python"} ../tests/e2e_server.py`,
    url: "http://127.0.0.1:8008/health/live",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
