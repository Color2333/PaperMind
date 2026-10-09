// pm gateway —— Pi LLM 网关（OpenAI 兼容 HTTP 面，底层 pi-ai / ModelRuntime）。
//
// 定位（设计④收敛）：LLM 网关唯一化——Agent 聊天（pm -p --json）与 Python
// 管线（skim/deep/claims）共用同一 Pi 网关，Python 不再自建 provider 协议栈。
// 模型凭据单一事实源仍是 DB（前端 Settings）→ 桥物化为 models.json → 本网关读。
//
// 协议：
//   POST /v1/chat/completions  {model?: "skim"|"deep"|<modelId>, messages, stream?}
//   GET  /healthz
// 鉴权：Bearer === PAPERMIND_GATEWAY_TOKEN（内网管道）。
// 模型映射：models.json 中 provider 的 models 数组顺序 = [skim, deep]（物化约定）；
// 请求 model="skim"/"deep" 按序取，其他值按真实 modelId 解析，缺省用 defaultModel。
import { createServer } from "node:http";
import { join } from "node:path";

const AGENT_DIR = process.env.PAPERMIND_AGENT_DIR;
const PORT = Number(process.env.PAPERMIND_GATEWAY_PORT || 8765);
const TOKEN = process.env.PAPERGATEWAY_TOKEN || process.env.PAPERMIND_GATEWAY_TOKEN || "";

if (!AGENT_DIR) {
	process.stderr.write("pm gateway: PAPERMIND_AGENT_DIR is required\n");
	process.exit(2);
}

const { streamSimple } = await import("@earendil-works/pi-ai/compat");
const { readFile, stat } = await import("node:fs/promises");

// 模型映射（物化约定）：models.json 中 provider 的 models 数组顺序 = [skim, deep]。
// 直接从 models.json 构造 pi-ai Model——不经 ModelRuntime snapshot（自定义
// provider 需 availability 刷新才入快照，网关场景不可控）。
// 配置按请求读（mtime 缓存）：桥在 DB 配置变化时重写文件即可热生效——
// 启动时读一次的旧实现会在"网关先于物化启动"时永久 502（真机实证）。
let configCache = { mtimeMs: -1, cfg: null };

async function loadConfig() {
	try {
		const st = await stat(join(AGENT_DIR, "models.json"));
		if (configCache.mtimeMs === st.mtimeMs && configCache.cfg) return configCache.cfg;
	} catch {}
	try {
		const settings = JSON.parse(await readFile(join(AGENT_DIR, "settings.json"), "utf8"));
		let defaultProvider = settings.defaultProvider || "";
		let defaultModel = settings.defaultModel || "";
		const models = JSON.parse(await readFile(join(AGENT_DIR, "models.json"), "utf8"));
		const providerCfg = models.providers?.[defaultProvider] || Object.values(models.providers || {})[0];
		const modelIds = (providerCfg?.models || []).map((m) => m.id).filter(Boolean);
		if (!defaultProvider) defaultProvider = Object.keys(models.providers || {})[0] || "";
		if (!defaultModel) defaultModel = modelIds[0] || "";
		configCache = {
			mtimeMs: (await stat(join(AGENT_DIR, "models.json"))).mtimeMs,
			cfg: { defaultProvider, defaultModel, providerCfg, modelIds },
		};
	} catch {}
	return configCache.cfg;
}

function resolveModelId(cfg, requested) {
	const { modelIds, defaultModel } = cfg;
	if (requested === "skim") return modelIds[0] || defaultModel;
	if (requested === "deep") return modelIds[1] || modelIds[0] || defaultModel;
	if (requested === "vision") return modelIds[2] || modelIds[1] || modelIds[0] || defaultModel;
	if (requested && modelIds.includes(requested)) return requested;
	return defaultModel;
}

function buildModel(cfg, modelId) {
	const entry = (cfg.providerCfg?.models || []).find((m) => m.id === modelId) || {};
	return {
		id: modelId,
		name: entry.name || modelId,
		api: entry.api || cfg.providerCfg?.api || "openai-completions",
		baseUrl: entry.baseUrl || cfg.providerCfg?.baseUrl,
		provider: cfg.defaultProvider,
		reasoning: false,
		input: ["text"],
		// pi-ai 1.1.0 calculateCost 无兜底地读 model.cost.tiers——自定义 provider
		// 模型不在其定价目录里，必须带零成本形状（网关不定价，成本由 Python 侧
		// prompt_traces 按自身费率记录）
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, tiers: [] },
	};
}

