// E2c headless 回环测试：mock LLM（OpenAI completions，SSE）+ mock PaperMind API，
// 通过**子进程执行真实 bin**（`node bin/pm.js -p "..."`）走完整链路：
// bin 入口 → agent loop（LLM→tool_call→PaperMind API→工具结果→最终回答）→ text 输出。
// 验证：受控工具集注册、noTools（Pi 内置工具不可达）、系统提示注入、退出码。
//
// 注：不能在测试进程内 monkeypatch process.stdout.write——Pi print-mode 的输出
// 路径会因此挂死（已实测），故用子进程捕获 stdout（也更贴近真实使用）。
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import http from "node:http";

const BIN = join(dirname(fileURLToPath(import.meta.url)), "..", "bin", "pm.js");

// ---------- mock 服务 ----------

function jsonServer(handler) {
	return new Promise((resolve) => {
		const server = http.createServer((req, res) => {
			let body = "";
			req.on("data", (c) => (body += c));
			req.on("end", () => handler(req, res, body));
		});
		server.listen(0, "127.0.0.1", () => resolve(server));
	});
}

const papermindCalls = [];
function mockPapermind() {
	return jsonServer((req, res) => {
		papermindCalls.push(req.url);
		res.setHeader("Content-Type", "application/json");
		if (req.url.startsWith("/jobs?")) {
			res.end(
				JSON.stringify({
					items: [{ id: "job-1", kind: "StartSkim", status: "succeeded", progress: {} }],
				}),
			);
		} else {
			res.statusCode = 404;
			res.end(JSON.stringify({ detail: "not found" }));
		}
	});
}

const llmRequests = [];
function mockLLM() {
	let round = 0;
	const sse = (res, events) => {
		res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
		for (const ev of events) res.write(`data: ${JSON.stringify(ev)}\n\n`);
		res.write("data: [DONE]\n\n");
		res.end();
	};
	return jsonServer((req, res, body) => {
		round += 1;
		llmRequests.push(JSON.parse(body || "{}"));
		if (round === 1) {
			sse(res, [
				{
					id: "chatcmpl-1",
					choices: [
						{
							index: 0,
							delta: {
								role: "assistant",
								tool_calls: [{ index: 0, id: "call-1", type: "function", function: { name: "pm_list_jobs", arguments: "{}" } }],
							},
						},
					],
				},
				{ id: "chatcmpl-1", choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }] },
			]);
		} else {
			sse(res, [
				{ id: "chatcmpl-2", choices: [{ index: 0, delta: { role: "assistant", content: "查询完成：1 个任务，状态 succeeded。" } }] },
				{ id: "chatcmpl-2", choices: [{ index: 0, delta: {}, finish_reason: "stop" }] },
			]);
		}
	});
}

function runBin(args, env, timeoutMs = 60000) {
	return new Promise((resolve) => {
		const child = spawn(process.execPath, [BIN, ...args], { env, cwd: dirname(BIN) });
		let out = "";
		let err = "";
		const timer = setTimeout(() => {
			child.kill("SIGKILL");
			resolve({ code: -1, out, err: `${err}\n[测试超时 ${timeoutMs}ms]` });
		}, timeoutMs);
		child.stdout.on("data", (c) => (out += c));
		child.stderr.on("data", (c) => (err += c));
		child.on("close", (code) => {
			clearTimeout(timer);
			resolve({ code, out, err });
		});
	});
}

// ---------- 测试 ----------

