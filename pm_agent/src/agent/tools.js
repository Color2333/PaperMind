// PaperMind 受控工具集（E2c：product profile——Pi 内置 coding tools 全关，
// 只暴露本工具集；全部经 HTTPS application API，不导入服务端 Python/不直连 DB）。
// destructive 动作（cancel/submit 高预算）在 execute 内走 ctx.ui.confirm 双重把关；
// 服务端 scope 校验仍是最终授权，UI 确认不绕过。
import { Type } from "typebox";
import { Text } from "@earendil-works/pi-tui";

// renderCall 公共工厂：操作摘要行（工具名 + 关键参数）
function callLine(tool, summaryFn) {
	return (args, theme, _ctx) => {
		let text = theme.fg("toolTitle", theme.bold(tool + " "));
		text += theme.fg("accent", summaryFn(args));
		return new Text(text, 0, 0);
	};
}

// renderResult 公共工厂：进行中提示 + 完成卡片 + expanded 详情
function resultRenderer(partialMsg, cardFn, detailFn) {
	return (result, opts, theme, _ctx) => {
		if (opts.isPartial) return new Text(theme.fg("warning", partialMsg), 0, 0);
		const card = cardFn(result, theme);
		// expanded 分支：card 可能是 Text 组件（renderXxx 返回）——字符串拼接会把
		// 组件打成 [object Object]（第四轮 P2）。统一取其文本再拼详情。
		const cardText =
			typeof card === "string" ? card : (card?.render?.(120)?.join("\n") ?? "");
		if (opts.expanded && detailFn) {
			const detail = detailFn(result, theme);
			return new Text(`${cardText}\n${theme.fg("dim", detail)}`, 0, 0);
		}
		return card;
	};
}

function detailText(result, theme, keys) {
	const d = result?.details || result?.result || {};
	const lines = [];
	for (const k of keys) {
		if (d[k] !== undefined && d[k] !== null && d[k] !== "") {
			lines.push(theme.fg("dim", `  ${k}: `) + theme.fg("text", String(d[k]).slice(0, 120)));
		}
	}
	return lines.join("\n");
}

import { ApiClient } from "../http-client.js";
import { resolveServerUrl, resolveToken } from "../config.js";
import {
	renderClaimCard,
	renderDiffItems,
	renderEvidenceCard,
	renderJobCard,
	renderPaperCard,
	renderResearchPack,
} from "./renderers.js";

// ---------- 内部工具 ----------

const CONFIRM_POLL_INTERVAL_MS = 1500;
const CONFIRM_TIMEOUT_MS = 10 * 60 * 1000;

async function getClient() {
	// 解析优先级：env（Web 桥注入请求用户凭据）> config.toml（终端登录态）
	const [serverUrl, token] = await Promise.all([resolveServerUrl(), resolveToken()]);
	if (!serverUrl) {
		throw new Error("未配置 PaperMind 服务地址（PAPERMIND_SERVER_URL 或 pm login）");
	}
	// webchat 模式允许无 token——后端关闭认证的本地部署（请求方身份即服务自身）；
	// 终端模式仍要求显式登录
	if (!token && !process.env.PAPERMIND_WEBCHAT) {
		throw new Error("未登录 PaperMind（先运行 pm login --endpoint <url>）");
	}
	return new ApiClient(serverUrl, token);
}

/** Web 桥 headless 确认：破坏性操作建 pending-action 并轮询决定——
 * 前端确认卡批准后继续，拒绝/清理/超时/中断即取消（与 TUI ctx.ui.confirm 同语义）。
 * onUpdate 把确认请求透传给桥（→ SSE action_confirm → 前端卡片）。 */
async function confirmViaPendingAction(client, { tool, args, description, onUpdate, signal }) {
	const created = await client.post("/agent/pending-actions", {
		tool,
		args: args ?? {},
		description,
		conversation_id: process.env.PAPERMIND_CONVERSATION_ID || null,
	});
	const actionId = created?.id;
	if (!actionId) throw new Error("确认请求创建失败");
	onUpdate?.({ action_request: { id: actionId, description, tool, args: args ?? {} } });

	const deadline = Date.now() + CONFIRM_TIMEOUT_MS;
	while (Date.now() < deadline) {
		if (signal?.aborted) throw new Error("已中断");
		await new Promise((r) => setTimeout(r, CONFIRM_POLL_INTERVAL_MS));
		let state;
		try {
			state = await client.get(`/agent/pending-actions/${actionId}`);
		} catch (err) {
			if (err?.statusCode === 404) throw new Error("确认请求已过期（服务端清理）");
			continue; // 瞬态网络错误——重试
		}
		if (state.status === "approved") return;
		if (state.status === "rejected") throw new Error("用户取消了该操作");
	}
	throw new Error("确认超时（10 分钟未响应）");
}

