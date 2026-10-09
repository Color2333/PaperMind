// pm 的 agent 会话组装（E2c）：以 Pi 为 upstream、同进程、深度定制但零上游源码改动。
//
// 组装原则（product profile，设计④ §4）：
// - Pi 内置 coding tools 全关（noTools:"all"），只挂 PaperMind 受控工具集；
// - agentDir 隔离到 ~/.config/papermind/agent——PaperMind 的模型凭据（auth.json/
//   models.json）与 Pi 上游互不可见，与 PaperMind token 分开保存（设计④ §7）；
// - 系统提示/主题经 ResourceLoader override 注入（默认资源关闭），不改上游文件。
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
	InteractiveMode,
	SessionManager,
	SettingsManager,
	createAgentSessionFromServices,
	createAgentSessionRuntime,
	createAgentSessionServices,
	createEditTool,
	createFindTool,
	createGrepTool,
	createLsTool,
	createReadTool,
	createWriteTool,
	runPrintMode,
} from "@earendil-works/pi-coding-agent";

import { PAPERMIND_SYSTEM_PROMPT } from "./prompt.js";
import { papermindTools } from "./tools.js";

export function pmAgentDir() {
	return process.env.PAPERMIND_AGENT_DIR || join(homedir(), ".config", "papermind", "agent");
}

const THEMES_SRC = join(fileURLToPath(new URL(".", import.meta.url)), "../../../../extension/themes");

/** 1.1.0 默认资源加载器原生扫描 <agentDir>/themes/*.json——首次启动把 fork 主题布署进去 */
function ensureAgentThemes(agentDir) {
	const destDir = join(agentDir, "themes");
	try {
		mkdirSync(destDir, { recursive: true });
		for (const name of ["papermind-dark.json", "papermind-light.json"]) {
			const dest = join(destDir, name);
			if (existsSync(dest)) continue;
			const src = join(THEMES_SRC, name);
			if (existsSync(src)) copyFileSync(src, dest);
		}
	} catch {
		// 主题布署失败不阻塞启动（回退系统主题）
	}
}

/** PaperMind 资源装载定制（注入点全部来自 DefaultResourceLoaderOptions 公开契约）。
 * 主题：1.1.0 默认资源加载器原生扫描 <agentDir>/themes/*.json——把主题 JSON 放进
 * agentDir/themes/ 即生效（此前的 themesOverride + theme-loader 子路径导入在
 * 1.1.0 已不存在）。 */
function pmResourceLoaderOverrides() {
	return {
		noSkills: true,
		noPromptTemplates: true,
		noContextFiles: true,
		systemPromptOverride: () => PAPERMIND_SYSTEM_PROMPT,
		appendSystemPromptOverride: () => [],
	};
}

/**
 * 工作区文件工具（查看/修改——写论文场景的核心能力）：
 * read/grep/find/ls + edit/write。bash/powershell **不在其中**——
 * research profile 永不含任意 shell 执行（设计④验收标准）；
 * `--coding` 显式开启时才经 createCodingTools 恢复完整 coding 工具。
 */
function workspaceFileTools(cwd) {
	return {
		read: createReadTool(cwd),
		edit: createEditTool(cwd),
		write: createWriteTool(cwd),
		grep: createGrepTool(cwd),
		find: createFindTool(cwd),
		ls: createLsTool(cwd),
	};
}

/**
 * 创建 PaperMind 定制的 AgentSessionRuntime（pm 无参 TUI 与 -p 一次性共用）。
 * options: { cwd?, sessionManager?, codingTools? }
 */
