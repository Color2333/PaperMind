// pm -p 的远程 agent 接入（方案 A，设计④：CLI 唯一连接方式是公网 HTTPS）。
//
// CLI → 生产 /agent/chat SSE：agent loop/工具/LLM（Pi 网关）全在服务端，
// CLI 零 LLM 依赖——只做 SSE 解析 + 终端渲染 + 确认卡应答。
// 会话续接：conversation_id 存 configDir/agent-session.json（-c 覆盖，--new 清）。

import { createInterface } from "node:readline/promises";
import { stdin, stdout, stderr } from "node:process";
import { configDir } from "../config.js";
import { join } from "node:path";
import { readFile, writeFile, mkdir } from "node:fs/promises";

const DIM = "\x1b[2m";
const RESET = "\x1b[0m";
const RED = "\x1b[31m";
const BOLD = "\x1b[1m";

/** 解析单个 SSE 事件块（"event: X\n data: {...}"）→ {event, data}；无效返回 null */
export function parseSseChunk(chunk) {
	let event = "message";
	const dataLines = [];
	for (const line of chunk.split("\n")) {
		if (line.startsWith("event:")) event = line.slice(6).trim();
		else if (line.startsWith("data:")) dataLines.push(line.slice(5));
	}
	if (!dataLines.length) return null;
	try {
		return { event, data: JSON.parse(dataLines.join("\n")) };
	} catch {
		return null;
	}
}

/** 会话续接：conversation_id 的本地持久化（configDir/agent-session.json） */
export async function loadAgentConversationId() {
	try {
		const raw = await readFile(join(configDir(), "agent-session.json"), "utf8");
		return JSON.parse(raw).conversationId || null;
	} catch {
		return null;
	}
}

export async function saveAgentConversationId(conversationId) {
	const dir = configDir();
	await mkdir(dir, { recursive: true });
	await writeFile(
		join(dir, "agent-session.json"),
		JSON.stringify({ conversationId }, null, 2),
		"utf8",
	);
}

async function answerConfirm(client, data, interactive) {
	const desc = data.description || data.tool || "";
	stdout.write(`\n${BOLD}⚠ 确认请求（${data.tool || "tool"}）${RESET}: ${desc}\n`);
	if (!interactive) {
		stdout.write(`${DIM}非交互环境，自动拒绝（可在 TTY 下重跑以批准）${RESET}\n`);
		await client.post(`/agent/reject/${data.id}`).catch(() => {});
		return;
	}
	const rl = createInterface({ input: stdin, output: stdout });
	const answer = (await rl.question("批准执行? [y/N] ")).trim().toLowerCase();
	rl.close();
	const ok = answer === "y" || answer === "yes";
	stdout.write(`${DIM}${ok ? "✓ 已批准" : "✗ 已拒绝"}${RESET}\n`);
	await client.post(`/agent/${ok ? "confirm" : "reject"}/${data.id}`).catch(() => {});
}

/**
 * 远程 agent 对话核心：POST /agent/chat SSE → 事件分派（渲染无关）。
 * handlers: {onConversationInit, onTextDelta, onToolStart, onToolResult,
 *            onConfirm(async), onError, onDone}
 * onConfirm 缺省时自动拒绝（安全默认）。返回 {conversationId, ok}。
 */
export async function chatStream({ client, message, conversationId = null, handlers = {} }) {
	let convId = conversationId;
	let errored = false;
	await client.postStream(
		"/agent/chat",
		{
			messages: [{ role: "user", content: message }],
			...(conversationId ? { conversation_id: conversationId } : {}),
		},
		(chunk) => {
			const parsed = parseSseChunk(chunk);
			if (!parsed) return;
			const { event, data } = parsed;
			switch (event) {
				case "conversation_init":
					if (data.conversation_id) convId = data.conversation_id;
					handlers.onConversationInit?.(data.conversation_id);
					break;
				case "text_delta":
					handlers.onTextDelta?.(data.content || "");
					break;
				case "tool_start":
					handlers.onToolStart?.(data.tool || "tool", data);
					break;
				case "tool_result":
					handlers.onToolResult?.(data.tool || "tool", data);
					break;
				case "action_confirm":
					if (handlers.onConfirm) void handlers.onConfirm(data);
					else
						void client
							.post(`/agent/reject/${data.id}`)
							.catch(() => {});
					break;
				case "error":
					errored = true;
					handlers.onError?.(data.message || "未知");
					break;
				case "done":
					handlers.onDone?.();
					break;
				default:
					break;
			}
		},
	);
	return { conversationId: convId, ok: !errored };
}

