/**
 * Agent 会话全局上下文 - SSE 流和对话状态在页面切换时保持存活
 * @author Bamzc
 */
import { createContext, useContext, useState, useRef, useEffect, useCallback, useMemo } from "react";
import { agentApi } from "@/services/api";
import type { AgentMessage, SSEEvent, SSEEventType } from "@/types";
import { parseSSEStream } from "@/types";
import { useConversationCtx } from "@/contexts/ConversationContext";
import { loadConversation } from "@/hooks/useConversations";
import type { ConversationMessage } from "@/hooks/useConversations";

/* ========== 共享类型 ========== */

export interface ChatItem {
  id: string;
  type: "user" | "assistant" | "step_group" | "action_confirm" | "error" | "artifact";
  content: string;
  streaming?: boolean;
  steps?: StepItem[];
  actionId?: string;
  actionDescription?: string;
  actionTool?: string;
  toolArgs?: Record<string, unknown>;
  artifactTitle?: string;
  artifactContent?: string;
  artifactIsHtml?: boolean;
  timestamp: Date;
}

export interface StepItem {
  id: string;
  status: "running" | "done" | "error";
  toolName: string;
  toolArgs?: Record<string, unknown>;
  success?: boolean;
  summary?: string;
  data?: Record<string, unknown>;
  progressMessage?: string;
  progressCurrent?: number;
  progressTotal?: number;
}

export interface CanvasData {
  title: string;
  markdown: string;
  isHtml?: boolean;
}

/* ========== Context 接口 ========== */

interface AgentSessionCtx {
  items: ChatItem[];
  loading: boolean;
  pendingActions: Set<string>;
  confirmingActions: Set<string>;
  canvas: CanvasData | null;
  hasPendingConfirm: boolean;
  setCanvas: (v: CanvasData | null) => void;
  sendMessage: (text: string) => Promise<void>;
  handleConfirm: (actionId: string) => Promise<void>;
  handleReject: (actionId: string) => Promise<void>;
  stopGeneration: () => void;
}

const Ctx = createContext<AgentSessionCtx | null>(null);

/* ========== Provider ========== */

