// HTTP 客户端（唯一 PaperMind 连接方式：HTTPS application API）。
// Pi extension 与确定性 CLI 共用——不导入服务端 Python、不直连数据库（设计④ §3）。
import { loadConfig, resolveServerUrl, resolveToken } from "./config.js";

export const EXIT = {
	OK: 0,
	USAGE: 2,
	NOT_AUTHED: 3,
	SERVER: 4,
	NETWORK: 5,
};

export class ApiError extends Error {
	constructor(statusCode, message) {
		super(message);
		this.statusCode = statusCode;
	}
}

export class NetworkError extends Error {}

export class ApiClient {
	constructor(serverUrl, token = null, { timeoutMs = 30000, fetchImpl = globalThis.fetch } = {}) {
		this.baseUrl = serverUrl.replace(/\/+$/, "");
		this.token = token;
		this.timeoutMs = timeoutMs;
		this.fetchImpl = fetchImpl;
	}

	async request(method, path, body = null) {
		const headers = { "Content-Type": "application/json" };
		if (this.token) headers.Authorization = `Bearer ${this.token}`;
		let resp;
		try {
			resp = await this.fetchImpl(this.baseUrl + path, {
				method,
				headers,
				body: body === null ? undefined : JSON.stringify(body),
				signal: AbortSignal.timeout(this.timeoutMs),
			});
		} catch (err) {
			throw new NetworkError(`无法连接 ${this.baseUrl}（${err?.cause?.code || err.name || "network"}）`);
		}
		if (resp.status >= 400) {
			let detail = `HTTP ${resp.status}`;
			try {
				const parsed = await resp.json();
				if (parsed && typeof parsed === "object" && parsed.detail) detail = String(parsed.detail);
			} catch {
				/* 非 JSON 错误体，保留 HTTP 状态 */
			}
			throw new ApiError(resp.status, detail);
		}
		if (resp.status === 204) return {};
		const text = await resp.text();
		if (!text) return {};
		return JSON.parse(text);
	}

	get(path) {
		return this.request("GET", path);
	}
	post(path, body = {}) {
		return this.request("POST", path, body);
	}
	del(path) {
		return this.request("DELETE", path);
	}

	/**
	 * SSE 流式 POST（pm -p 远程 agent）：cb 依次收到每个完整事件块（原始文本，
	 * 以空行分隔）。非 2xx 走与 request 一致的错误映射。
	 */
	async postStream(path, body, onChunk) {
		const headers = { "Content-Type": "application/json", Accept: "text/event-stream" };
		if (this.token) headers.Authorization = `Bearer ${this.token}`;
		let resp;
		try {
			resp = await this.fetchImpl(this.baseUrl + path, {
				method: "POST",
				headers,
				body: JSON.stringify(body),
			});
		} catch (err) {
			throw new NetworkError(`无法连接 ${this.baseUrl}（${err?.cause?.code || err.name || "network"}）`);
		}
		if (resp.status >= 400) {
			let detail = `HTTP ${resp.status}`;
			try {
				const parsed = await resp.json();
				if (parsed && typeof parsed === "object" && parsed.detail) detail = String(parsed.detail);
			} catch {
				/* 非 JSON 错误体，保留 HTTP 状态 */
			}
			throw new ApiError(resp.status, detail);
		}
		const decoder = new TextDecoder();
		let buf = "";
		for await (const part of resp.body) {
			buf += decoder.decode(part, { stream: true });
			let idx;
			while ((idx = buf.indexOf("\n\n")) !== -1) {
				const chunk = buf.slice(0, idx);
				buf = buf.slice(idx + 2);
				onChunk(chunk);
			}
		}
		if (buf.trim()) onChunk(buf); // 流尾无空行结尾的最后一块
	}

	// ---- 便捷封装（与 Python ApiClient 同形）----
	health() {
		return this.get("/health");
	}
	me() {
		return this.get("/auth/me");
	}
	deviceStart(clientName) {
		return this.post("/auth/device/start", { client_name: clientName });
	}
	devicePoll(deviceCode) {
		return this.post("/auth/device/poll", { device_code: deviceCode });
	}
}

/** 从环境/配置解析出已鉴权客户端；未登录返回 null（调用方映射退出码 3） */
export async function authedClient({ requireToken = true, endpoint = null } = {}) {
	const serverUrl = await resolveServerUrl(endpoint);
	if (!serverUrl) return null;
	const token = await resolveToken();
	if (requireToken && !token) return null;
	return new ApiClient(serverUrl, token);
}

/** 已保存的配置（含 serverUrl，即使 token 缺失——doctor/login 用） */
export async function savedConfig() {
	return loadConfig();
}
