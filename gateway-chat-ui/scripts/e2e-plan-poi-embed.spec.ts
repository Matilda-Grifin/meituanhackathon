/**
 * 用真实/文档化 Agent 输出跑 PlanMessageBody，验收 POI 卡 + 正文无 amap 残片。
 * Run: npm run test:plan-poi
 */
import { test, expect } from "@playwright/test";
import { PLAN_POI_FIXTURES } from "./fixtures/plan-poi/fixtures";

test.describe("plan POI embed — real output fixtures", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("http://127.0.0.1:5199/", { waitUntil: "networkidle" });
  });

  for (const fx of PLAN_POI_FIXTURES) {
    test(`${fx.id}: ${fx.label}`, async ({ page }) => {
      const section = page.locator(`[data-testid="fixture-${fx.id}"]`);
      await expect(section).toBeVisible();

      const poiCount = Number(await section.getAttribute("data-poi-count"));
      if (fx.pois.some((p) => fx.plan.includes(p.name.slice(0, 2)))) {
        expect(poiCount, "daily 段应嵌 POI 卡").toBeGreaterThan(0);
      }

      const markdown = section.locator(".plan-message-body .markdown-body");
      const mdCount = await markdown.count();
      for (let i = 0; i < mdCount; i++) {
        const block = markdown.nth(i);
        const links = block.locator('a[href*="amap.com/place"]');
        await expect(links, "正文 markdown 段不应含 amap 链接").toHaveCount(0);

        const html = await block.innerHTML();
        for (const re of fx.forbidInMarkdown) {
          expect(re.test(html), `HTML 命中禁止模式 ${re}`).toBe(false);
        }

        const text = await block.innerText();
        for (const re of fx.forbidInMarkdown) {
          expect(re.test(text), `纯文本命中禁止模式 ${re}: ${text.slice(0, 120)}`).toBe(false);
        }
      }

      const rawMarkdown = (await section.getAttribute("data-markdown-text")) ?? "";
      for (const re of fx.forbidInMarkdown) {
        expect(re.test(rawMarkdown), `split 后 text 段命中 ${re}`).toBe(false);
      }
      for (const needle of fx.expectTextIncludes) {
        expect(rawMarkdown, `应保留「${needle}」`).toContain(needle);
      }

      const cardLinks = section.locator('.poi-card[href*="amap.com/place"]');
      if (poiCount > 0) {
        await expect(cardLinks.first()).toBeVisible();
      }
    });
  }
});
