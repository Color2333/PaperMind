// E6：六类领域卡片 renderer（Paper/Claim/Evidence/Diff/Job/Research Pack）。
// 规则（设计④ §7）：canonical tool result 是结构化数据，renderer 只负责显示；
// --json/oneshot text 路径完全绕过 renderer。
// 状态词永远保留（颜色不是唯一信号）。
const STATUS_COLOR = {
	// claim
	confirmed: "success",
	draft: "muted",
	pending_verification: "warning",
	pending: "warning",
	superseded: "dim",
	invalidated: "error",
	// job/task
	succeeded: "success",
	completed: "success",
	queued: "warning",
	leased: "warning",
	running: "warning",
	failed: "error",
	dead_letter: "error",
	cancelled: "dim",
	cancelled_by_user: "dim",
};

function statusColor(status) {
	return STATUS_COLOR[String(status || "").toLowerCase()] || "muted";
}

function line(theme, key, value, valueColor = "text") {
	return theme.fg("muted", `${key}: `) + theme.fg(valueColor, String(value));
}

function bordered(theme, title, rows) {
	const width = Math.max(title.length, ...rows.map((r) => stripAnsi(r).length)) + 2;
	const top = theme.fg("border", `┌${"─".repeat(width)}┐`);
	const bottom = theme.fg("border", `└${"─".repeat(width)}┘`);
	const head = theme.fg("border", "│ ") + theme.fg("toolTitle", theme.bold(title)) + theme.fg("border", " ".repeat(width - stripAnsi(title).length - 1) + "│");
	const body = rows.map((r) => theme.fg("border", "│ ") + r + " ".repeat(Math.max(0, width - stripAnsi(r).length - 1)) + theme.fg("border", "│"));
	return [top, head, theme.fg("border", "├" + "─".repeat(width) + "┤"), ...body, bottom].join("\n");
}

function stripAnsi(s) {
	return String(s).replace(/\u001b\[[0-9;]*m/g, "");
}

/** Paper Card：标题/作者/年份/来源/阅读状态/短 ID */
export function renderPaperCard(paper, theme) {
	const meta = paper.metadata_json || paper.metadata || {};
	const rows = [
		theme.fg("text", theme.bold(String(paper.title ?? "(无标题)"))),
		line(theme, "id", paper.id, "accent") + (paper.arxiv_id ? theme.fg("muted", ` · arXiv:${paper.arxiv_id}`) : ""),
		line(theme, "作者", Array.isArray(paper.authors) ? paper.authors.slice(0, 3).join(", ") : (paper.authors ?? "-")),
		line(theme, "日期", paper.publication_date ?? "-"),
		line(theme, "状态", paper.read_status ?? "-", statusColor(paper.read_status)),
	];
	if (paper.skim_score !== undefined && paper.skim_score !== null) {
		rows.push(line(theme, "skim", `${paper.skim_score}`, "accent"));
	}
	return bordered(theme, `📄 ${meta.title_zh || "Paper"}`, rows);
}

/** Claim Card：结论/状态/判断来源/置信/证据数 */
export function renderClaimCard(claim, theme) {
	const originLabel = { author: "作者原文", papermind: "PaperMind", user: "用户" }[claim.origin] || claim.origin;
	const rows = [
		theme.fg("text", theme.bold(String(claim.statement ?? claim.statement_zh ?? "(无结论)"))),
		line(theme, "状态", claim.status ?? "-", statusColor(claim.status)),
		line(theme, "来源", originLabel),
		line(theme, "置信", claim.certainty ?? "-"),
		line(theme, "id", claim.id, "accent"),
	];
	if (claim.evidence_count !== undefined) rows.push(line(theme, "证据", `${claim.evidence_count} 条`));
	return bordered(theme, "⚖ Claim", rows);
}

/** Evidence Card：论文/页码/section/短引用/方向 */
export function renderEvidenceCard(evidence, theme) {
	const rows = [
		line(theme, "论文", evidence.paper_title || evidence.paper_id || "-", "accent"),
		line(theme, "坐标", [evidence.locator?.page ? `p.${evidence.locator.page}` : null, evidence.locator?.section].filter(Boolean).join(" · ") || "-"),
		line(theme, "方向", evidence.stance ?? "-", statusColor(evidence.stance)),
	];
	if (evidence.quote) {
		rows.push(theme.fg("dim", `  "${String(evidence.quote).slice(0, 120)}"`));
	}
	return bordered(theme, "🔎 Evidence", rows);
}

/** Research Diff 行：added/confirmed/strengthened/weakened/conflict/superseded/invalidated */
export function renderDiffItems(items, theme) {
	if (!Array.isArray(items) || items.length === 0) {
		return theme.fg("muted", "(无 diff 记录)");
	}
	const ICON = { added: "+", confirmed: "=", strengthened: "↑", weakened: "↓", conflict: "!", superseded: "→", invalidated: "×", retraction: "×" };
	const out = [];
	for (const d of items) {
		const kind = d.diff_kind ?? d.kind ?? "?";
		const icon = ICON[kind] || "·";
		const color = kind === "added" || kind === "strengthened" ? "success" : kind === "weakened" || kind === "invalidated" || kind === "retraction" ? "error" : "warning";
		const statement = (d.statement ?? d.claim_statement ?? "").slice(0, 72);
		out.push(`${theme.fg(color, icon)} ${theme.fg(color, kind.padEnd(12))} ${theme.fg("text", statement)}`);
	}
	return out.join("\n");
}

/** Job View：阶段/进度/重试/错误（job graph 单行摘要或全卡） */
export function renderJobCard(graph, theme) {
	const rows = [
		line(theme, "kind", graph.kind ?? "-"),
		line(theme, "状态", graph.status ?? "-", statusColor(graph.status)),
		line(theme, "id", graph.id, "accent"),
	];
	const tasks = Array.isArray(graph.tasks) ? graph.tasks : [];
	if (tasks.length) {
		rows.push(theme.fg("muted", `tasks: ${tasks.length}`));
		for (const t of tasks.slice(0, 6)) {
			rows.push(
				`  ${theme.fg(statusColor(t.status), String(t.status).padEnd(10))} ${theme.fg("text", String(t.capability))} ` +
					theme.fg("dim", `attempt=${t.attempt_count ?? 0}${t.last_error ? ` err=${String(t.last_error).slice(0, 60)}` : ""}`),
			);
		}
		if (tasks.length > 6) rows.push(theme.fg("dim", `  … ${tasks.length - 6} more`));
	}
	return bordered(theme, "🛠 Job", rows);
}

/** Research Pack View：对象清单/校验值/provenance 摘要 */
export function renderResearchPack(pack, theme) {
	const rows = [
		line(theme, "question", pack.question?.title ?? pack.title ?? "-", "accent"),
		line(theme, "claims", String(pack.claims?.length ?? 0)),
		line(theme, "evidence", String(pack.evidence?.length ?? 0)),
	];
	if (pack.content_hash) rows.push(line(theme, "hash", String(pack.content_hash).slice(0, 16) + "…", "dim"));
	return bordered(theme, "📦 Research Pack", rows);
}
