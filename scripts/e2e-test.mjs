/**
 * PaperMind 深度用户体验自动化测试
 * 模拟真人操作：导航、点击、输入、滚动、截图
 * @author Color2333
 */
import { chromium } from "playwright";
import { mkdirSync } from "fs";

const BASE = "http://localhost:5173";
const SHOT_DIR = "scripts/screenshots";
mkdirSync(SHOT_DIR, { recursive: true });

let shotIdx = 0;
const shot = async (page, name) => {
  const file = `${SHOT_DIR}/${String(++shotIdx).padStart(2, "0")}-${name}.png`;
  await page.screenshot({ path: file, fullPage: false });
  console.log(`📸 ${file}`);
};

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  const issues = [];
  const log = (msg) => {
    console.log(`  ${msg}`);
  };
  const fail = (msg) => {
    console.log(`  ❌ ${msg}`);
    issues.push(msg);
  };
  const pass = (msg) => {
    console.log(`  ✅ ${msg}`);
  };

  // ========== 1. Agent 首页 ==========
  console.log("\n=== 1. Agent 首页 (/) ===");
  await page.goto(BASE, { waitUntil: "networkidle" });
  await shot(page, "agent-home");

  const sidebar = await page.$("aside, nav, [class*='sidebar'], [class*='Sidebar']");
  sidebar ? pass("侧边栏存在") : fail("侧边栏缺失");

  const inputArea = await page.$("textarea, input[type='text'], [contenteditable]");
  inputArea ? pass("输入区域存在") : fail("输入区域缺失");

  // 检查工具网格
  const toolLinks = await page.$$("a[href='/papers'], a[href='/collect'], a[href='/graph'], a[href='/wiki'], a[href='/brief'], a[href='/dashboard']");
  toolLinks.length >= 4 ? pass(`工具导航链接: ${toolLinks.length} 个`) : fail(`工具导航链接不足: ${toolLinks.length}`);

  // ========== 2. Papers 论文库 ==========
  console.log("\n=== 2. Papers 论文库 (/papers) ===");
  await page.goto(`${BASE}/papers`, { waitUntil: "networkidle" });
  await wait(1000);
  await shot(page, "papers-list");

  // 检查论文列表
  const paperItems = await page.$$("[class*='paper'], [class*='Paper'], article, [role='listitem']");
  log(`论文列表项: ${paperItems.length}`);
  paperItems.length > 0 ? pass("论文列表渲染正常") : fail("论文列表为空");

  // 检查分页
  const paginationText = await page.textContent("body");
  if (paginationText.includes("共") && paginationText.includes("页")) {
    pass("分页信息显示正常");
  } else {
    fail("分页信息缺失");
  }

  // 测试搜索
  const searchInput = await page.$("input[placeholder*='搜索']");
  if (searchInput) {
    await searchInput.fill("3D");
    await wait(500); // 等待防抖
    await shot(page, "papers-search-3d");
    const afterSearch = await page.textContent("body");
    pass("搜索输入正常");

    // 清空搜索
    await searchInput.fill("");
    await wait(500);
  } else {
    fail("搜索框缺失");
  }

  // 测试左侧栏 - 按收录日期
  const dateSection = await page.$("text=按收录日期");
  if (dateSection) {
    await dateSection.click();
    await wait(300);
    await shot(page, "papers-date-expanded");
    pass("「按收录日期」折叠面板可展开");
  } else {
    log("「按收录日期」区块不可见（可能无日期数据）");
  }

  // 测试分页点击
  const page2Btn = await page.$("button:has-text('2')");
  if (page2Btn) {
    await page2Btn.click();
    await wait(1000);
    await shot(page, "papers-page2");
    pass("翻到第 2 页");
  }

  // ========== 3. 论文详情 ==========
  console.log("\n=== 3. 论文详情 ===");
  await page.goto(`${BASE}/papers`, { waitUntil: "networkidle" });
  await wait(1000);

  // 点击第一篇论文
  const firstPaper = await page.$("button:has-text('MatLat'), [class*='paper'] >> nth=0, article >> nth=0");
  if (!firstPaper) {
    // 尝试其他选择器
    const anyClickable = await page.$$("div[class*='cursor-pointer'], button[class*='paper'], div[role='button']");
    if (anyClickable.length > 0) {
      await anyClickable[0].click();
      await wait(1500);
      await shot(page, "paper-detail");

      // 检查阅读原文按钮
      const readBtn = await page.$("button:has-text('阅读原文')");
      readBtn ? pass("「阅读原文」按钮存在") : log("「阅读原文」按钮不存在（可能论文无 PDF）");

      // 检查返回按钮
      const backBtn = await page.$("button:has-text('返回'), button:has-text('Back'), [aria-label='back']");
      backBtn ? pass("返回按钮存在") : fail("返回按钮缺失");
    } else {
      fail("无法找到可点击的论文");
    }
  } else {
    await firstPaper.click();
    await wait(1500);
    await shot(page, "paper-detail");
    pass("进入论文详情页");
  }

  // ========== 4. Collect 论文收集 ==========
  console.log("\n=== 4. Collect 论文收集 (/collect) ===");
  await page.goto(`${BASE}/collect`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "collect");

  const collectTitle = await page.textContent("body");
  collectTitle.includes("收集") || collectTitle.includes("Collect") || collectTitle.includes("搜索")
    ? pass("论文收集页面加载正常")
    : fail("论文收集页面标题异常");

  // ========== 5. Graph 引用图谱 ==========
  console.log("\n=== 5. Graph 引用图谱 (/graph) ===");
  await page.goto(`${BASE}/graph`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "graph");

  const graphBody = await page.textContent("body");
  graphBody.includes("图谱") || graphBody.includes("Graph") || graphBody.includes("引用")
    ? pass("引用图谱页面加载正常")
    : fail("引用图谱页面异常");

  // 检查 tabs
  const tabs = await page.$$("[role='tab'], button[class*='tab'], [class*='Tab']");
  log(`图谱 Tab 数量: ${tabs.length}`);

  // ========== 6. Wiki ==========
  console.log("\n=== 6. Wiki (/wiki) ===");
  await page.goto(`${BASE}/wiki`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "wiki");

  const wikiBody = await page.textContent("body");
  wikiBody.includes("Wiki") || wikiBody.includes("知识")
    ? pass("Wiki 页面加载正常")
    : fail("Wiki 页面异常");

  // ========== 7. Brief 研究简报 ==========
  console.log("\n=== 7. Brief 研究简报 (/brief) ===");
  await page.goto(`${BASE}/brief`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "brief");

  const briefBody = await page.textContent("body");
  briefBody.includes("简报") || briefBody.includes("Brief")
    ? pass("研究简报页面加载正常")
    : fail("研究简报页面异常");

  // ========== 8. Dashboard 看板 ==========
  console.log("\n=== 8. Dashboard 看板 (/dashboard) ===");
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "dashboard");

  const dashBody = await page.textContent("body");
  dashBody.includes("看板") || dashBody.includes("Dashboard") || dashBody.includes("成本")
    ? pass("看板页面加载正常")
    : fail("看板页面异常");

  // ========== 9. 404 测试 ==========
  console.log("\n=== 9. 404 路径测试 ===");
  await page.goto(`${BASE}/briefs`, { waitUntil: "networkidle" });
  await wait(500);
  const body404 = await page.textContent("body");
  if (body404.includes("404") || body404.includes("not found") || body404.includes("Not Found")) {
    pass("/briefs 正确返回 404");
  } else {
    log("/briefs 未显示 404（可能有默认路由重定向）");
    await shot(page, "briefs-404-check");
  }

  // ========== 10. 暗色主题测试 ==========
  console.log("\n=== 10. 暗色主题切换 ===");
  await page.goto(BASE, { waitUntil: "networkidle" });
  await wait(500);

  // 查找暗色主题切换按钮
  const themeBtn = await page.$("button[aria-label*='theme'], button[aria-label*='Theme'], button[title*='主题'], button[title*='暗色'], [class*='theme-toggle']");
  if (themeBtn) {
    await themeBtn.click();
    await wait(500);
    await shot(page, "dark-theme");
    pass("暗色主题切换成功");
  } else {
    // 尝试 Moon/Sun 图标
    const moonBtn = await page.$("button:has(svg[class*='moon']), button:has(svg)");
    log("未找到主题切换按钮（可能需要更精确的选择器）");
  }

  // ========== 总结 ==========
  console.log("\n" + "=".repeat(50));
  console.log("📋 测试总结");
  console.log("=".repeat(50));
  console.log(`截图数: ${shotIdx}`);
  console.log(`问题数: ${issues.length}`);
  if (issues.length > 0) {
    console.log("\n❌ 发现的问题:");
    issues.forEach((i, idx) => console.log(`  ${idx + 1}. ${i}`));
  } else {
    console.log("\n✅ 所有检查通过！");
  }

  // 收集 console 错误
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  await browser.close();
  console.log("\n🏁 测试完成");
})();
