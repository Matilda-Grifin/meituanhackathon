import { defineConfig } from "@playwright/test";

/** 真实 Agent 输出夹具 → PlanMessageBody 渲染验收（本机 Chrome，不重装 Playwright） */
export default defineConfig({
  testDir: ".",
  testMatch: "e2e-plan-poi-embed.spec.ts",
  timeout: 60_000,
  use: {
    channel: "chrome",
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  },
  webServer: {
    command: "npx vite --config scripts/vite.plan-poi-fixture.config.ts",
    cwd: "..",
    port: 5199,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