export async function createPmRuntime(options = {}) {
	const cwd = options.cwd || process.cwd();
	const agentDir = pmAgentDir();
	ensureAgentThemes(agentDir);

		const createRuntime = async ({ cwd: c, agentDir: a, sessionManager, sessionStartEvent }) => {
		// patch 0002：pm 是研究终端，无 coding 操作——project trust 交互整体跳过
		const settingsManager = SettingsManager.create(c, a, { projectTrusted: true });
		const services = await createAgentSessionServices({
			cwd: c,
			agentDir: a,
			settingsManager,
			resourceLoaderOptions: pmResourceLoaderOverrides(),
		});
		// product profile（Zotero+AI 定位）：
		// - PaperMind 受控工具集 + 工作区文件工具（read/edit/write/grep/find/ls——
		//   查看/修改，写论文的核心能力）；
		// - bash/powershell 零构造（research profile 永不含任意 shell 执行）；
		// - noTools:"all" 连 customTools 也会禁用——必须显式 allowlist。
		const pmTools = papermindTools();
		const baseTools = options.codingTools ? undefined : workspaceFileTools(c);
		const created = await createAgentSessionFromServices({
			services,
			sessionManager,
			sessionStartEvent,
			baseToolsOverride: baseTools, // undefined = --coding 恢复 Pi 上游默认（完整 coding 工具）
			noTools: "all",
			tools: [...pmTools.map((t) => t.name), ...(baseTools ? Object.keys(baseTools) : [])],
			customTools: pmTools, // 含领域 renderer（E6）
		});
		return { ...created, services, diagnostics: [] };
	};

	return createAgentSessionRuntime(createRuntime, {
		cwd,
		agentDir,
		sessionManager: options.sessionManager || SessionManager.create(cwd, join(pmAgentDir(), "sessions")),
	});
}

/** pm -p "prompt"：一次性 AI 调用（headless，text 输出，返回退出码）。
 * options.mode="json"：输出 Pi agent 事件流（每行一个 JSON 事件）——
 * Web 聊天桥（packages/agent_pi）据此翻译成 SSE；
 * options.sessionFile：续接既有 Pi 会话文件（多轮上下文由 Pi 会话承载）。
 * 注意：runPrintMode 的 finally 已 dispose runtime——这里不得二次 dispose
 * （二次 dispose 会让 extension runner 的 shutdown 事件等待挂死）。 */
export async function runPmOneshot(prompt, { cwd, codingTools = false, mode = "text", sessionFile } = {}) {
	const sessionManager = resolveSessionManager(cwd || process.cwd(), sessionFile);
	const runtime = await createPmRuntime({
		cwd,
		codingTools,
		sessionManager,
	});
	return runPrintMode(runtime, { mode, messages: [prompt] });
}

/** 会话解析：--session 指向既有文件则续接（open），否则新会话落到该路径
 * （setSessionFile——web 聊天的每会话持久化由 Python 桥按 conversation_id 建路径）。 */
function resolveSessionManager(cwd, sessionFile) {
	if (!sessionFile) return SessionManager.inMemory();
	if (existsSync(sessionFile)) {
		return SessionManager.open(sessionFile, undefined, cwd);
	}
	const manager = SessionManager.create(cwd, dirname(sessionFile));
	manager.setSessionFile(sessionFile);
	return manager;
}

/** pm（无参数）：交互 TUI（E2c） */
export async function runPmTui({ cwd, initialMessage, codingTools = false } = {}) {
	const modelsPath = join(pmAgentDir(), "models.json");
	if (!existsSync(modelsPath)) {
		process.stderr.write(
			`提示：${pmAgentDir()} 下未检测到 models.json——进入 TUI 后输入 /login 可配置 provider（或手动放置 models.json + settings.json）。\n`,
		);
	}
	const runtime = await createPmRuntime({ cwd, codingTools });
	const interactive = new InteractiveMode(runtime, {
		modelFallbackMessage: runtime.modelFallbackMessage,
		startupDiagnostics: runtime.diagnostics || [],
		verbose: false,
		initialMessage,
		initialThemeSetting: "papermind-dark",
	});
	await interactive.init();
	try {
		await interactive.run();
	} finally {
		interactive.stop();
	}
}
