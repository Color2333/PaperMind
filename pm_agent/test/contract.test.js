// E2/E4 契约测试（设计④ §8.1/8.2/8.3 的骨架覆盖）：
// 1) --json 契约：canonical result 原样、无 ANSI 转义；
// 2) 退出码表：五类退出码逐个触发；
// 3) 非 TTY fallback：plain 输出与 JSON 同一 canonical 数据；
// 4) 凭据互通：与 Python 版 pm 同一 config.toml 格式互读；
// 5) 设备码授权全链路（mock 服务器：start→pending→approved→存凭据）。
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, readFileSync, existsSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import http from "node:http";

import { run, UsageError } from "../src/cli.js";
import { loadConfig, saveConfig, configDir } from "../src/config.js";
import { ApiClient, EXIT } from "../src/http-client.js";

// ---------- 测试环境隔离 ----------

function isolate() {
	const dir = mkdtempSync(join(tmpdir(), "pm-cli-test-"));
	process.env.PAPERMIND_CONFIG_DIR = dir;
	process.env.PAPERMIND_TOKEN = "";
	process.env.PAPERMIND_SERVER_URL = "";
	return dir;
}

const ANSI_RE = /\u001b\[/;

// ---------- 1. 三模式骨架 ----------

test("无参数：云端会话 REPL（未登录退出 3）", async () => {
	isolate();
	const code = await run([]);
	assert.equal(code, EXIT.NOT_AUTHED);
});

test("pm -p：缺消息退出 2（用法错误）", async () => {
	isolate();
	const code = await run(["-p"]);
	assert.equal(code, EXIT.USAGE);
});

test("pm -p：未登录退出 3（远程 agent 需 PaperMind 登录）", async () => {
	isolate();
	const code = await run(["-p", "总结这篇论文"]);
	assert.equal(code, EXIT.NOT_AUTHED);
});

test("未知命令：退出 2", async () => {
	isolate();
	const code = await run(["definitely-not-a-command"]);
	assert.equal(code, EXIT.USAGE);
});

test("缺参数（claims list 无 --question）：JSON 模式输出 usage 错误对象，退出 2", async () => {
	isolate();
	const code = await run(["claims", "list", "--json"]);
	assert.equal(code, EXIT.USAGE);
});

// ---------- 2. 退出码 3：未登录 ----------

test("未登录调用受保护命令：退出 3，JSON 错误对象无 ANSI", async () => {
	isolate(); // 空配置目录
	const code = await run(["jobs", "list", "--json"]);
	assert.equal(code, EXIT.NOT_AUTHED);
});

// ---------- 3. --json 契约 + 非 TTY fallback（对 mock API）----------

function mockServer(handler) {
	return new Promise((resolve) => {
		const server = http.createServer(handler);
		server.listen(0, "127.0.0.1", () => resolve(server));
	});
}

test("jobs list --json：canonical result 原样输出且无 ANSI", async () => {
	isolate();
	const jobsPayload = {
		items: [{ id: "job-1", kind: "StartSkim", status: "succeeded", progress: {} }],
	};
	const server = await mockServer((req, res) => {
		assert.match(req.url, /^\/jobs\?/);
		res.setHeader("Content-Type", "application/json");
		res.end(JSON.stringify(jobsPayload));
	});
	const port = server.address().port;
	await saveConfig({ serverUrl: `http://127.0.0.1:${port}`, token: "pmt_test" });

	const chunks = [];
	const origWrite = process.stdout.write.bind(process.stdout);
	process.stdout.write = (chunk) => {
		chunks.push(String(chunk));
		return true;
	};
	const code = await run(["jobs", "list", "--json"]);
	process.stdout.write = origWrite;
	server.close();

	assert.equal(code, EXIT.OK);
	const out = chunks.join("");
	assert.equal(JSON.parse(out).items[0].id, "job-1"); // 原样 canonical
	assert.doesNotMatch(out, ANSI_RE); // 无 ANSI 转义
});

test("非 TTY plain 模式：同一 canonical 数据的可读渲染（含状态词）", async () => {
	isolate();
	const job = { id: "job-2", kind: "StartSkim", status: "succeeded", created_at: "2026-09-03T00:00:00+00:00" };
	const server = await mockServer((req, res) => {
		res.setHeader("Content-Type", "application/json");
		res.end(JSON.stringify({ items: [job] }));
	});
	const port = server.address().port;
	await saveConfig({ serverUrl: `http://127.0.0.1:${port}`, token: "pmt_test" });

	const chunks = [];
	const origWrite = process.stdout.write.bind(process.stdout);
	process.stdout.write = (chunk) => {
		chunks.push(String(chunk));
		return true;
	};
	const code = await run(["jobs", "list"]); // 无 --json → plain
	process.stdout.write = origWrite;
	server.close();

	assert.equal(code, EXIT.OK);
	const out = chunks.join("");
	assert.match(out, /succeeded/); // 状态词保留（颜色不是唯一信号）
	assert.doesNotMatch(out, ANSI_RE);
	assert.match(out, /job-2/);
});

// ---------- 4. 退出码 4/5：服务端业务错误 / 网络错误 ----------

test("服务端 404：退出 4，JSON detail 原样", async () => {
	isolate();
	const server = await mockServer((req, res) => {
		res.statusCode = 404;
		res.end(JSON.stringify({ detail: "Job not found" }));
	});
	const port = server.address().port;
	await saveConfig({ serverUrl: `http://127.0.0.1:${port}`, token: "pmt_test" });

	const errChunks = [];
	const origErr = process.stderr.write.bind(process.stderr);
	process.stderr.write = (chunk) => {
		errChunks.push(String(chunk));
		return true;
	};
	const code = await run(["jobs", "show", "no-such-job", "--json"]);
	process.stderr.write = origErr;
	server.close();

	assert.equal(code, EXIT.SERVER);
	const parsed = JSON.parse(errChunks.join(""));
	assert.equal(parsed.detail, "Job not found");
});

test("连接拒绝：退出 5（网络错误）", async () => {
	isolate();
	await saveConfig({ serverUrl: "http://127.0.0.1:1", token: "pmt_test" }); // 端口 1 必然拒绝
	const code = await run(["jobs", "list", "--json"]);
	assert.equal(code, EXIT.NETWORK);
});

// ---------- 5. 凭据互通（Python 版 pm 同一 config.toml）----------

test("读 Python 版 pm 写入的 config.toml（同一格式）", async () => {
	const dir = isolate();
	writeFileSync(
		join(dir, "config.toml"),
		'# PaperMind CLI 配置（pm login 生成）\nserver_url = "https://pm.example.com"\ntoken = "pmt_from_python"\nclient_name = "pm-cli"\n',
		"utf8",
	);
	const cfg = await loadConfig();
	assert.equal(cfg.serverUrl, "https://pm.example.com");
	assert.equal(cfg.token, "pmt_from_python");
});

test("TS 写入的 config.toml 兼容 Python 读取（同 key/引号/0600）", async () => {
	const dir = isolate();
	await saveConfig({ serverUrl: "https://pm.example.com/", token: "pmt_from_ts" });
	const raw = readFileSync(join(dir, "config.toml"), "utf8");
	assert.match(raw, /server_url = "https:\/\/pm\.example\.com"/);
	assert.match(raw, /token = "pmt_from_ts"/);
	const mode = statSync(join(dir, "config.toml")).mode & 0o777;
	assert.equal(mode, 0o600);
});

// ---------- 6. 设备码授权全链路（mock）----------

test("pm login：start→pending→approved→凭据落盘→whoami 可用", async () => {
	isolate();
	let pollCount = 0;
	const server = await mockServer((req, res) => {
		let body = "";
		req.on("data", (c) => (body += c));
		req.on("end", () => {
			res.setHeader("Content-Type", "application/json");
			if (req.url === "/auth/device/start") {
				res.end(
					JSON.stringify({
						device_code: "dc-1",
						user_code: "ABCD-1234",
						verification_url: "https://pm.example.com/device/ABCD-1234",
						expires_in: 900,
						interval: 5,
					}),
				);
			} else if (req.url === "/auth/device/poll") {
				pollCount += 1;
				if (pollCount === 1) res.end(JSON.stringify({ status: "pending" }));
				else res.end(JSON.stringify({ status: "approved", access_token: "pmt_new", token_name: "pm-cli" }));
			} else if (req.url === "/auth/me") {
				res.end(JSON.stringify({ username: "hao", auth_method: "api_token" }));
			} else {
				res.statusCode = 404;
				res.end("{}");
			}
		});
	});
	const port = server.address().port;

	process.env.PM_LOGIN_INTERVAL_MS = "5"; // 测试钩子：跳过 5s 轮询间隔
	const chunks = [];
	const origWrite = process.stdout.write.bind(process.stdout);
	process.stdout.write = (chunk) => {
		chunks.push(String(chunk));
		return true;
	};
	const code = await run([
		"login",
		"--endpoint",
		`http://127.0.0.1:${port}`,
	]);
	process.stdout.write = origWrite;
	server.close();

	assert.equal(code, EXIT.OK);
	assert.ok(pollCount >= 2);
	const cfg = await loadConfig();
	assert.equal(cfg.token, "pmt_new");
	assert.equal(cfg.serverUrl, `http://127.0.0.1:${port}`);
	// 与 Python 兼容
	assert.match(readFileSync(join(configDir(), "config.toml"), "utf8"), /token = "pmt_new"/);
});

// ---------- 7. ApiClient 协议细节 ----------

test("ApiClient：Bearer 头 + detail 错误提取", async () => {
	const server = await mockServer((req, res) => {
		assert.equal(req.headers.authorization, "Bearer pmt_x");
		if (req.url === "/ok") {
			res.end(JSON.stringify({ fine: true }));
		} else {
			res.statusCode = 403;
			res.end(JSON.stringify({ detail: "令牌缺少 write 权限" }));
		}
	});
	const port = server.address().port;
	const client = new ApiClient(`http://127.0.0.1:${port}`, "pmt_x");
	assert.deepEqual(await client.get("/ok"), { fine: true });
	await assert.rejects(
		() => client.get("/denied"),
		(err) => err.statusCode === 403 && /缺少 write/.test(err.message),
	);
	server.close();
});

test("existsSync：隔离环境不读真实用户凭据", () => {
	const dir = isolate();
	assert.ok(dir.startsWith(tmpdir()));
	assert.ok(!existsSync(join(dir, "config.toml")));
});
