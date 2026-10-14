import { defineConfig } from "@playwright/test";

// Starts the API (fresh database, fast travel) and the built web app, then drives a real browser.
// Locally without Playwright's browser download, point PW_CHROME at any Chrome/Chromium binary.
export default defineConfig({
  testDir: ".",
  timeout: 120_000,
  workers: 1,
  use: {
    baseURL: "http://localhost:3100",
    launchOptions: {
      executablePath: process.env.PW_CHROME || undefined,
      args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
    },
  },
  webServer: [
    {
      command: "rm -rf .data-e2e && AICIV_DATA_DIR=.data-e2e AICIV_TRAVEL_SECONDS=0.5 AICIV_RESEARCH_MODE=fixture AICIV_BELT_SPEED=40 AICIV_TICK_SCALE=0.2 AICIV_ALLOWED_ORIGINS=http://localhost:3100 python -m uvicorn services.api.main:app --port 8100",
      cwd: "../..",
      url: "http://localhost:8100/api/health",
      reuseExistingServer: false,
      env: { PATH: process.env.PYTHON_BIN_DIR ? `${process.env.PYTHON_BIN_DIR}:${process.env.PATH}` : process.env.PATH! },
    },
    {
      command: "NEXT_PUBLIC_API_URL=http://localhost:8100 npx next build && npx next start -p 3100",
      cwd: "../../apps/web",
      url: "http://localhost:3100",
      timeout: 240_000,
      reuseExistingServer: false,
    },
  ],
});
