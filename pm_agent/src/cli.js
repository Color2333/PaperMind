// `pm` 命令解析与分发（设计④ §5 确定性命令面 v1）。
//
// 退出码契约：0 成功 / 2 用法错误 / 3 未登录 / 4 服务端业务错误 / 5 网络错误。
// --json：canonical result 原样输出，无 ANSI、无装饰、无截断。
import { EXIT } from "./http-client.js";
import { cmdDoctor, cmdLogin, cmdLogout, cmdWhoami } from "./auth.js";
import * as cmd from "./commands.js";

const DIM_SF = (id) => `\x1b[2mconversation: ${id}\x1b[0m`;

const USAGE = `pm — PaperMind Research Terminal（确定性命令面 v1）

用法：
  pm login --endpoint <url> [--client-name NAME]    设备码授权登录
  pm logout / pm whoami / pm doctor                 身份与体检
  pm papers search <query> [--limit N]              多渠道论文搜索
  pm papers show <paper-id>                         论文详情
  pm questions show <question-id>                   研究问题
  pm claims list --question <id> [--status a,b]     Claim 列表
  pm claims show <claim-id>                         Claim 证据卡
  pm diff --question <id>                           研究 Diff 时间线
  pm export <question-id> [--format research-pack]  Research Pack 导出
  pm jobs list [--status s] [--limit N]             durable Job 列表
  pm jobs show <job-id>                             Job graph（tasks/attempts）
  pm jobs cancel <job-id>                           取消 Job
  pm tasks retry <task-id>                          重试 dead_letter 任务
  pm queue pause | pm queue resume                  队列暂停/恢复

全局开关：--json（机器输出，canonical result 原样，无 ANSI）

交互模式（后续版本接线）：pm（无参数，TUI）、pm -p "..."（一次性 AI）`;

export class UsageError extends Error {
	constructor(message, meta = {}) {
		super(message);
		this.meta = meta;
	}
}

function parseGlobalFlags(argv) {
	const json = argv.includes("--json");
	const rest = argv.filter((a) => a !== "--json");
	return { json, rest };
}

export async function run(argv) {
	const { json, rest } = parseGlobalFlags(argv);
	const [head, ...tail] = rest;

	// 三模式骨架：无参数（TUI）与 -p（一次性）在 E2c 接线裁剪后的 Pi core
	// 无参：云端会话交互（数据存服务端——与 Web 聊天同一存储）；本地 Pi TUI 用 pm -tui
	if (!head) {
		const { authedClient: ac } = await import("./http-client.js");
		const client = await ac({ endpoint: flagOf(tail, "--endpoint") });
		if (!client) {
			process.stderr.write("未登录：先 pm login --endpoint <url>\n");
			return EXIT.NOT_AUTHED;
		}
		const { runRemoteChat } = await import("./agent/remote.js");
		return (await runRemoteChat({ client })) || EXIT.OK;
	}
	if (head === "chat") {
		const { authedClient: ac } = await import("./http-client.js");
		const client = await ac({ endpoint: flagOf(tail, "--endpoint") });
		if (!client) {
			process.stderr.write("未登录：先 pm login --endpoint <url>\n");
			return EXIT.NOT_AUTHED;
		}
		const { runRemoteChat } = await import("./agent/remote.js");
		return (await runRemoteChat({ client })) || EXIT.OK;
	}
	if (head === "-p" || head === "--prompt") {
		// 远程 agent（方案 A）：/agent/chat SSE——agent loop/工具/LLM 全在服务端
		const rest = tail.filter((a) => a !== "--new");
		const forceNew = tail.includes("--new");
		const message = rest.join(" ").trim();
		if (!message) {
			process.stderr.write('用法: pm -p "<消息>" [-c <conversation-id>] [--new]\n');
			return EXIT.USAGE;
		}
		const { authedClient } = await import("./http-client.js");
		const client = await authedClient({ endpoint: flagOf(tail, "--endpoint") });
		if (!client) {
			process.stderr.write("未登录：先 pm login --endpoint <url>\n");
			return EXIT.NOT_AUTHED;
		}
		const { runRemotePrompt, loadAgentConversationId } = await import("./agent/remote.js");
		const flagC = flagOf(tail, "-c") || flagOf(tail, "--conversation");
		const stored = forceNew ? null : await loadAgentConversationId();
		const { conversationId, ok } = await runRemotePrompt({
			client,
			message,
			conversationId: flagC || stored,
		});
		if (conversationId) {
			process.stderr.write(`${DIM_SF(conversationId)}\n`);
		}
		return ok ? EXIT.OK : EXIT.SERVER;
	}
	if (head === "-h" || head === "--help" || head === "help") {
		process.stdout.write(USAGE + "\n");
		return EXIT.OK;
	}
	if (head === "--version" || head === "-v") {
		process.stdout.write("pm 0.1.0 (@papermind/cli)\n");
		return EXIT.OK;
	}

	try {
		return await dispatch(head, tail, json);
	} catch (err) {
		if (err instanceof UsageError) {
			process.stderr.write(json ? JSON.stringify({ error: "usage", message: err.message, ...err.meta }) : `${err.message}\n`);
			return EXIT.USAGE;
		}
		throw err;
	}
}