/**
 * 远程 agent 一次性对话（行式渲染，pm -p 用）：chatStream + stdout 处理器。
 */
export async function runRemotePrompt({
	client,
	message,
	conversationId = null,
	interactive = Boolean(stdin.isTTY),
}) {
	let answerConfirm = null;
	const { conversationId: convId, ok } = await chatStream({
		client,
		message,
		conversationId,
		handlers: {
			onConversationInit: () => {},
			onTextDelta: (delta) => stdout.write(delta),
			onToolStart: (tool) => stdout.write(`\n${DIM}⚙ ${tool} …${RESET}\n`),
			onToolResult: (tool) => stdout.write(`${DIM}✓ ${tool} 完成${RESET}\n`),
			onConfirm: (data) => {
				answerConfirm = answerConfirmOrNote(client, data, interactive);
			},
			onError: (msg) => stderr.write(`\n${RED}错误: ${msg}${RESET}\n`),
			onDone: () => stdout.write("\n"),
		},
	});
	await answerConfirm;
	if (convId) await saveAgentConversationId(convId).catch(() => {});
	return { conversationId: convId, ok };
}

async function answerConfirmOrNote(client, data, interactive) {
	const desc = data.description || data.tool || "";
	stdout.write(`\n${BOLD}⚠ 确认请求（${data.tool || "tool"}）${RESET}: ${desc}\n`);
	if (!interactive) {
		stdout.write(`${DIM}非交互环境，自动拒绝（可在 TTY 下重跑以批准）${RESET}\n`);
		await client.post(`/agent/reject/${data.id}`).catch(() => {});
		return;
	}
	const rl = createInterface({ input: stdin, output: stdout });
	const answer = (await rl.question("批准执行? [y/N] ")).trim().toLowerCase();
	rl.close();
	const ok = answer === "y" || answer === "yes";
	stdout.write(`${DIM}${ok ? "✓ 已批准" : "✗ 已拒绝"}${RESET}\n`);
	await client.post(`/agent/${ok ? "confirm" : "reject"}/${data.id}`).catch(() => {});
}

/**
 * 云端会话交互模式（pm chat / pm 无参）：多轮对话循环，会话数据全在服务端
 * （agent_conversations——与 Web 聊天同一存储，任何端续接同一对话）。
 * CLI 本地只保存 conversation_id 指针；斜杠命令：/new 开新会话 /exit 退出。
 * 注意：循环 readline 在调用 runRemotePrompt 前必须关闭——确认卡会另开
 * readline 读 stdin，两者并存会抢输入。
 */
export async function runRemoteChat({ client, interactive = Boolean(stdin.isTTY) }) {
	if (!interactive) {
		stderr.write("交互模式需要 TTY（在终端中运行）。\n");
		return EXIT_CODE_OK;
	}
	let conversationId = await loadAgentConversationId();
	stdout.write(
		`${BOLD}pm 云端会话${RESET}` +
			(conversationId
				? `${DIM}（续接 ${conversationId.slice(0, 8)})${RESET}`
				: `${DIM}（新会话）${RESET}`) +
			`\n${DIM}/new 新会话 · /exit 退出 · 输入消息与云端 agent 对话。数据存于服务端。${RESET}\n`,
	);
	for (;;) {
		const rl = createInterface({ input: stdin, output: stdout });
		const line = (await rl.question(`${BOLD}你 › ${RESET}`)).trim();
		rl.close();
		if (!line) continue;
		if (line === "/exit" || line === "/q" || line === "exit" || line === "quit") {
			stdout.write(
				`${DIM}再见。会话已存云端（conversation: ${conversationId || "无"}）${RESET}\n`,
			);
			return EXIT_CODE_OK;
		}
		if (line === "/new") {
			conversationId = null;
			await saveAgentConversationId(null).catch(() => {});
			stdout.write(`${DIM}已开新会话${RESET}\n`);
			continue;
		}
		if (line === "/help") {
			stdout.write(`${DIM}/new 新会话 · /exit 退出 · 其余内容直接发给云端 agent${RESET}\n`);
			continue;
		}
		const { conversationId: next, ok } = await runRemotePrompt({
			client,
			message: line,
			conversationId,
			interactive,
		});
		conversationId = next || conversationId;
		if (!ok) stdout.write(`${DIM}（上一轮出错——会话仍可继续，直接输入即可）${RESET}\n`);
	}
}

const EXIT_CODE_OK = 0;