async function confirmOrThrow(ctx, message, { tool, args, onUpdate, signal } = {}) {
	// webchat 优先：print 模式的 ctx.ui 存在但 confirm 自动 false——必须先走
	// pending-action 轮询（前端确认卡），再落 TUI 本地确认
	if (process.env.PAPERMIND_WEBCHAT && tool) {
		const client = await getClient();
		await confirmViaPendingAction(client, { tool, args, description: message, onUpdate, signal });
		return;
	}
	if (ctx?.ui?.confirm) {
		// TUI：本地确认 UI
		const yes = await ctx.ui.confirm("PaperMind", message);
		if (!yes) throw new Error("用户取消了该操作");
		return;
	}
	// 其他 headless（pm -p 脚本）：跳过，服务端 scope 兜底
}

function textResult(text, details = undefined) {
	return { content: [{ type: "text", text }], details };
}

function trunc(value, n = 400) {
	const s = typeof value === "string" ? value : JSON.stringify(value, null, 2);
	return s.length > n ? `${s.slice(0, n)}\n…（截断，共 ${s.length} 字符）` : s;
}

// ---------- 工具定义 ----------

export function papermindTools() {
	const tools = [];

	tools.push({
		name: "pm_search_papers",
		label: "search papers",
		description: "在用户的 PaperMind 库与 arXiv 等渠道搜索论文，返回候选列表（id/标题/作者/摘要片段）。用户提到找论文时先用这个。",
		promptSnippet: "- pm_search_papers(query, limit): 搜索论文库与 arXiv 渠道",
		parameters: Type.Object({
			query: Type.String({ description: "搜索关键词（英文效果最好）" }),
			limit: Type.Optional(Type.Number({ description: "每渠道最大条数，默认 10" })),
		}),
		async execute(_id, params) {
			const client = await getClient();
			const qs = new URLSearchParams({ query: params.query, max_results_per_channel: String(params.limit ?? 10) });
			const result = await client.post(`/papers/search-multi?${qs}`);
			const items = Array.isArray(result?.papers) ? result.papers : Array.isArray(result?.items) ? result.items : [];
			const lines = items.slice(0, 12).map((p) => `- [${p.id}] ${p.title}${p.arxiv_id ? ` (arXiv:${p.arxiv_id})` : ""}`);
			return textResult(lines.length ? lines.join("\n") : "没有匹配结果", result);
		},
		renderCall: callLine("search", (args) => args.query || ""),
		renderResult: resultRenderer(
			"搜索中…",
			(result, theme) => {
				const first = result?.details?.papers?.[0];
				return new Text(first ? renderPaperCard(first, theme) : theme.fg("muted", "搜索完成"), 0, 0);
			},
			(result, theme) => detailText(result, theme, ["total", "query", "channels"]),
		),
	});

	tools.push({
		name: "pm_get_paper",
		label: "get paper",
		description: "查看单篇论文详情：摘要、阅读状态、skim/deep-dive 摘要、元数据。",
		parameters: Type.Object({ paper_id: Type.String({ description: "论文 id" }) }),
		async execute(_id, params) {
			const client = await getClient();
			const paper = await client.get(`/papers/${params.paper_id}`);
			return textResult(trunc(paper, 3000), paper);
		},
		renderCall: callLine("paper", (args) => String(args.paper_id || "").slice(0, 16)),
		renderResult: resultRenderer(
			"读取中…",
			(result, theme) => new Text(result?.details ? renderPaperCard(result.details, theme) : theme.fg("muted", "已读取"), 0, 0),
			(result, theme) => detailText(result, theme, ["title", "read_status", "arxiv_id"]),
		),
	});

	tools.push({
		name: "pm_list_claims",
		label: "list claims",
		description: "列出某研究问题下的 Claim（含状态/来源/置信）。引用结论前必须先看证据状态。",
		parameters: Type.Object({
			question_id: Type.String({ description: "研究问题 id" }),
			statuses: Type.Optional(Type.Array(Type.String(), { description: "按状态过滤（draft/pending/confirmed…）" })),
		}),
		async execute(_id, params) {
			const client = await getClient();
			const qs = (params.statuses || []).map((s) => `status=${encodeURIComponent(s)}`).join("&");
			const result = await client.get(`/research/questions/${params.question_id}/claims${qs ? `?${qs}` : ""}`);
			const items = Array.isArray(result?.items) ? result.items : Array.isArray(result) ? result : [];
			const lines = items
				.map((c) => `- [${c.status}] (${c.origin}) ${String(c.statement || c.statement_zh || "").slice(0, 100)} [${c.id}]`)
				.join("\n");
			return textResult(lines || "（无 claim）", result);
		},
		renderCall: callLine("claims", (args) => `question=${String(args.question_id || "").slice(0, 16)}`),
		renderResult: resultRenderer(
			"加载 claims…",
			(result, theme) => {
				const items = result?.details?.items ?? [];
				return new Text(items.length ? renderClaimCard(items[0], theme) : theme.fg("muted", "无 claim"), 0, 0);
			},
			(result, theme) => detailText(result, theme, ["total", "question_id"]),
		),
	});

	tools.push({
		name: "pm_get_claim_evidence",
		label: "claim evidence",
		description: "查看单条 Claim 的全部证据（论文/页码/section/原文引用/支持方向）。引用一条结论前必须核对其证据坐标。",
		parameters: Type.Object({ claim_id: Type.String({ description: "claim id" }) }),
		async execute(_id, params) {
			const client = await getClient();
			const result = await client.get(`/research/claims/${params.claim_id}/evidence`);
			return textResult(trunc(result, 2500), result);
		},
		renderCall: callLine("evidence", (args) => String(args.claim_id || "").slice(0, 16)),
		renderResult: resultRenderer(
			"加载证据…",
			(result, theme) => {
				const ev = result?.details?.evidence?.[0] ?? result?.details?.items?.[0];
				return new Text(ev ? renderEvidenceCard(ev, theme) : theme.fg("muted", "无证据"), 0, 0);
			},
			(result, theme) => detailText(result, theme, ["claim_id", "total"]),
		),
	});

	tools.push({
		name: "pm_diff_research_state",
		label: "research diff",
		description: "查看某研究问题的状态变更时间线（新增/加强/削弱/冲突/取代/失效 + 原因）。",
		parameters: Type.Object({ question_id: Type.String({ description: "研究问题 id" }) }),
		async execute(_id, params) {
			const client = await getClient();
			const result = await client.get(`/research/questions/${params.question_id}/diff`);
			return textResult(trunc(result, 2500), result);
		},
		renderCall: callLine("diff", (args) => `question=${String(args.question_id || "").slice(0, 16)}`),
		renderResult: resultRenderer(
			"加载 diff…",
			(result, theme) => new Text(renderDiffItems(result?.details?.items ?? [], theme), 0, 0),
			(result, theme) => detailText(result, theme, ["question_id", "total"]),
		),
	});

	tools.push({
		name: "pm_export_research_pack",
		label: "export research pack",
		description: "导出某研究问题的 Research Pack（claims+evidence+provenance+校验值）。返回摘要；完整文件用确定性命令 pm export。",
		parameters: Type.Object({ question_id: Type.String({ description: "研究问题 id" }) }),
		async execute(_id, params) {
			const client = await getClient();
			const result = await client.get(`/research/questions/${params.question_id}/export?format=research-pack`);
			const summary = {
				question: result?.question?.title ?? params.question_id,
				claims: result?.claims?.length ?? 0,
				evidence: result?.evidence?.length ?? 0,
				content_hash: result?.content_hash,
			};
			return textResult(JSON.stringify(summary, null, 2), result);
		},
		renderCall: callLine("export", (args) => String(args.question_id || "").slice(0, 16)),
		renderResult: resultRenderer(
			"导出中…",
			(result, theme) => new Text(result?.details ? renderResearchPack(result.details, theme) : theme.fg("muted", "已导出"), 0, 0),
			(result, theme) => detailText(result, theme, ["content_hash", "claims", "evidence"]),
		),
	});

	tools.push({
		name: "pm_submit_job",
		label: "submit job",
		description:
			"向 PaperMind 提交 durable 处理任务（如 skim/deep-read 一篇论文）。返回 job_id 与 task_id；进度用 pm_get_job 查询。已知 capability：skim_paper（需 paper_id）、deep_read_paper（需 paper_id）、embed_paper（需 paper_id）。",
		parameters: Type.Object({
			capability: Type.String({ description: "能力名（skim_paper / deep_read_paper / embed_paper）" }),
			paper_id: Type.String({ description: "论文 id" }),
		}),
		async execute(_id, params, signal, onUpdate, ctx) {
			await confirmOrThrow(ctx, `提交 ${params.capability} 任务处理论文 ${params.paper_id}？`, {
				tool: "pm_submit_job",
				args: params,
				onUpdate,
				signal,
			});
			const client = await getClient();
			const result = await client.post("/jobs/durable", {
				kind: `Agent_${params.capability}`,
				capability: params.capability,
				title: `AI 提交：${params.capability}`,
				input_ref: { paper_id: params.paper_id },
				created_by: "terminal",
			});
			return textResult(
				`已提交：job=${result.job_id} task=${result.task_id}（状态 ${result.status}）。用 pm_get_job 查进度。`,
				result,
			);
		},
		renderCall: callLine("submit", (args) => `${args.capability} ${String(args.paper_id || "").slice(0, 16)}`),
		renderResult: resultRenderer(
			"提交中…",
			(result, theme) => new Text(
				result?.details ? renderJobCard({ id: result.details.job_id, status: result.details.status, kind: "submitted" }, theme) : theme.fg("muted", "已提交"),
				0,
				0,
			),
			(result, theme) => detailText(result, theme, ["job_id", "task_id", "status"]),
		),
	});

	tools.push({
		name: "pm_get_job",
		label: "get job",
		description: "查询 durable Job 的执行图（tasks/attempts/进度/错误）。",
		parameters: Type.Object({ job_id: Type.String({ description: "job id" }) }),
		async execute(_id, params) {
			const client = await getClient();
			const graph = await client.get(`/jobs/${params.job_id}`);
			const tasks = graph.tasks || [];
			const lines = tasks.map((t) => `- [${t.status}] ${t.capability} (attempt=${t.attempt_count})`);
			return textResult(`job ${graph.id} [${graph.status}]\n${lines.join("\n") || "(无 task)"}`, graph);
		},
		renderCall: callLine("job", (args) => String(args.job_id || "").slice(0, 16)),
		renderResult: resultRenderer(
			"查询任务…",
			(result, theme) => new Text(result?.details ? renderJobCard(result.details, theme) : theme.fg("muted", "已读取"), 0, 0),
			(result, theme) => detailText(result, theme, ["status", "attempt_count", "last_error"]),
		),
	});

	tools.push({
		name: "pm_list_jobs",
		label: "list jobs",
		description: "列出最近的 durable Job（状态/类型/时间）。",
		parameters: Type.Object({
			status: Type.Optional(Type.String({ description: "按状态过滤（queued/running/succeeded/failed…）" })),
			limit: Type.Optional(Type.Number({ description: "默认 20" })),
		}),
		async execute(_id, params) {
			const client = await getClient();
			const qs = new URLSearchParams({ limit: String(params.limit ?? 20) });
			if (params.status) qs.set("status", params.status);
			const result = await client.get(`/jobs?${qs}`);
			const items = result?.items ?? [];
			const lines = items.map((j) => `- [${j.status}] ${j.kind} ${j.id}`);
			return textResult(lines.join("\n") || "(无 job)", result);
		},
	});

	tools.push({
		name: "pm_cancel_job",
		label: "cancel job",
		description: "取消一个 Job：未领取的直接取消，运行中的在安全点协作退出。",
		parameters: Type.Object({ job_id: Type.String({ description: "job id" }) }),
		async execute(_id, params, signal, onUpdate, ctx) {
			await confirmOrThrow(ctx, `取消 Job ${params.job_id}？`, {
				tool: "pm_cancel_job",
				args: params,
				onUpdate,
				signal,
			});
			const client = await getClient();
			const result = await client.post(`/jobs/${params.job_id}/cancel`);
			return textResult(`已请求取消：${JSON.stringify(result)}`, result);
		},
	});

	return tools;
}
