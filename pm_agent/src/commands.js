// E4 确定性命令面 v1（设计④ §5）——查询/任务/队列，全部薄 adapter 到 HTTPS API。
import { EXIT } from "./http-client.js";
import { classify, notAuthed } from "./auth.js";
import { emit, info } from "./output.js";

async function withClient(json, fn) {
	const { authedClient } = await import("./http-client.js");
	const client = await authedClient();
	if (!client) return notAuthed(json);
	try {
		return await fn(client);
	} catch (err) {
		return classify(err, json);
	}
}

// ---------- papers ----------

export async function papersSearch({ query, limit = 10, json = false }) {
	return withClient(json, async (client) => {
		const body = new URLSearchParams({ query, max_results_per_channel: String(limit) });
		const result = await client.post(`/papers/search-multi?${body}`);
		emit(result, { json });
		if (!json) {
			const items = collectResults(result);
			info(`共 ${items.length} 篇（--json 查看完整 canonical result）`);
		}
		return EXIT.OK;
	});
}

function collectResults(result) {
	if (Array.isArray(result)) return result;
	if (Array.isArray(result?.items)) return result.items;
	if (Array.isArray(result?.results)) return result.results.flatMap((r) => r.items || r.papers || []);
	return [];
}

export async function papersShow({ paperId, json = false }) {
	return withClient(json, async (client) => {
		const paper = await client.get(`/papers/${paperId}`);
		emit(paper, { json });
		if (!json) info(`\n（详情含 metadata/分析报告；Web 深链：/papers/${paperId}）`);
		return EXIT.OK;
	});
}

// ---------- research state ----------

export async function questionsShow({ questionId, json = false }) {
	return withClient(json, async (client) => {
		const q = await client.get(`/research/questions/${questionId}`);
		emit(q, { json });
		return EXIT.OK;
	});
}

export async function claimsList({ questionId, statuses = [], json = false }) {
	return withClient(json, async (client) => {
		const params = new URLSearchParams();
		for (const s of statuses) params.append("status", s);
		const qs = params.toString();
		const result = await client.get(`/research/questions/${questionId}/claims${qs ? `?${qs}` : ""}`);
		emit(result, { json });
		if (!json) info(`\n（--json 输出 canonical claims；状态词保持原文，颜色不作唯一信号）`);
		return EXIT.OK;
	});
}

export async function claimsShow({ claimId, json = false }) {
	return withClient(json, async (client) => {
		const result = await client.get(`/research/claims/${claimId}/evidence`);
		emit(result, { json });
		return EXIT.OK;
	});
}

export async function diffResearchState({ questionId, json = false }) {
	return withClient(json, async (client) => {
		const result = await client.get(`/research/questions/${questionId}/diff`);
		emit(result, { json });
		return EXIT.OK;
	});
}

export async function exportResearchObject({ questionId, format = "research-pack", json = false }) {
	return withClient(json, async (client) => {
		// export 的 canonical result：json=true 时原样输出 JSON；
		// markdown/research-pack 非 json 模式直接输出文本本身
		if (json && format !== "json") {
			const result = await client.get(`/research/questions/${questionId}/export?format=${format}`);
			emit(result, { json: true });
			return EXIT.OK;
		}
		const fmt = format === "json" ? "json" : format;
		const result = await client.get(`/research/questions/${questionId}/export?format=${fmt}`);
		if (format === "json") {
			emit(result, { json: true });
		} else if (typeof result === "string") {
			process.stdout.write(result + "\n");
		} else if (result?.markdown) {
			process.stdout.write(result.markdown + "\n");
		} else {
			emit(result, { json: false });
		}
		return EXIT.OK;
	});
}

// ---------- jobs / tasks / queue ----------

export async function jobsList({ status = null, limit = 20, json = false }) {
	return withClient(json, async (client) => {
		const params = new URLSearchParams({ limit: String(limit) });
		if (status) params.set("status", status);
		const result = await client.get(`/jobs?${params}`);
		emit(result, { json });
		if (!json) info(`\n（共 ${(result?.items || []).length} 个 Job）`);
		return EXIT.OK;
	});
}

export async function jobsShow({ jobId, json = false }) {
	return withClient(json, async (client) => {
		const graph = await client.get(`/jobs/${jobId}`);
		emit(graph, { json });
		return EXIT.OK;
	});
}

export async function jobsCancel({ jobId, json = false }) {
	return withClient(json, async (client) => {
		const result = await client.post(`/jobs/${jobId}/cancel`);
		emit(result, { json });
		if (!json) info(`已请求取消 Job ${jobId}（运行中任务在安全点退出）`);
		return EXIT.OK;
	});
}

export async function tasksRetry({ taskId, json = false }) {
	return withClient(json, async (client) => {
		const result = await client.post(`/tasks/${taskId}/retry`);
		emit(result, { json });
		if (!json) info(`Task ${taskId} 已重入队（${result?.status}）`);
		return EXIT.OK;
	});
}

export async function queueControl({ action, json = false }) {
	return withClient(json, async (client) => {
		const result = await client.post(`/queue/${action}`);
		emit(result, { json });
		if (!json) info(action === "pause" ? "队列已暂停（跨进程生效）" : "队列已恢复");
		return EXIT.OK;
	});
}
