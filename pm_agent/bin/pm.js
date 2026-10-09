#!/usr/bin/env node
// PaperMind `pm` — 确定性 CLI 入口（设计④ §3/§5）。
//
// 三模式骨架：
//   pm               无参数 → 交互 TUI（E2c 接线裁剪后的 Pi core；当前打印引导）
//   pm -p "prompt"   一次性 AI 调用（E2c）
//   pm <subcommand>  确定性命令面（本骨架已实现；--json 机器输出 + 稳定退出码）
//
// 退出码契约：0 成功 / 2 用法错误 / 3 未登录 / 4 服务端业务错误 / 5 网络错误。
import { run } from "../src/cli.js";

const argv = process.argv.slice(2);

// 三模式分发：子命令 → 确定性路径；无参/-p/-tui → agent（E2c）
const AGENT_MODES = new Set(["-tui", "--tui"]);
const codingTools = argv.includes("--coding");
const jsonMode = argv.includes("--json"); // Pi 事件流输出（Web 聊天桥消费）
const sessionFlagIdx = argv.indexOf("--session");
const sessionFile = sessionFlagIdx >= 0 ? argv[sessionFlagIdx + 1] : undefined;
const restArgs = argv.filter(
	(a, i) =>
		a !== "--coding" &&
		a !== "--json" &&
		a !== "--session" &&
		!(sessionFlagIdx >= 0 && i === sessionFlagIdx + 1),
);
const isAgentMode =
	restArgs.length === 0 || restArgs[0] === "-p" || restArgs[0] === "--prompt" || AGENT_MODES.has(restArgs[0]);

if (isAgentMode && (jsonMode || sessionFlagIdx >= 0)) {
	// webchat 桥模式（host.py spawn：pm -p --json --session <file>）——本地 pi
	// JSON 事件流，工具经用户 JWT 调 PaperMind API
	try {
		const { runPmOneshot, runPmTui } = await import("../src/agent/session.js");
		if (restArgs[0] === "-p" || restArgs[0] === "--prompt") {
			const prompt = restArgs.slice(1).join(" ").trim();
			if (!prompt) {
				process.stderr.write('用法: pm -p "<提示词>" --json [--session <文件>]\n');
				process.exitCode = 2;
			} else {
				process.exitCode = await runPmOneshot(prompt, { codingTools, mode: "json", sessionFile });
			}
		} else {
			process.stderr.write('用法: 桥模式需 --json（pm -p "<提示词>" --json）\n');
			process.exitCode = 2;
		}
	} catch (err) {
		process.stderr.write(`pm agent 启动失败：${err?.message || err}\n`);
		process.stderr.write(
			"提示：模型凭据保存在 ~/.config/papermind/agent（auth.json / models.json），与 PaperMind 登录分离。\n",
		);
		process.exitCode = 1;
	}
} else if (isAgentMode && (restArgs[0] === "-tui" || restArgs[0] === "--tui")) {
	// 本地 Pi 完整 TUI：需要 agentDir 模型凭据（数据/会话在本地）
	try {
		const { runPmTui } = await import("../src/agent/session.js");
		process.exitCode = await runPmTui({ codingTools });
	} catch (err) {
		process.stderr.write(`pm TUI 启动失败：${err?.message || err}\n`);
		process.stderr.write(
			"提示：模型凭据保存在 PAPERMIND_AGENT_DIR（auth.json / models.json），与 PaperMind 登录分离。\n",
		);
		process.exitCode = 1;
	}
} else if (isAgentMode && (restArgs[0] === "-p" || restArgs[0] === "--prompt")) {
	// 纯文本 -p / 无参：远程 agent（方案 A）——agent loop/工具/LLM（Pi 网关）全在
	// 服务端 /agent/chat SSE，CLI 零本地模型凭据。无参 → cli.js 交互模式提示。
	try {
		const { run } = await import("../src/cli.js");
		process.exitCode = await run(argv);
	} catch (err) {
		process.stderr.write(`pm 远程 agent 失败：${err?.message || err}\n`);
		process.exitCode = 1;
	}
} else if (isAgentMode) {
	// 无参：云端会话 REPL（数据全在服务端，零本地模型凭据）——经 cli.js
	try {
		const { run } = await import("../src/cli.js");
		process.exitCode = await run(argv);
	} catch (err) {
		process.stderr.write(`pm 交互失败：${err?.message || err}\n`);
		process.exitCode = 1;
	}
} else if (restArgs[0] === "gateway") {
	// pm gateway：Pi LLM 网关（OpenAI 兼容 HTTP 面，Python 管线共用）
	try {
		await import("../src/gateway.js");
	} catch (err) {
		process.stderr.write(`pm gateway 启动失败：${err?.message || err}\n`);
		process.exitCode = 1;
	}
} else {
	run(argv)
		.then((code) => {
			process.exitCode = code;
		})
		.catch((err) => {
			process.stderr.write(`pm 内部错误：${err?.stack || err}\n`);
			process.exitCode = 1;
		});
}
