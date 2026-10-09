// pm -p 远程 agent（方案 A）单元测试：SSE 解析 / 渲染回调 / 非 TTY 确认自动拒绝 / 会话持久化
import { describe, it, mock } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { parseSseChunk, runRemotePrompt } from "../src/agent/remote.js";

describe("parseSseChunk", () => {
	it("解析 event/data 行对", () => {
		const r = parseSseChunk('event: text_delta\ndata: {"content":"你好"}');
		assert.equal(r.event, "text_delta");
		assert.equal(r.data.content, "你好");
	});

	it("data 缺失返回 null；坏 JSON 返回 null", () => {
		assert.equal(parseSseChunk("event: ping"), null);
		assert.equal(parseSseChunk('event: x\ndata: {bad'), null);
	});
});

describe("runRemotePrompt", () => {
	function mockClient(chunks, capture) {
		return {
			postStream: async (_path, body, onChunk) => {
				capture.body = body;
				for (const c of chunks) onChunk(c);
			},
			post: async (path) => {
				capture.confirms = capture.confirms || [];
				capture.confirms.push(path);
				return { ok: true };
			},
		};
	}

	it("按序处理事件并回传 conversation_id", async () => {
		const capture = {};
		const chunks = [
			'event: conversation_init\ndata: {"conversation_id":"conv-1"}',
			'event: text_delta\ndata: {"content":"你"}',
			'event: text_delta\ndata: {"content":"好"}',
			'event: done\ndata: {}',
		];
		const { conversationId, ok } = await runRemotePrompt({
			client: mockClient(chunks, capture),
			message: "你好",
			interactive: false,
		});
		assert.equal(conversationId, "conv-1");
		assert.equal(ok, true);
		assert.equal(capture.body.messages[0].content, "你好");
	});

	it("已有 conversation_id 时随请求续接", async () => {
		const capture = {};
		await runRemotePrompt({
			client: mockClient(['event: done\ndata: {}'], capture),
			message: "继续",
			conversationId: "conv-9",
			interactive: false,
		});
		assert.equal(capture.body.conversation_id, "conv-9");
	});

	it("非 TTY 的 action_confirm 自动拒绝（安全默认）", async () => {
		const capture = {};
		const chunks = [
			'event: action_confirm\ndata: {"id":"act-1","tool":"delete_paper","description":"删除论文"}',
			'event: done\ndata: {}',
		];
		await runRemotePrompt({
			client: mockClient(chunks, capture),
			message: "删",
			interactive: false,
		});
		assert.deepEqual(capture.confirms, ["/agent/reject/act-1"]);
	});

	it("conversation_id 持久化到 configDir/agent-session.json", async () => {
		const dir = mkdtempSync(join(tmpdir(), "pm-cli-test-"));
		const orig = process.env.PAPERMIND_CONFIG_DIR;
		process.env.PAPERMIND_CONFIG_DIR = dir;
		try {
			const { conversationId } = await runRemotePrompt({
				client: mockClient(['event: conversation_init\ndata: {"conversation_id":"conv-p"}'], {}),
				message: "m",
				interactive: false,
			});
			assert.equal(conversationId, "conv-p");
			const saved = JSON.parse(readFileSync(join(dir, "agent-session.json"), "utf8"));
			assert.equal(saved.conversationId, "conv-p");
		} finally {
			if (orig === undefined) delete process.env.PAPERMIND_CONFIG_DIR;
			else process.env.PAPERMIND_CONFIG_DIR = orig;
		}
	});
});
