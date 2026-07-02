/**
 * Smoke test App 8081 send flow.
 * Run: npm run test:app
 * Uses system Chrome (channel: chrome) — no playwright browser download.
 */
import { test, expect } from "@playwright/test";

test("location consent → type → send shows user bubble", async ({ page, context }) => {
  await context.grantPermissions(["geolocation"]);
  await context.setGeolocation({ latitude: 31.2304, longitude: 121.4737 });

  page.on("console", (msg) => {
    if (msg.type() === "error") console.log("browser error:", msg.text());
  });

  await page.goto("/", { waitUntil: "networkidle" });

  const agree = page.getByRole("button", { name: /同意/ });
  if (await agree.isVisible({ timeout: 8000 }).catch(() => false)) {
    await agree.click();
    await expect(page.getByRole("dialog", { name: "位置信息说明" })).toBeHidden({ timeout: 20_000 });
  }

  const input = page.locator(".composer-mobile textarea");
  await expect(input).toBeEnabled({ timeout: 20_000 });

  await input.fill("我想去上海玩");

  await expect
    .poll(async () => page.locator(".composer-mobile .send").isEnabled(), { timeout: 30_000 })
    .toBe(true);

  await page.locator(".composer-mobile .send").click();

  await expect(page.locator(".bubble-row-user .bubble")).toContainText("我想去上海玩", {
    timeout: 25_000,
  });
});
