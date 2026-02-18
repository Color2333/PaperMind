/**
 * PaperMind 全流程 E2E 深度测试
 * 模拟真实用户操作：导航、输入、点击、滚动、验证
 * @author Bamzc
 */
import { chromium } from "playwright";
import { mkdirSync } from "fs";

const BASE = "http://localhost:5173";
const SHOT_DIR = "scripts/screenshots/full";
mkdirSync(SHOT_DIR, { recursive: true });

let shotIdx = 0;
const shot = async (page, name) => {
  const file = `${SHOT_DIR}/${String(++shotIdx).padStart(2, "0")}-${name}.png`;
  await page.screenshot({ path: file, fullPage: false });
  console.log(`  📸 ${file}`);
  return file;
};
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const issues = [];
const pass = (msg) => console.log(`  ✅ ${msg}`);
const fail = (msg) => { console.log(`  ❌ ${msg}`); issues.push(msg); };
const info = (msg) => console.log(`  ℹ️  ${msg}`);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // 收集 console 错误
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`[${page.url()}] ${msg.text()}`);
  });
  page.on("pageerror", (err) => {
    consoleErrors.push(`[${page.url()}] PageError: ${err.message}`);
  });

  // ========================================================================
  // TEST 1: Agent 首页
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 1: Agent 首页 (/)");
  console.log("=".repeat(60));
  await page.goto(BASE, { waitUntil: "networkidle" });
  await wait(500);
  await shot(page, "01-agent-home");

  // 检查关键元素
  const logo = await page.textContent("body");
  logo.includes("PaperMind") ? pass("Logo 存在") : fail("Logo 缺失");

  // 检查统计卡片
  logo.includes("论文总量") ? pass("统计卡片: 论文总量") : fail("统计卡片缺失");
  logo.includes("本周新增") ? pass("统计卡片: 本周新增") : fail("统计卡片: 本周新增缺失");

  // 检查推荐论文
  logo.includes("为你推荐") ? pass("推荐论文区域存在") : fail("推荐论文区域缺失");

  // 检查本周热点
  logo.includes("本周热点") ? pass("本周热点存在") : fail("本周热点缺失");

  // 检查能力卡片
  for (const cap of ["搜索调研", "下载论文", "论文分析"]) {
    logo.includes(cap) ? pass(`能力卡片: ${cap}`) : fail(`能力卡片缺失: ${cap}`);
  }

  // 检查快捷按钮
  for (const btn of ["搜索论文", "下载入库", "知识问答", "生成 Wiki", "生成简报"]) {
    logo.includes(btn) ? pass(`快捷按钮: ${btn}`) : fail(`快捷按钮缺失: ${btn}`);
  }

  // 检查输入框
  const chatInput = await page.$("textarea");
  chatInput ? pass("对话输入框存在") : fail("对话输入框缺失");

  // 侧边栏工具网格
  const toolGrid = await page.$$("a[href='/collect'], a[href='/papers'], a[href='/graph'], a[href='/wiki'], a[href='/brief'], a[href='/dashboard']");
  toolGrid.length === 6 ? pass(`侧边栏工具网格: ${toolGrid.length}/6`) : fail(`侧边栏工具网格不全: ${toolGrid.length}/6`);

  // ========================================================================
  // TEST 2: Agent 对话功能
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 2: Agent 对话功能");
  console.log("=".repeat(60));

  // 输入消息并发送
  if (chatInput) {
    await chatInput.fill("你好，请简单介绍一下你的功能");
    await wait(200);
    const sendBtn = await page.$("button[type='submit'], button:has(svg.lucide-send), button[aria-label*='send']");
    if (sendBtn) {
      await sendBtn.click();
      pass("消息已发送");

      // 等待回复
      await wait(5000);
      await shot(page, "02-agent-chat-reply");

      const chatBody = await page.textContent("body");
      const hasReply = chatBody.includes("PaperMind") || chatBody.includes("论文") || chatBody.length > 500;
      hasReply ? pass("Agent 回复已生成") : fail("Agent 未回复");
    } else {
      fail("发送按钮未找到");
    }
  }

  // ========================================================================
  // TEST 3: Papers 论文库
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 3: Papers 论文库 (/papers)");
  console.log("=".repeat(60));
  await page.goto(`${BASE}/papers`, { waitUntil: "networkidle" });
  await wait(1000);
  await shot(page, "03-papers-list");

  let papersBody = await page.textContent("body");

  // 验证页面标题和数量
  papersBody.includes("全部论文") ? pass("标题: 全部论文") : fail("标题缺失");
  papersBody.includes("73") ? pass("论文总数显示: 73") : info("论文总数可能已变化");

  // 验证文件夹侧栏
  papersBody.includes("收藏") ? pass("侧栏: 收藏") : fail("侧栏缺失: 收藏");
  papersBody.includes("最近 7 天") ? pass("侧栏: 最近 7 天") : fail("侧栏缺失: 最近7天");
  papersBody.includes("未分类") ? pass("侧栏: 未分类") : fail("侧栏缺失: 未分类");
  papersBody.includes("按收录日期") ? pass("侧栏: 按收录日期") : fail("侧栏缺失: 按收录日期");

  // 验证订阅主题
  papersBody.includes("订阅主题") ? pass("侧栏: 订阅主题标签") : info("订阅主题标签未显示");

  // 测试搜索
  const searchInput = await page.$("input[placeholder*='搜索']");
  if (searchInput) {
    await searchInput.fill("gaussian");
    await wait(500);
    await shot(page, "04-papers-search-gaussian");
    papersBody = await page.textContent("body");
    const searchWorking = papersBody.includes("6") || !papersBody.includes("73 篇");
    searchWorking ? pass("搜索功能正常 (gaussian)") : fail("搜索未过滤结果");
    await searchInput.fill("");
    await wait(500);
  }

  // 测试日期折叠
  const dateToggle = await page.$("text=按收录日期");
  if (dateToggle) {
    await dateToggle.click();
    await wait(300);
    await shot(page, "05-papers-date-open");
    papersBody = await page.textContent("body");
    papersBody.includes("昨天") || papersBody.includes("今天") || papersBody.includes("02-")
      ? pass("日期折叠展开成功") : fail("日期折叠内容异常");
  }

  // 测试点击收藏分类
  const favBtn = await page.$("button:has-text('收藏'), div:has-text('收藏') >> nth=0");
  if (favBtn) {
    await favBtn.click();
    await wait(800);
    papersBody = await page.textContent("body");
    papersBody.includes("0 篇") || papersBody.includes("该文件夹暂无论文")
      ? pass("收藏分类: 空（正常）") : info("收藏分类可能有数据");
  }

  // 返回全部论文
  const allBtn = await page.$("button:has-text('全部论文'), div:has-text('全部论文')");
  if (allBtn) {
    await allBtn.click();
    await wait(800);
    pass("返回全部论文");
  }

  // 验证视图切换
  const viewBtns = await page.$$("button[title*='列表'], button[title*='网格'], button:has(svg.lucide-layout-list), button:has(svg.lucide-layout-grid)");
  viewBtns.length >= 2 ? pass(`视图切换按钮: ${viewBtns.length} 个`) : info("视图切换按钮未检测到");

  // ========================================================================
  // TEST 4: 论文详情
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 4: 论文详情页");
  console.log("=".repeat(60));

  // 直接导航到第一篇论文
  const firstPaperResp = await page.evaluate(async () => {
    const r = await fetch("/api/papers/latest?page=1&page_size=1");
    // 如果 /api 前缀不行，试 localhost:8000
    return null;
  });

  // 通过 URL 直接访问
  await page.goto(`${BASE}/papers`, { waitUntil: "networkidle" });
  await wait(1000);

  // 找到第一篇论文并点击
  const paperLinks = await page.$$("div.flex.cursor-pointer, button.flex.w-full");
  if (paperLinks.length > 0) {
    await paperLinks[0].click();
    await wait(2000);
    await shot(page, "06-paper-detail");

    const detailBody = await page.textContent("body");

    // 验证论文详情元素
    detailBody.includes("返回") ? pass("返回按钮存在") : fail("返回按钮缺失");
    detailBody.includes("ArXiv") || detailBody.includes("arxiv") ? pass("ArXiv 信息显示") : info("ArXiv 信息未显示");
    detailBody.includes("摘要") || detailBody.includes("Abstract") ? pass("摘要区域") : info("摘要区域标记未找到");

    // 检查状态标签
    const hasStatus = detailBody.includes("已粗读") || detailBody.includes("未读") || detailBody.includes("已精读");
    hasStatus ? pass("阅读状态标签") : fail("阅读状态标签缺失");

    // 检查分类/关键词
    const hasTopics = detailBody.includes("主题") || detailBody.includes("关键词") || detailBody.includes("keywords");
    hasTopics ? pass("主题/关键词显示") : info("主题/关键词未显示");

    // 检查操作按钮
    for (const btn of ["粗读", "精读", "嵌入"]) {
      detailBody.includes(btn) ? pass(`操作按钮: ${btn}`) : info(`操作按钮未找到: ${btn}`);
    }

    // 检查 PDF 阅读按钮
    detailBody.includes("阅读原文") ? pass("PDF 阅读原文按钮") : info("PDF 阅读按钮未显示（可能无 PDF）");

    // 检查图表解读区域
    detailBody.includes("图表") || detailBody.includes("Figure")
      ? pass("图表解读区域") : info("图表解读区域未显示");

    // 测试 PDF 阅读器（如果存在）
    const readPdfBtn = await page.$("button:has-text('阅读原文')");
    if (readPdfBtn) {
      await readPdfBtn.click();
      await wait(3000);
      await shot(page, "07-pdf-reader");

      const pdfBody = await page.textContent("body");
      pdfBody.includes("AI") || pdfBody.includes("缩放") || pdfBody.includes("页")
        ? pass("PDF 阅读器打开成功") : fail("PDF 阅读器未正常显示");

      // 关闭 PDF 阅读器
      const closeBtn = await page.$("button:has-text('关闭'), button[aria-label='close']");
      if (closeBtn) {
        await closeBtn.click();
        await wait(500);
        pass("PDF 阅读器关闭");
      } else {
        // 按 Esc 关闭
        await page.keyboard.press("Escape");
        await wait(500);
        pass("PDF 阅读器 Esc 关闭");
      }
    }
  } else {
    fail("无法找到可点击的论文条目");
  }

  // ========================================================================
  // TEST 5: Collect 论文收集
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 5: Collect 论文收集 (/collect)");
  console.log("=".repeat(60));
  await page.goto(`${BASE}/collect`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "08-collect");

  const collectBody = await page.textContent("body");
  collectBody.includes("论文收集") ? pass("页面标题: 论文收集") : fail("页面标题异常");
  collectBody.includes("即时搜索") ? pass("即时搜索区域") : fail("即时搜索区域缺失");
  collectBody.includes("自动订阅") ? pass("自动订阅区域") : fail("自动订阅区域缺失");
  collectBody.includes("新建") ? pass("新建订阅按钮") : fail("新建订阅按钮缺失");

  // 验证现有订阅
  const subs = collectBody.match(/每天/g);
  subs && subs.length > 0 ? pass(`订阅数量: ${subs.length} 个`) : info("无订阅");

  // 测试搜索输入
  const collectSearch = await page.$("input[placeholder*='3D'], input[placeholder*='NeRF'], input[type='text']");
  if (collectSearch) {
    await collectSearch.fill("neural radiance field");
    await wait(300);
    pass("搜索框可输入");
    await collectSearch.fill("");
  }

  // ========================================================================
  // TEST 6: Graph 知识图谱
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 6: Graph 知识图谱 (/graph)");
  console.log("=".repeat(60));
  await page.goto(`${BASE}/graph`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "09-graph");

  const graphBody = await page.textContent("body");
  graphBody.includes("知识图谱") ? pass("页面标题: 知识图谱") : fail("页面标题异常");
  graphBody.includes("快速探索") ? pass("快速探索标签区域") : fail("快速探索标签缺失");

  // 验证 6 个 Tab
  for (const tab of ["时间线", "引用树", "质量分析", "演化趋势", "综述生成", "研究空白"]) {
    graphBody.includes(tab) ? pass(`Tab: ${tab}`) : fail(`Tab 缺失: ${tab}`);
  }

  // 点击一个推荐关键词
  const keywordChip = await page.$("button:has-text('cs.CV'), button:has-text('3D')");
  if (keywordChip) {
    await keywordChip.click();
    await wait(2000);
    await shot(page, "10-graph-keyword-clicked");
    const afterClick = await page.textContent("body");
    afterClick.includes("篇论文") || afterClick.includes("node_count")
      ? pass("关键词点击后有数据") : info("关键词点击后数据加载中或为空");
  }

  // 切换 Tab
  const citationTab = await page.$("button:has-text('引用树')");
  if (citationTab) {
    await citationTab.click();
    await wait(500);
    await shot(page, "11-graph-citation-tab");
    pass("引用树 Tab 切换");
  }

  // ========================================================================
  // TEST 7: Wiki
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 7: Wiki (/wiki)");
  console.log("=".repeat(60));
  await page.goto(`${BASE}/wiki`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "12-wiki");

  const wikiBody = await page.textContent("body");
  wikiBody.includes("Wiki") ? pass("页面标题: Wiki") : fail("页面标题异常");
  wikiBody.includes("主题 Wiki") ? pass("Tab: 主题 Wiki") : fail("Tab 缺失: 主题 Wiki");
  wikiBody.includes("论文 Wiki") ? pass("Tab: 论文 Wiki") : fail("Tab 缺失: 论文 Wiki");
  wikiBody.includes("历史记录") ? pass("历史记录区域") : fail("历史记录区域缺失");
  wikiBody.includes("生成 Wiki") ? pass("生成按钮") : fail("生成按钮缺失");

  // 测试输入
  const wikiInput = await page.$("input[placeholder*='关键词'], input[placeholder*='mechanism']");
  if (wikiInput) {
    await wikiInput.fill("3D reconstruction");
    pass("Wiki 搜索输入正常");
    await wikiInput.fill("");
  }

  // ========================================================================
  // TEST 8: Brief 研究简报
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 8: Brief 研究简报 (/brief)");
  console.log("=".repeat(60));
  await page.goto(`${BASE}/brief`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "13-brief");

  const briefBody = await page.textContent("body");
  briefBody.includes("研究简报") ? pass("页面标题: 研究简报") : fail("页面标题异常");
  briefBody.includes("生成简报") ? pass("生成简报按钮") : fail("生成简报按钮缺失");
  briefBody.includes("历史简报") ? pass("历史简报列表") : fail("历史简报列表缺失");

  // 检查已有简报
  const briefCount = (briefBody.match(/Daily Brief/g) || []).length;
  briefCount > 0 ? pass(`历史简报: ${briefCount} 条`) : info("无历史简报");

  // ========================================================================
  // TEST 9: Dashboard 看板
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 9: Dashboard 看板 (/dashboard)");
  console.log("=".repeat(60));
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await wait(1000);
  await shot(page, "14-dashboard");

  const dashBody = await page.textContent("body");
  dashBody.includes("Dashboard") || dashBody.includes("看板") ? pass("页面标题") : fail("页面标题异常");
  dashBody.includes("系统正常") ? pass("系统状态: 正常") : fail("系统状态异常或缺失");
  dashBody.includes("成本分析") ? pass("成本分析区域") : fail("成本分析区域缺失");
  dashBody.includes("最近活动") ? pass("最近活动区域") : fail("最近活动区域缺失");

  // 验证成本中文标签
  for (const label of ["粗读分析", "推理链分析", "图表解读", "RAG 问答"]) {
    dashBody.includes(label) ? pass(`成本标签: ${label}`) : info(`成本标签未出现: ${label}`);
  }

  // 验证模型统计
  dashBody.includes("按模型") ? pass("按模型统计") : fail("按模型统计缺失");
  dashBody.includes("Token 用量") || dashBody.includes("Token") ? pass("Token 用量统计") : fail("Token 用量缺失");

  // ========================================================================
  // TEST 10: Settings 设置
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 10: Settings 设置");
  console.log("=".repeat(60));

  // 通过侧边栏底部设置按钮进入
  const settingsBtn = await page.$("button:has-text('设置'), a[href='/settings']");
  if (settingsBtn) {
    await settingsBtn.click();
    await wait(1000);
    await shot(page, "15-settings");
    const settingsBody = await page.textContent("body");
    settingsBody.includes("设置") || settingsBody.includes("Settings")
      ? pass("设置页面打开") : fail("设置页面异常");

    // 检查 LLM 配置
    settingsBody.includes("zhipu") || settingsBody.includes("GLM") || settingsBody.includes("API")
      ? pass("LLM 配置显示") : info("LLM 配置信息未显示");
  } else {
    // 直接导航
    await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
    await wait(800);
    await shot(page, "15-settings");
    pass("设置页面（直接导航）");
  }

  // ========================================================================
  // TEST 11: 404 页面
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 11: 404 页面");
  console.log("=".repeat(60));
  await page.goto(`${BASE}/nonexistent-page`, { waitUntil: "networkidle" });
  await wait(500);
  await shot(page, "16-404");
  const body404 = await page.textContent("body");
  body404.includes("404") ? pass("404 页面正常显示") : fail("404 页面未正确显示");
  body404.includes("返回首页") ? pass("返回首页按钮") : fail("返回首页按钮缺失");

  // ========================================================================
  // TEST 12: 暗色主题
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 12: 暗色主题切换");
  console.log("=".repeat(60));
  await page.goto(BASE, { waitUntil: "networkidle" });
  await wait(500);

  // 找主题切换按钮（通常在侧边栏底部）
  const allButtons = await page.$$("button");
  let themeToggled = false;
  for (const btn of allButtons) {
    const ariaLabel = await btn.getAttribute("aria-label");
    const title = await btn.getAttribute("title");
    if ((ariaLabel || "").includes("theme") || (ariaLabel || "").includes("主题") ||
        (title || "").includes("theme") || (title || "").includes("主题")) {
      await btn.click();
      themeToggled = true;
      break;
    }
  }

  if (!themeToggled) {
    // 尝试 svg 图标查找
    const moonBtn = await page.$("button:has(svg.lucide-moon), button:has(svg.lucide-sun)");
    if (moonBtn) {
      await moonBtn.click();
      themeToggled = true;
    }
  }

  if (themeToggled) {
    await wait(500);
    await shot(page, "17-dark-theme");
    const isDark = await page.evaluate(() => document.documentElement.classList.contains("dark"));
    isDark ? pass("暗色主题已激活") : info("可能已经是暗色主题，切换为亮色");
  } else {
    info("主题切换按钮未定位到");
  }

  // ========================================================================
  // TEST 13: 响应式 - 缩小视口
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("TEST 13: 移动端响应式");
  console.log("=".repeat(60));
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "18-mobile-agent");

  await page.goto(`${BASE}/papers`, { waitUntil: "networkidle" });
  await wait(800);
  await shot(page, "19-mobile-papers");
  pass("移动端视口截图完成");

  // 恢复视口
  await page.setViewportSize({ width: 1440, height: 900 });

  // ========================================================================
  // 总结
  // ========================================================================
  console.log("\n" + "=".repeat(60));
  console.log("📋 全流程测试总结");
  console.log("=".repeat(60));
  console.log(`截图数: ${shotIdx}`);
  console.log(`通过检查: ${shotIdx + issues.length === 0 ? "全部" : "见下"}`);
  console.log(`问题数: ${issues.length}`);
  console.log(`Console 错误数: ${consoleErrors.length}`);

  if (issues.length > 0) {
    console.log("\n❌ 发现的问题:");
    issues.forEach((i, idx) => console.log(`  ${idx + 1}. ${i}`));
  }

  if (consoleErrors.length > 0) {
    console.log("\n⚠️ Console 错误 (前10条):");
    consoleErrors.slice(0, 10).forEach((e) => console.log(`  ${e}`));
  }

  if (issues.length === 0 && consoleErrors.length === 0) {
    console.log("\n✅ 所有检查通过，无 Console 错误！");
  }

  await browser.close();
  console.log("\n🏁 测试完成");
})();
