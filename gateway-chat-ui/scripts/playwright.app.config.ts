import { defineConfig } from "@playwright/test";

/** App 8081 E2E — 使用本机已安装的 Chrome，无需 npx playwright install */
export default defineConfig({
  testDir: ".",
  testMatch: "e2e-app-send.spec.ts",
  timeout: 90_000,
  use: {
    baseURL: process.env.APP_URL ?? "https://121.41.81.58:8081/",
    channel: "chrome",
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  },
});
