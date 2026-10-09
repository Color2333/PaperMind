// pm 云端 TUI（全屏）：pi-tui 组件驱动生产 /agent/chat SSE。
// 数据全在服务端（agent_conversations）——CLI 零 LLM 依赖、零本地会话文件。
// 确认卡 v1：自动拒绝 + 显式提示（Web 端可批准）；键盘交互确认留 v2。

import { Container, Markdown, ProcessTerminal, Text, TuiMainScreen } from "@earendil-works/pi-tui";
import { chatStream, loadAgentConversationId, saveAgentConversationId } from "./remote.js";

const DIM = (s) => `\x1b[2m${s}\x1b[0m`;
const BOLD = (s) => `\x1b[1m${s}\x1b[0m`;
const ACCENT = (s) => `\x1b[36m${s}\x1b[0m`;
const RED = (s) => `\x1b[31m${s}\x1b[0m`;

const mdTheme = {
	heading: (t) => BOLD(ACCENT(t)),
	link: (t) => `\x1b[34m${t}\x1b[0m`,
	linkUrl: (t) => DIM(t),
	code: (t) => `\x1b[33m${t}\x1b[0m`,
	codeBlock: (t) => DIM(t),
	codeBlockBorder: () => "",
	quote: (t) => DIM(t),
	quoteBorder: (t) => ACCENT(t),
	hr: (t) => DIM(t),
	listBullet: (t) => ACCENT(t),
	bold: BOLD,
	italic: (t) => `\x1b[3m${t}\x1b[0m`,
	strikethrough: (t) => `\x1b[9m${t}\x1b[0m`,
	underline: (t) => `\x1b[4m${t}\x1b[0m`,
};

/** 底部输入行：Component（渲染）+ TUI input listener（按键）二合一 */
class InputLine {
	text = "";
	constructor(onSubmit, onExit) {
		this.onSubmit = onSubmit;
		this.onExit = onExit;
	}
	handleInput(data) {
		let submitted = false;
		for (const ch of data) {
			if (ch === "\x03") {
				this.onExit?.();
				return { handled: true, render: true };
			}
			if (ch === "\r" || ch === "\n") {
				const t = this.text;
				this.text = "";
				submitted = true;
				this.onSubmit?.(t);
			} else if (ch === "\x7f") {
				this.text = this.text.slice(0, -1);
			} else if (ch >= " ") {
				this.text += ch;
			}
		}
		return { handled: true, render: true };
	}
	invalidate() {}
	render() {
		return [`${BOLD("你 › ")}${this.text}\x1b[7m \x1b[0m`];
	}
}

/** 云端会话全屏 TUI：多轮对话，会话数据全在服务端。需要 TTY。 */
export async function runCloudTui({ client }) {
	const terminal = new ProcessTerminal();
	const tui = new TuiMainScreen(terminal);
	const messages = new Container();
	tui.addChild(messages);

	let conversationId = await loadAgentConversationId();
	messages.addChild(
		new Text(
			BOLD("pm 云端会话") +
				DIM(conversationId ? `（续接 ${conversationId.slice(0, 8)}）` : "（新会话）") +
				DIM(" — 数据存于服务端 · /new 新会话 · ctrl+c 退出"),
			0,
			0,
		),
	);

	const onExit = () => {
		try {
			tui.stop();
		} catch {}
		process.exit(0);
	};

	let busy = false;
	const submit = (text) => {
		if (busy) {
			messages.addChild(new Text(DIM("（上一轮还在进行中……）"), 0, 0));
			tui.requestRender();
			return Promise.resolve();
		}
		messages.addChild(new Text(BOLD(`你 › ${text}`), 0, 0));
		const md = new Markdown("", 1, 0, mdTheme);
		const status = new Text("", 0, 0);
		messages.addChild(md);
		messages.addChild(status);
		let buf = "";
		busy = true;
		return chatStream({
			client,
			message: text,
			conversationId,
			handlers: {
				onConversationInit: (id) => {
					conversationId = id || conversationId;
					saveAgentConversationId(conversationId).catch(() => {});
				},
				onTextDelta: (delta) => {
					buf += delta;
					md.setText(buf);
					tui.requestRender();
				},
				onToolStart: (tool) => {
					status.setText(DIM(`⚙ ${tool} …`));
					tui.requestRender();
				},
				onToolResult: (tool) => {
					status.setText(DIM(`✓ ${tool} 完成`));
					tui.requestRender();
				},
				onConfirm: (data) => {
					status.setText(
						RED(
							`⚠ 确认请求（${data.tool}）：${data.description || ""} —— 已自动拒绝；如需执行请在 Web 端批准后重试`,
						),
					);
					tui.requestRender();
					return client.post(`/agent/reject/${data.id}`).catch(() => {});
				},
				onError: (msg) => {
					messages.addChild(new Text(RED(`错误: ${msg}`), 0, 0));
					tui.requestRender();
				},
			},
		})
			.then(({ ok }) => {
				if (ok) status.setText(DIM(`（conversation: ${conversationId?.slice(0, 8) || "-"}）`));
				else status.setText(RED("（该轮以错误结束）"));
			})
			.catch((err) => {
				messages.addChild(new Text(RED(`请求失败: ${err?.message || err}`), 0, 0));
			})
			.finally(() => {
				busy = false;
				tui.requestRender();
			});
	};

	const input = new InputLine(
		(text) => {
			const line = text.trim();
			if (!line) return;
			if (line === "/exit" || line === "/q") {
				messages.addChild(new Text(DIM("再见。会话已存云端。"), 0, 0));
				tui.requestRender();
				setTimeout(onExit, 50);
				return;
			}
			if (line === "/new") {
				conversationId = null;
				saveAgentConversationId(null).catch(() => {});
				messages.addChild(new Text(DIM("已开新会话。"), 0, 0));
				tui.requestRender();
				return;
			}
			void submit(line);
		},
		onExit,
	);
	tui.addChild(input);
	tui.addInputListener((data) => input.handleInput(data));

	tui.start();
	tui.requestRender();
	await new Promise(() => {}); // 常驻：退出走 onExit / ctrl+c
}