export function AgentSessionProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [pendingActions, setPendingActions] = useState<Set<string>>(new Set());
  const [confirmingActions, setConfirmingActions] = useState<Set<string>>(new Set());
  const [canvas, setCanvas] = useState<CanvasData | null>(null);

  const { activeId, createConversation, saveMessages } = useConversationCtx();
  const justCreatedRef = useRef(false);
  const activeIdRef = useRef(activeId);
  activeIdRef.current = activeId;

  /* ---- SSE 流取消控制 ---- */
  const abortRef = useRef<AbortController | null>(null);

  const cancelStream = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  useEffect(() => cancelStream, [cancelStream]);

  /* ---- 流式文本缓冲（RAF 方式，减少 setItems 调用） ---- */
  const streamBufRef = useRef("");
  const rafIdRef = useRef<number | null>(null);

  const drainBuffer = useCallback(() => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    const text = streamBufRef.current;
    streamBufRef.current = "";
    return text;
  }, []);

  const flushStreamBuffer = useCallback(() => {
    const text = streamBufRef.current;
    if (!text) return;
    streamBufRef.current = "";
    setItems((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.type === "assistant" && last.streaming) {
        const copy = [...prev];
        copy[copy.length - 1] = { ...last, content: last.content + text };
        return copy;
      }
      return [
        ...prev,
        { id: `asst_${Date.now()}`, type: "assistant" as const, content: text, streaming: true, timestamp: new Date() },
      ];
    });
  }, []);

  const scheduleFlush = useCallback(() => {
    if (rafIdRef.current !== null) return;
    rafIdRef.current = requestAnimationFrame(() => {
      rafIdRef.current = null;
      flushStreamBuffer();
    });
  }, [flushStreamBuffer]);

  /* ---- 切换对话时恢复消息 —— 直接读 localStorage，绕过 React state 异步 ---- */
  useEffect(() => {
    if (justCreatedRef.current) {
      justCreatedRef.current = false;
      return;
    }
    const conv = activeId ? loadConversation(activeId) : null;
    if (conv && conv.messages.length > 0) {
      setItems(conv.messages.map((m): ChatItem => ({
        id: m.id,
        type: m.type,
        content: m.content,
        timestamp: new Date(m.timestamp),
        streaming: false,
        steps: m.steps,
        actionId: m.actionId,
        actionDescription: m.actionDescription,
        actionTool: m.actionTool,
        toolArgs: m.toolArgs,
        artifactTitle: m.artifactTitle,
        artifactContent: m.artifactContent,
        artifactIsHtml: m.artifactIsHtml,
      })));
    } else {
      setItems([]);
    }
    setPendingActions(new Set());
    setCanvas(null);
  }, [activeId]);

  /* ---- 保存对话到 localStorage ---- */
  const buildSavePayload = useCallback((snapshot: ChatItem[]): ConversationMessage[] => {
    return snapshot
      .map((it) => {
        const base: ConversationMessage = {
          id: it.id,
          type: it.type,
          content: it.streaming ? it.content + streamBufRef.current : it.content,
          timestamp: it.timestamp.toISOString(),
        };
        if (it.type === "step_group" && it.steps) base.steps = it.steps;
        if (it.type === "action_confirm") {
          base.actionId = it.actionId;
          base.actionDescription = it.actionDescription;
          base.actionTool = it.actionTool;
          base.toolArgs = it.toolArgs;
        }
        if (it.type === "artifact") {
          base.artifactTitle = it.artifactTitle;
          base.artifactContent = it.artifactContent;
          base.artifactIsHtml = it.artifactIsHtml;
        }
        return base;
      });
  }, []);

  /* 防抖保存 */
  useEffect(() => {
    if (!activeId || items.length === 0) return;
    const timer = setTimeout(() => {
      const msgs = buildSavePayload(items.filter((it) => !it.streaming));
      if (msgs.length > 0) saveMessages(msgs);
    }, 1000);
    return () => clearTimeout(timer);
  }, [items, activeId, saveMessages, buildSavePayload]);

  /* 页面关闭/刷新前同步保存（包括 streaming 中的内容） */
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (!activeIdRef.current || items.length === 0) return;
      const msgs = buildSavePayload(items);
      if (msgs.length > 0) saveMessages(msgs);
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [items, buildSavePayload, saveMessages]);

  /* ---- 工具函数 ---- */
  const applyPendingText = (copy: ChatItem[], pendingText: string): void => {
    const lastIdx = copy.length - 1;
    if (lastIdx < 0) {
      if (pendingText) {
        copy.push({ id: `asst_${Date.now()}`, type: "assistant" as const, content: pendingText, streaming: false, timestamp: new Date() });
      }
      return;
    }
    const last = copy[lastIdx];
    if (last.type === "assistant" && last.streaming) {
      copy[lastIdx] = { ...last, content: last.content + pendingText, streaming: false };
    } else if (pendingText) {
      copy.push({ id: `asst_${Date.now()}`, type: "assistant" as const, content: pendingText, streaming: false, timestamp: new Date() });
    }
  };

  /* ---- SSE 事件处理 ---- */
  const processSSE = useCallback(
    (event: SSEEvent) => {
      const { type, data } = event;
      const id = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

      switch (type as SSEEventType) {
        case "text_delta": {
          streamBufRef.current += (data.content as string) || "";
          scheduleFlush();
          break;
        }
        case "tool_start": {
          const pending = drainBuffer();
          setItems((prev) => {
            const copy = [...prev];
            applyPendingText(copy, pending);
            const toolName = data.name as string;
            const toolArgs = data.args as Record<string, unknown>;
            const stepId = (data.id as string) || id;
            const last = copy[copy.length - 1];
            if (last && last.type === "step_group") {
              const steps = [...(last.steps || [])];
              steps.push({ id: stepId, status: "running", toolName, toolArgs });
              copy[copy.length - 1] = { ...last, steps };
              return copy;
            }
            return [...copy, { id, type: "step_group" as const, content: "", steps: [{ id: stepId, status: "running", toolName, toolArgs }], timestamp: new Date() }];
          });
          break;
        }
        case "tool_progress": {
          const progId = (data.id as string) || "";
          const progMsg = (data.message as string) || "";
          const progCur = (data.current as number) || 0;
          const progTotal = (data.total as number) || 0;
          setItems((prev) => {
            const copy = [...prev];
            for (let i = copy.length - 1; i >= 0; i--) {
              if (copy[i].type === "step_group" && copy[i].steps) {
                const steps = [...copy[i].steps!];
                const idx = progId
                  ? steps.findIndex((s) => s.id === progId)
                  : steps.findIndex((s) => s.status === "running");
                if (idx >= 0) {
                  steps[idx] = { ...steps[idx], progressMessage: progMsg, progressCurrent: progCur, progressTotal: progTotal };
                  copy[i] = { ...copy[i], steps };
                  return copy;
                }
              }
            }
            return prev;
          });
          break;
        }
        case "tool_result": {
          const toolId = (data.id as string) || "";
          const toolName = data.name as string;
          setItems((prev) => {
            const copy = [...prev];
            for (let i = copy.length - 1; i >= 0; i--) {
              if (copy[i].type === "step_group" && copy[i].steps) {
                const steps = [...copy[i].steps!];
                const idx = toolId
                  ? steps.findIndex((s) => s.id === toolId)
                  : steps.findIndex((s) => s.toolName === toolName && s.status === "running");
                if (idx >= 0) {
                  steps[idx] = { ...steps[idx], status: (data.success as boolean) ? "done" : "error", success: data.success as boolean, summary: data.summary as string, data: data.data as Record<string, unknown> };
                  copy[i] = { ...copy[i], steps };
                  return copy;
                }
              }
            }
            return prev;
          });
          if (data.success && data.data) {
            const d = data.data as Record<string, unknown>;
            if (d.html) {
              // HTML 类 artifact（简报等）
              const artTitle = String(d.title || "Daily Brief");
              const artContent = String(d.html);
              setItems((prev) => [...prev, {
                id: `art_${Date.now()}`, type: "artifact" as const, content: "",
                artifactTitle: artTitle, artifactContent: artContent, artifactIsHtml: true,
                timestamp: new Date(),
              }]);
              setCanvas({ title: artTitle, markdown: artContent, isHtml: true });
            } else if (d.markdown) {
              // Markdown 类 artifact（Wiki、RAG 问答报告等）
              const artTitle = String(d.title || "报告");
              const artContent = String(d.markdown);
              setItems((prev) => [...prev, {
                id: `art_${Date.now()}`, type: "artifact" as const, content: "",
                artifactTitle: artTitle, artifactContent: artContent, artifactIsHtml: false,
                timestamp: new Date(),
              }]);
              setCanvas({ title: artTitle, markdown: artContent });
            }
          }
          break;
        }
        case "action_confirm": {
          const pending = drainBuffer();
          const actionId = data.id as string;
          setPendingActions((prev) => new Set(prev).add(actionId));
          setItems((prev) => {
            const copy = [...prev];
            applyPendingText(copy, pending);
            return [...copy, { id, type: "action_confirm" as const, content: "", actionId, actionDescription: data.description as string, actionTool: data.tool as string, toolArgs: data.args as Record<string, unknown>, timestamp: new Date() }];
          });
          setLoading(false);
          break;
        }
        case "action_result": {
          const arId = (data.id as string) || "";
          setItems((prev) => {
            const copy = [...prev];
            for (let i = copy.length - 1; i >= 0; i--) {
              if (copy[i].type === "step_group" && copy[i].steps) {
                const steps = [...copy[i].steps!];
                const running = steps.findIndex((s) => s.status === "running");
                if (running >= 0) {
                  steps[running] = { ...steps[running], status: (data.success as boolean) ? "done" : "error", success: data.success as boolean, summary: data.summary as string, data: data.data as Record<string, unknown> };
                  copy[i] = { ...copy[i], steps };
                  return copy;
                }
              }
            }
            const last = copy[copy.length - 1];
            if (last && last.type === "step_group") {
              const steps = [...(last.steps || [])];
              steps.push({ id: arId, status: ((data.success as boolean) ? "done" : "error") as "done" | "error", toolName: "操作执行", success: data.success as boolean, summary: data.summary as string, data: data.data as Record<string, unknown> });
              copy[copy.length - 1] = { ...last, steps };
              return copy;
            }
            return [...prev, { id: `sg_${Date.now()}`, type: "step_group" as const, content: "", steps: [{ id: arId, status: ((data.success as boolean) ? "done" : "error") as "done" | "error", toolName: "操作执行", success: data.success as boolean, summary: data.summary as string, data: data.data as Record<string, unknown> }], timestamp: new Date() }];
          });
          if (data.success && data.data) {
            const d = data.data as Record<string, unknown>;
            if (d.markdown) {
              const artTitle = String(d.title || "Wiki");
              const artContent = String(d.markdown);
              setItems((prev) => [...prev, {
                id: `art_${Date.now()}`, type: "artifact" as const, content: "",
                artifactTitle: artTitle, artifactContent: artContent, artifactIsHtml: false,
                timestamp: new Date(),
              }]);
              setCanvas({ title: artTitle, markdown: artContent });
            } else if (d.html) {
              const artTitle = String(d.title || "Daily Brief");
              const artContent = String(d.html);
              setItems((prev) => [...prev, {
                id: `art_${Date.now()}`, type: "artifact" as const, content: "",
                artifactTitle: artTitle, artifactContent: artContent, artifactIsHtml: true,
                timestamp: new Date(),
              }]);
              setCanvas({ title: artTitle, markdown: artContent, isHtml: true });
            }
          }
          break;
        }
        case "error": {
          const pending = drainBuffer();
          setItems((prev) => {
            const copy = [...prev];
            applyPendingText(copy, pending);
            return [...copy, { id, type: "error" as const, content: (data.message as string) || "未知错误", timestamp: new Date() }];
          });
          break;
        }
        case "done": {
          const pending = drainBuffer();
          setItems((prev) => {
            const hasStreaming = prev.some((it) => it.type === "assistant" && it.streaming);
            if (hasStreaming) {
              return prev.map((item) =>
                item.type === "assistant" && item.streaming
                  ? { ...item, content: item.content + pending, streaming: false }
                  : item,
              );
            }
            if (pending) {
              return [...prev, { id: `asst_done_${Date.now()}`, type: "assistant" as const, content: pending, streaming: false, timestamp: new Date() }];
            }
            return prev;
          });
          setLoading(false);
          break;
        }
      }
    },
    [scheduleFlush, drainBuffer],
  );

  /**
   * 启动 SSE 流并处理完成回调
   */
  const startStream = useCallback(
    (reader: ReadableStreamDefaultReader<Uint8Array>, signal?: AbortSignal) => {
      parseSSEStream(reader, processSSE, () => {
        /* 兜底：仅在流异常关闭（未收到 done 事件）时清理状态 */
        setLoading((current) => {
          if (!current) return false;
          const pending = drainBuffer();
          if (pending) {
            setItems((prev) => {
              const hasStreaming = prev.some((it) => it.type === "assistant" && it.streaming);
              if (hasStreaming) {
                return prev.map((item) =>
                  item.type === "assistant" && item.streaming
                    ? { ...item, content: item.content + pending, streaming: false }
                    : item,
                );
              }
              if (pending) return [...prev, { id: `asst_fallback_${Date.now()}`, type: "assistant" as const, content: pending, streaming: false, timestamp: new Date() }];
              return prev;
            });
          }
          return false;
        });
      });

      if (signal) {
        signal.addEventListener("abort", () => {
          reader.cancel().catch(() => {});
          setLoading(false);
        });
      }
    },
    [processSSE, drainBuffer],
  );

  /* ---- 发送消息 ---- */
  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || loading || pendingActions.size > 0) {
        throw new Error("blocked");
      }
      cancelStream();
      if (!activeIdRef.current) {
        justCreatedRef.current = true;
        createConversation();
      }
      setLoading(true);
      setItems((prev) => [...prev, { id: `user_${Date.now()}`, type: "user" as const, content: text.trim(), timestamp: new Date() }]);
      const msgs: AgentMessage[] = [];
      for (const it of items) {
        if (it.type === "user") {
          msgs.push({ role: "user", content: it.content });
        } else if (it.type === "assistant") {
          msgs.push({ role: "assistant", content: it.content });
        } else if (it.type === "step_group" && it.steps) {
          const summaries = it.steps
            .filter((s) => s.status === "done" || s.status === "error")
            .map((s) => `[工具: ${s.toolName}] ${s.success ? "成功" : "失败"}: ${s.summary || ""}`)
            .join("\n");
          if (summaries) {
            msgs.push({ role: "assistant", content: `执行了以下操作:\n${summaries}` });
          }
        } else if (it.type === "action_confirm") {
          msgs.push({ role: "assistant", content: `[等待确认] ${it.actionDescription || it.actionTool || ""}` });
        } else if (it.type === "artifact") {
          msgs.push({ role: "assistant", content: `[已生成内容: ${it.artifactTitle || "未命名"}]\n${(it.artifactContent || "").slice(0, 500)}` });
        } else if (it.type === "error") {
          msgs.push({ role: "assistant", content: `[错误: ${it.content}]` });
        }
      }
      msgs.push({ role: "user" as const, content: text.trim() });
      try {
        const ac = new AbortController();
        abortRef.current = ac;
        const resp = await agentApi.chat(msgs);
        if (!resp.body) {
          setItems((p) => [...p, { id: `e_${Date.now()}`, type: "error" as const, content: "无响应流", timestamp: new Date() }]);
          setLoading(false);
          return;
        }
        startStream(resp.body.getReader(), ac.signal);
      } catch (err) {
        setItems((p) => [...p, { id: `e_${Date.now()}`, type: "error" as const, content: err instanceof Error ? err.message : "请求失败", timestamp: new Date() }]);
        setLoading(false);
      }
    },
    [items, loading, pendingActions, cancelStream, createConversation, startStream],
  );

  /* ---- 确认/拒绝操作 ---- */
  const handleConfirm = useCallback(
    async (actionId: string) => {
      setConfirmingActions((prev) => new Set(prev).add(actionId));
      setPendingActions((prev) => { const n = new Set(prev); n.delete(actionId); return n; });
      cancelStream();
      setLoading(true);
      try {
        const ac = new AbortController();
        abortRef.current = ac;
        const resp = await agentApi.confirm(actionId);
        if (resp.body) startStream(resp.body.getReader(), ac.signal);
        else setLoading(false);
      } catch (err) {
        setItems((p) => [...p, { id: `e_${Date.now()}`, type: "error" as const, content: err instanceof Error ? err.message : "确认失败", timestamp: new Date() }]);
        setLoading(false);
      } finally {
        setConfirmingActions((prev) => { const n = new Set(prev); n.delete(actionId); return n; });
      }
    },
    [startStream, cancelStream],
  );

  const handleReject = useCallback(
    async (actionId: string) => {
      setPendingActions((prev) => { const n = new Set(prev); n.delete(actionId); return n; });
      cancelStream();
      setLoading(true);
      try {
        const ac = new AbortController();
        abortRef.current = ac;
        const resp = await agentApi.reject(actionId);
        if (resp.body) {
          startStream(resp.body.getReader(), ac.signal);
        } else {
          setLoading(false);
        }
      } catch (err) {
        setItems((p) => [...p, { id: `e_${Date.now()}`, type: "error" as const, content: err instanceof Error ? err.message : "拒绝操作失败", timestamp: new Date() }]);
        setLoading(false);
      }
    },
    [startStream, cancelStream],
  );

  const hasPendingConfirm = pendingActions.size > 0;

  const stopGeneration = useCallback(() => {
    cancelStream();
    const pending = drainBuffer();
    setLoading(false);
    setItems((prev) =>
      prev.map((item) =>
        item.type === "assistant" && item.streaming
          ? { ...item, content: item.content + pending, streaming: false }
          : item,
      ),
    );
  }, [cancelStream, drainBuffer]);

  const value: AgentSessionCtx = useMemo(() => ({
    items, loading, pendingActions, confirmingActions, canvas, hasPendingConfirm,
    setCanvas, sendMessage, handleConfirm, handleReject, stopGeneration,
  }), [items, loading, pendingActions, confirmingActions, canvas, hasPendingConfirm,
    setCanvas, sendMessage, handleConfirm, handleReject, stopGeneration]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAgentSession(): AgentSessionCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAgentSession must be inside AgentSessionProvider");
  return ctx;
}