test("pm -p 全链路（子进程）：LLM tool_call → PaperMind API → 最终回答；内置工具不可达", async () => {
	const dir = mkdtempSync(join(tmpdir(), "pm-agent-test-"));
	const configDir = join(dir, "config");
	const agentDir = join(dir, "agent");
	mkdirSync(configDir, { recursive: true });

	const [pmServer, llmServer] = await Promise.all([mockPapermind(), mockLLM()]);
	const pmPort = pmServer.address().port;
	const llmPort = llmServer.address().port;
	writeFileSync(
		join(configDir, "config.toml"),
		`server_url = "http://127.0.0.1:${pmPort}"\ntoken = "pmt_agent_test"\nclient_name = "pm-cli"\n`,
		"utf8",
	);
	// 模型凭据与 PaperMind 登录分离：agentDir 下独立 models.json/settings.json
	mkdirSync(agentDir, { recursive: true });
	writeFileSync(
		join(agentDir, "models.json"),
		JSON.stringify({
			providers: {
				"pm-mock": {
					name: "PM Mock",
					baseUrl: `http://127.0.0.1:${llmPort}/v1`,
					apiKey: "mock-key",
					api: "openai-completions",
					models: [{ id: "mock-model", name: "Mock Model", reasoning: false, contextWindow: 128000, maxTokens: 4096 }],
				},
			},
		}),
		"utf8",
	);
	writeFileSync(
		join(agentDir, "settings.json"),
		JSON.stringify({ defaultProvider: "pm-mock", defaultModel: "mock-model" }),
		"utf8",
	);

	const env = {
		...process.env,
		PAPERMIND_CONFIG_DIR: configDir,
		PAPERMIND_AGENT_DIR: agentDir,
		PAPERMIND_TOKEN: "",
		PAPERMIND_SERVER_URL: "",
	};

	let result;
	try {
		// 新契约：本地 pi 仅承载 webchat 桥模式（--json）；纯文本 -p 走远程 agent
		result = await runBin(["-p", "我的 skim 任务跑得怎么样了？", "--json"], env);
	} finally {
		pmServer.close();
		llmServer.close();
	}
	const { code, out, err } = result;

	assert.equal(code, 0, `退出码非 0。stderr: ${err.slice(0, 600)}`);
	assert.match(out, /succeeded/, "最终回答应包含工具取回的状态词");
	const ANSI_RE = /\u001b\[/;
	assert.doesNotMatch(out, ANSI_RE, "print 模式输出无 ANSI");
	assert.ok(papermindCalls.some((u) => u.startsWith("/jobs")), "工具应调用 PaperMind /jobs");
	const sys = llmRequests[0]?.messages?.find((m) => m.role === "system")?.content || "";
	assert.match(String(sys), /PaperMind Research Terminal/, "系统提示应为 PaperMind 版");
	const toolNames = JSON.stringify(llmRequests[0]?.tools || []);
	assert.match(toolNames, /pm_list_jobs/);
	assert.match(toolNames, /"read"/, "查看能力（read）可用——写论文场景");
	assert.match(toolNames, /"edit"/, "修改能力（edit）可用——写论文场景");
	assert.doesNotMatch(toolNames, /"bash"/, "research profile：bash 永不可达");
	assert.doesNotMatch(toolNames, /"powershell"/, "research profile：powershell 永不可达");
}, 90000);

// ---------- patch 0001/0002 验证：coding 工具零构造 + trust 跳过 ----------

test("patch 0001/0002：工作区文件工具 6 项构造（bash/powershell 零构造）；trust 跳过", async () => {
	const dir = mkdtempSync(join(tmpdir(), "pm-patch-test-"));
	const configDir = join(dir, "config");
	const agentDir = join(dir, "agent");
	mkdirSync(configDir, { recursive: true });
	mkdirSync(agentDir, { recursive: true });

	const [pmServer, llmServer] = await Promise.all([mockPapermind(), mockLLM()]);
	const pmPort = pmServer.address().port;
	const llmPort = llmServer.address().port;
	writeFileSync(
		join(configDir, "config.toml"),
		`server_url = "http://127.0.0.1:${pmPort}"\ntoken = "pmt_t"\nclient_name = "pm-cli"\n`,
		"utf8",
	);
	writeFileSync(
		join(agentDir, "models.json"),
		JSON.stringify({
			providers: {
				"pm-mock": {
					name: "PM Mock",
					baseUrl: `http://127.0.0.1:${llmPort}/v1`,
					apiKey: "k",
					api: "openai-completions",
					models: [{ id: "mock-model", name: "Mock", reasoning: false, contextWindow: 128000, maxTokens: 4096 }],
				},
			},
		}),
		"utf8",
	);
	writeFileSync(
		join(agentDir, "settings.json"),
		JSON.stringify({ defaultProvider: "pm-mock", defaultModel: "mock-model" }),
		"utf8",
	);

	const { createPmRuntime } = await import("../src/agent/session.js");
	const runtime = await createPmRuntime({
		cwd: dir,
		sessionManager: (await import("@earendil-works/pi-coding-agent")).SessionManager.inMemory(),
	});

	// patch 0001（修订）：baseToolsOverride = 工作区文件工具集——
	// read/edit/write/grep/find/ls 构造（写论文能力）；bash/powershell 零构造。
	// _baseToolDefinitions 是 AgentSession 私有字段——fork 内契约测试允许访问。
	const registry = runtime.session._baseToolDefinitions;
	assert.ok(registry instanceof Map, "AgentSession 应存在 _baseToolDefinitions（上游契约）");
	const names = [...registry.keys()];
	assert.deepEqual(
		names.sort(),
		["edit", "find", "grep", "ls", "read", "write"],
		`应恰好 6 个工作区文件工具，实际: ${names.join(",")}`,
	);
	assert.ok(!names.includes("bash") && !names.includes("powershell"), "任意 shell 执行不得构造");

	// 面向 LLM 的工具注册表：PaperMind 工具 + 工作区文件工具；bash/powershell 永不在
	const agentTools = runtime.session.agent?.state?.tools ?? [];
	const agentToolNames = (Array.isArray(agentTools) ? agentTools : []).map((t) => t?.name || t?.definition?.name).filter(Boolean);
	if (agentToolNames.length) {
		assert.match(agentToolNames.join(","), /pm_list_jobs/);
		assert.doesNotMatch(agentToolNames.join(","), /\b(bash|powershell)\b/);
	}

	try {
		await runtime.dispose();
	} finally {
		pmServer.close();
		llmServer.close();
	}
}, 30000);