function toAgentMessages(openaiMessages) {
	const out = [];
	for (const m of openaiMessages || []) {
		const role = m.role === "assistant" ? "assistant" : "user";
		if (typeof m.content === "string") {
			if (!m.content) continue;
			out.push({ role, content: [{ type: "text", text: m.content }], timestamp: Date.now() });
			continue;
		}
		// 多模态 content（vision_analyze）：image_url(data URL) → pi-ai image 块
		const blocks = [];
		for (const part of m.content || []) {
			if (part?.type === "text" && part.text) {
				blocks.push({ type: "text", text: part.text });
			} else if (part?.type === "image_url" && part.image_url?.url?.startsWith("data:")) {
				const [meta, data] = part.image_url.url.split(",", 2);
				const mimeType = meta.slice(5).split(";")[0] || "image/png";
				blocks.push({ type: "image", mimeType, data });
			}
		}
		if (blocks.length) out.push({ role, content: blocks, timestamp: Date.now() });
	}
	return out;
}

async function complete(body) {
	const cfg = await loadConfig();
	if (!cfg || !cfg.providerCfg) throw new Error("models.json 未物化或为空");
	const model = buildModel(cfg, resolveModelId(cfg, body.model));
	const msgs = toAgentMessages(body.messages);
	const lastUser = [...msgs].reverse().find((m) => m.role === "user");
	const context = {
		systemPrompt: "",
		messages: lastUser ? [lastUser] : msgs.slice(-1),
	};
	const events = streamSimple(model, context, { apiKey: cfg.providerCfg.apiKey });
	let content = "";
	let usage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
	for await (const ev of events) {
		// compat.streamSimple 顶层事件：text_delta 携带增量；done 携带权威全文与
		// 真实 usage（OpenAI 形状换算）；error 携带上游失败
		if (ev.type === "text_delta") content += ev.delta || "";
		else if (ev.type === "done") {
			const texts = (ev.message?.content || [])
				.filter((c) => c.type === "text")
				.map((c) => c.text || "");
			if (texts.length) content = texts.join("");
			const u = ev.message?.usage || {};
			usage = {
				prompt_tokens: u.input || 0,
				completion_tokens: (u.output || 0) + (u.reasoning || 0),
				total_tokens: u.totalTokens || 0,
			};
		} else if (ev.type === "error") {
			const msg = ev.error?.errorMessage || ev.error?.message || "gateway upstream error";
			throw new Error(msg);
		}
	}
	return { content, usage };
}

function sse(res, payload) {
	res.writeHead(200, {
		"Content-Type": "text/event-stream",
		"Cache-Control": "no-cache",
		Connection: "keep-alive",
	});
	res.write(`data: ${JSON.stringify(payload)}\n\n`);
	res.write("data: [DONE]\n\n");
	res.end();
}

const server = createServer((req, res) => {
	if (req.method === "GET" && req.url === "/healthz") {
		res.writeHead(200, { "Content-Type": "application/json" });
		loadConfig()
			.then((cfg) => {
				res.end(JSON.stringify({ ok: true, provider: cfg?.defaultProvider || "" }));
			})
			.catch(() => {
				res.end(JSON.stringify({ ok: true, provider: "" }));
			});
		return;
	}
	if (TOKEN) {
		const auth = req.headers.authorization || "";
		if (auth !== `Bearer ${TOKEN}`) {
			res.writeHead(401, { "Content-Type": "application/json" });
			res.end(JSON.stringify({ detail: "invalid gateway token" }));
			return;
		}
	}
	if (req.method === "POST" && (req.url || "").endsWith("/chat/completions")) {
		let raw = "";
		req.on("data", (c) => (raw += c));
		req.on("end", async () => {
			const started = Date.now();
			let body = {};
			try {
				body = JSON.parse(raw || "{}");
			} catch {}
			try {
				const { content, usage } = await complete(body);
				const id = `chatcmpl-gw-${started}`;
				if (body.stream) {
					sse(res, {
						id, object: "chat.completion.chunk", created: Math.floor(started / 1000),
						model: body.model || "default",
						choices: [{ index: 0, delta: { role: "assistant", content }, finish_reason: "stop" }],
					});
				} else {
					res.writeHead(200, { "Content-Type": "application/json" });
					res.end(JSON.stringify({
						id, object: "chat.completion", created: Math.floor(started / 1000),
						model: body.model || "default",
						choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
						usage,
					}));
				}
			} catch (err) {
				res.writeHead(502, { "Content-Type": "application/json" });
				res.end(JSON.stringify({ detail: String(err?.message || err).slice(0, 300) }));
			}
		});
		return;
	}
	res.writeHead(404, { "Content-Type": "application/json" });
	res.end(JSON.stringify({ detail: "not found" }));
});

// 绑定地址可配：sidecar 容器形态必须 0.0.0.0（仅编排网内可达，端口不对外发布）；
// 本地直跑默认 127.0.0.1
const HOST = process.env.PAPERMIND_GATEWAY_HOST || "127.0.0.1";
	server.listen(PORT, HOST, () => {
	loadConfig().then((cfg) => {
		process.stdout.write(`${JSON.stringify({ event: "gateway_ready", port: PORT, provider: cfg?.defaultProvider || "" })}\n`);
	});
});

// 可测试入口：runGateway 启动 HTTP 服务并阻塞直到进程被终止
export async function runGateway() {
	await new Promise(() => {}); // server 事件循环由 createServer 驱动
	return 0;
}