function required(value, name, meta = {}) {
	if (!value) throw new UsageError(`缺少参数：<${name}>`, { argument: name, ...meta });
	return value;
}

function flagOf(args, flag, fallback = undefined) {
	const idx = args.indexOf(flag);
	if (idx === -1) return fallback;
	args.splice(idx, 1);
	return args.splice(idx, 1)[0] ?? fallback;
}

function listFlagOf(args, flag, fallback = []) {
	const idx = args.indexOf(flag);
	if (idx === -1) return fallback;
	args.splice(idx, 1);
	const value = args.splice(idx, 1)[0];
	return value ? value.split(",").map((s) => s.trim()) : fallback;
}

function dispatch(head, args, json) {
	switch (head) {
		case "login": {
			const endpoint = flagOf(args, "--endpoint");
			const clientName = flagOf(args, "--client-name", "pm-cli");
			const openBrowser = args.includes("--open-browser");
			return cmdLogin({ endpoint: required(endpoint, "endpoint", { flag: "--endpoint" }), clientName, json, openBrowser });
		}
		case "logout":
			return cmdLogout({ json });
		case "whoami":
		case "me":
			return cmdWhoami({ json });
		case "doctor":
			return cmdDoctor({ json });
		case "papers":
			return dispatchPapers(args, json);
		case "question":
		case "questions":
			return dispatchQuestions(args, json);
		case "claims":
			return dispatchClaims(args, json);
		case "diff":
			return cmd.diffResearchState({ questionId: required(flagOf(args, "--question"), "question-id", { flag: "--question" }), json });
		case "export": {
			const questionId = required(args.shift(), "question-id");
			const format = flagOf(args, "--format", "research-pack");
			return cmd.exportResearchObject({ questionId, format, json });
		}
		case "jobs":
			return dispatchJobs(args, json);
		case "tasks":
			return dispatchTasks(args, json);
		case "queue": {
			const action = args.shift();
			if (action !== "pause" && action !== "resume") {
				throw new UsageError("用法: pm queue pause | pm queue resume");
			}
			return cmd.queueControl({ action, json });
		}
		case "ask":
		case "demo":
			throw new UsageError(`pm ${head} 将在后续阶段接入（E2c TUI / Phase 6 Demo 引导）`);
		default:
			throw new UsageError(`未知命令：${head}（pm --help）`, { command: head });
	}
}

function dispatchPapers(args, json) {
	const sub = args.shift();
	switch (sub) {
		case "search": {
			const query = required(args.shift(), "query");
			const limit = Number(flagOf(args, "--limit", "10"));
			return cmd.papersSearch({ query, limit: Number.isFinite(limit) ? limit : 10, json });
		}
		case "show":
			return cmd.papersShow({ paperId: required(args.shift(), "paper-id"), json });
		default:
			throw new UsageError("用法: pm papers search|show ...");
	}
}

function dispatchQuestions(args, json) {
	const sub = args.shift();
	if (sub !== "show") throw new UsageError("用法: pm questions show <question-id>");
	return cmd.questionsShow({ questionId: required(args.shift(), "question-id"), json });
}

function dispatchClaims(args, json) {
	const sub = args.shift();
	switch (sub) {
		case "list": {
			const questionId = required(flagOf(args, "--question"), "question-id", { flag: "--question" });
			const statuses = listFlagOf(args, "--status");
			return cmd.claimsList({ questionId, statuses, json });
		}
		case "show":
			return cmd.claimsShow({ claimId: required(args.shift(), "claim-id"), json });
		default:
			throw new UsageError("用法: pm claims list|show ...");
	}
}

function dispatchJobs(args, json) {
	const sub = args.shift();
	switch (sub) {
		case "list": {
			const status = flagOf(args, "--status") || null;
			const limit = Number(flagOf(args, "--limit", "20"));
			return cmd.jobsList({ status, limit: Number.isFinite(limit) ? limit : 20, json });
		}
		case "show":
			return cmd.jobsShow({ jobId: required(args.shift(), "job-id"), json });
		case "cancel":
			return cmd.jobsCancel({ jobId: required(args.shift(), "job-id"), json });
		default:
			throw new UsageError("用法: pm jobs list|show|cancel ...");
	}
}

function dispatchTasks(args, json) {
	const sub = args.shift();
	if (sub !== "retry") throw new UsageError("用法: pm tasks retry <task-id>");
	return cmd.tasksRetry({ taskId: required(args.shift(), "task-id"), json });
}
