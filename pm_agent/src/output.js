// 输出契约（设计④ §5）：--json 无 ANSI/无装饰/canonical result 原样；
// 非 TTY（pipe）退化为 plain text/Markdown；颜色不是唯一状态信号。
export const isTTY = process.stdout.isTTY;

export function emitJson(data) {
	process.stdout.write(JSON.stringify(data, null, 2) + "\n");
}

/** 简单 KV/plain 渲染（无 ANSI）；复杂结构回退 JSON.stringify */
export function emitPlain(data) {
	process.stdout.write(renderValue(data) + "\n");
}

function renderValue(value, indent = 0) {
	const pad = "  ".repeat(indent);
	if (value === null || value === undefined) return pad + "-";
	if (typeof value !== "object") return pad + String(value);
	if (Array.isArray(value)) {
		if (value.length === 0) return pad + "(空)";
		// 逐项展开：状态词/坐标在 plain 模式下不可折叠（设计④ §5 输出契约）
		return value.map((v, i) => {
			if (v && typeof v === "object" && !Array.isArray(v)) {
				const id = v.id ?? v.task_id ?? v.job_id ?? `[${i + 1}]`;
				const head = `${pad}- ${String(id)}`;
				const body = renderValue({ ...v, id: undefined, task_id: undefined, job_id: undefined }, indent + 1);
				return body.trim() ? `${head}\n${body}` : head;
			}
			return `${pad}- ${renderValue(v, 0).trim()}`;
		}).join("\n");
	}
	const lines = [];
	for (const [k, v] of Object.entries(value)) {
		if (v === null || v === undefined) continue;
		if (typeof v === "object" && !Array.isArray(v)) {
			lines.push(`${pad}${k}:`);
			lines.push(renderValue(v, indent + 1));
		} else if (Array.isArray(v)) {
			if (v.length === 0) continue;
			lines.push(`${pad}${k}:`);
			lines.push(renderValue(v, indent + 1));
		} else {
			lines.push(`${pad}${k}: ${v}`);
		}
	}
	return lines.filter((l) => l !== undefined).join("\n");
}

export function emit(data, { json = false } = {}) {
	if (json) emitJson(data);
	else emitPlain(data);
}

/** 用户可读的单行信息（plain 模式下 stdout；json 模式不打印） */
export function info(message, { json = false } = {}) {
	if (!json) process.stdout.write(message + "\n");
}

export function errorLine(message) {
	process.stderr.write(message + "\n");
}
