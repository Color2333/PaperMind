/**
 * Phase 5 功能 E2E 测试脚本
 * 使用: npx playwright test scripts/test-phase5-e2e.ts
 * 或: npx ts-node scripts/test-phase5-e2e.ts (需安装 playwright)
 * @author Bamzc
 */
import { chromium } from "playwright";

const BASE = "http://localhost:5173";
const PAPER_ID = "c1efeec2-32b4-4abe-825f-ac007e819011";

async function main() {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  const errors: string[] = [];

  page.on("console", (msg) => {
    const type = msg.type();
    const text = msg.text();
    if (type === "error") errors.push(`[Console] ${text}`);
  });

  try {
    // 1. 论文详情页
    console.log("1. 访问论文详情页...");
    await page.goto(`${BASE}/papers/${PAPER_ID}`, { waitUntil: "networkidle" });
    await page.screenshot({ path: "screenshots/paper-detail.png" });

    const hasReasoningBtn = await page.locator('button:has-text("推理链")').count() > 0;
    const hasFigureBtn = await page.locator('button:has-text("图表解读")').count() > 0;
    const hasBrainIcon = await page.locator('button:has(svg)').filter({ hasText: "推理链" }).count() > 0;

    console.log(`  - 推理链按钮: ${hasReasoningBtn ? "✓" : "✗"}`);
    console.log(`  - 图表解读按钮: ${hasFigureBtn ? "✓" : "✗"}`);
    console.log(`  - Brain 图标: ${hasBrainIcon ? "✓" : "✗"}`);

    const reasoningSection = await page.locator('text=推理链深度分析').count() > 0;
    const figureSection = await page.locator('text=图表解读').count() > 0;
    console.log(`  - 推理链区域: ${reasoningSection ? "✓" : "✗"}`);
    console.log(`  - 图表解读区域: ${figureSection ? "✓" : "✗"}`);

    // 2. Graph Explorer
    console.log("\n2. 访问 Graph Explorer...");
    await page.goto(`${BASE}/graph`, { waitUntil: "networkidle" });
    await page.screenshot({ path: "screenshots/graph-explorer.png" });

    const hasGapsTab = await page.locator('button:has-text("研究空白")').count() > 0;
    console.log(`  - 研究空白 Tab: ${hasGapsTab ? "✓" : "✗"}`);

    if (hasGapsTab) {
      await page.click('button:has-text("研究空白")');
      await page.fill('input[placeholder*="关键词"]', "3D gaussian splatting");
      await page.click('button:has-text("查询")');
      await page.waitForTimeout(3000);
      await page.screenshot({ path: "screenshots/graph-gaps.png" });
    }
  } catch (e) {
    console.error("测试失败:", e);
  } finally {
    await browser.close();
  }

  if (errors.length > 0) {
    console.log("\n控制台错误:");
    errors.forEach((e) => console.log("  -", e));
  }
}

main();
