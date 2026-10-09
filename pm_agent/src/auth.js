// E3：远程登录（设备码授权）+ whoami/logout/doctor。
// 协议：PaperMind 自己签发 device code（/auth/device/start）→ 浏览器完成上游登录
// → CLI 轮询 /auth/device/poll 只拿 PaperMind token——上游 provider 凭据不下发。
import { open } from "node:fs/promises";
import { ApiError, EXIT, NetworkError } from "./http-client.js";
import { clearConfig, loadConfig, saveConfig } from "./config.js";
import { emit, emitJson, errorLine, info } from "./output.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function cmdLogin({ endpoint, clientName = "pm-cli", json = false, openBrowser = false, poll = null }) {
	if (!endpoint) {
		errorLine("用法: pm login --endpoint <server-url>");
		return EXIT.USAGE;
	}
	const { ApiClient } = await import("./http-client.js");
	const client = new ApiClient(endpoint);
	let start;
	try {
		start = await client.deviceStart(clientName);
	} catch (err) {
		return networkOrServerExit(err, json);
	}
	info(`1. 在浏览器打开：${start.verification_url}`, { json });
	info(`2. 输入用户码：${start.user_code}`, { json });
	if (openBrowser) {
		try {
			const { default: webbrowser } = await import("node:child_process");
			const platform = process.platform;
			const cmd = platform === "darwin" ? "open" : platform === "win32" ? "cmd" : "xdg-open";
			const args = platform === "win32" ? ["/c", "start", "", start.verification_url] : [start.verification_url];
			webbrowser.spawn(cmd, args, { stdio: "ignore", detached: true }).unref();
		} catch {
			/* 打不开浏览器不阻塞——手输 URL */
		}
	}
	info("等待授权…", { json });

	// 服务端下发轮询间隔（秒）；测试/离线场景可用 PM_LOGIN_INTERVAL_MS（毫秒）覆盖
	const intervalMs = process.env.PM_LOGIN_INTERVAL_MS
		? Math.max(1, Number(process.env.PM_LOGIN_INTERVAL_MS))
		: Math.max(1, Number(start.interval || 5)) * 1000;
	const deadlineMs = Math.max(30, Number(start.expires_in || 900)) * 1000;
	const pollFn =
		poll ||
		(async (deviceCode) => {
			await sleep(intervalMs);
			return client.devicePoll(deviceCode);
		});

	const startedAt = Date.now();
	for (;;) {
		if (Date.now() - startedAt > deadlineMs) {
			errorLine(json ? JSON.stringify({ error: "授权超时" }) : "授权超时（device code 已过期，请重试）");
			return EXIT.SERVER;
		}
		let pollResult;
		try {
			pollResult = await pollFn(start.device_code);
		} catch (err) {
			return networkOrServerExit(err, json);
		}
		const status = pollResult?.status;
		if (status === "approved" && pollResult.access_token) {
			await saveConfig({ serverUrl: endpoint, token: pollResult.access_token, clientName });
			const me = await tryMe(endpoint, pollResult.access_token);
			if (json) {
				emitJson({ status: "logged_in", endpoint, user: me });
			} else {
				info(`已登录 ${endpoint}${me?.username ? `（${me.username}）` : ""}`);
			}
			return EXIT.OK;
		}
		if (status === "denied") {
			errorLine(json ? JSON.stringify({ error: "授权被拒绝" }) : "授权被拒绝");
			return EXIT.SERVER;
		}
		if (status === "expired") {
			errorLine(json ? JSON.stringify({ error: "授权超时" }) : "授权超时（device code 已过期，请重试）");
			return EXIT.SERVER;
		}
		// pending / delivered → 继续轮询
	}
}

async function tryMe(endpoint, token) {
	try {
		const { ApiClient } = await import("./http-client.js");
		return await new ApiClient(endpoint, token).me();
	} catch {
		return null;
	}
}

export async function cmdLogout({ json = false } = {}) {
	// 有 token 时先撤销服务端令牌（best-effort），再清本地
	const cfg = await loadConfig();
	if (cfg) {
		try {
			const { ApiClient } = await import("./http-client.js");
			const client = new ApiClient(cfg.serverUrl, cfg.token);
			const tokens = await client.get("/auth/tokens");
			const self = (tokens || []).find((t) => t.name && t.name.startsWith(cfg.clientName));
			if (self?.id) await client.del(`/auth/tokens/${self.id}`);
		} catch {
			/* 撤销失败不阻塞本地清除 */
		}
	}
	const removed = await clearConfig();
	emit({ logged_out: true, had_config: Boolean(cfg), removed }, { json });
	if (!json) info(removed ? "已退出登录（本地凭据已清除）" : "本就未登录");
	return EXIT.OK;
}

export async function cmdWhoami({ json = false } = {}) {
	const { authedClient } = await import("./http-client.js");
	const client = await authedClient();
	if (!client) return notAuthed(json);
	try {
		const me = await client.me();
		emit(me, { json });
		return EXIT.OK;
	} catch (err) {
		return classify(err, json);
	}
}

export async function cmdDoctor({ json = false } = {}) {
	const { authedClient } = await import("./http-client.js");
	const cfg = await loadConfig();
	const client = await authedClient({ requireToken: false });
	const result = {
		config_file: cfg ? "ok" : "missing",
		server_url: cfg?.serverUrl || null,
		token: cfg ? "present" : "missing",
	};
	try {
		result.reachable = Boolean(await client.health());
	} catch {
		result.reachable = false;
	}
	if (result.reachable && cfg) {
		try {
			const { ApiClient } = await import("./http-client.js");
			await new ApiClient(cfg.serverUrl, cfg.token).me();
			result.auth = "ok";
		} catch (err) {
			result.auth = err instanceof ApiError ? `invalid (${err.statusCode})` : "unreachable";
		}
	} else {
		result.auth = cfg ? "unverified" : "not_logged_in";
	}
	emit(result, { json });
	if (!json) {
		const ok = result.reachable && result.auth === "ok";
		info(ok ? "体检通过：配置/连通/鉴权均正常" : "体检未通过（见上）");
	}
	return ok(result) ? EXIT.OK : EXIT.SERVER;
}

function ok(_result) {
	return true; // doctor 诊断性命令：除非环境损坏，返回 0（细节在输出里）
}

export function notAuthed(json) {
	errorLine(json ? JSON.stringify({ error: "not_logged_in" }) : "未登录：先执行 pm login --endpoint <server-url>");
	return EXIT.NOT_AUTHED;
}

export function networkOrServerExit(err, json) {
	if (err instanceof NetworkError) {
		errorLine(json ? JSON.stringify({ error: "network_error", detail: err.message }) : err.message);
		return EXIT.NETWORK;
	}
	if (err instanceof ApiError) {
		errorLine(json ? JSON.stringify({ error: "server_error", status: err.statusCode, detail: err.message }) : `服务端错误（${err.statusCode}）：${err.message}`);
		return err.statusCode === 401 || err.statusCode === 403 ? EXIT.NOT_AUTHED : EXIT.SERVER;
	}
	errorLine(json ? JSON.stringify({ error: "unexpected", detail: String(err) }) : String(err));
	return EXIT.SERVER;
}

export function classify(err, json) {
	return networkOrServerExit(err, json);
}
