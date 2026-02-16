/**
 * 对话历史管理 - localStorage 持久化
 * @author Bamzc
 */
import { useState, useCallback, useEffect } from "react";
import { uid } from "@/lib/utils";

const STORAGE_KEY = "papermind_conversations";
const MAX_CONVERSATIONS = 100;

export interface ConversationMeta {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}

export interface ConversationMessageStep {
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

export interface ConversationMessage {
  id: string;
  type: "user" | "assistant" | "step_group" | "action_confirm" | "error" | "artifact";
  content: string;
  timestamp: string;
  /* step_group */
  steps?: ConversationMessageStep[];
  /* action_confirm */
  actionId?: string;
  actionDescription?: string;
  actionTool?: string;
  toolArgs?: Record<string, unknown>;
  /* artifact */
  artifactTitle?: string;
  artifactContent?: string;
  artifactIsHtml?: boolean;
}

export interface Conversation extends ConversationMeta {
  messages: ConversationMessage[];
}

/**
 * 从 localStorage 加载对话列表（仅元信息）
 */
function loadMetas(): ConversationMeta[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY + "_index");
    if (!raw) return [];
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

function saveMetas(metas: ConversationMeta[]) {
  localStorage.setItem(STORAGE_KEY + "_index", JSON.stringify(metas));
}

function loadConversation(id: string): Conversation | null {
  try {
    const raw = localStorage.getItem(`${STORAGE_KEY}_${id}`);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function saveConversation(conv: Conversation) {
  localStorage.setItem(`${STORAGE_KEY}_${conv.id}`, JSON.stringify(conv));
}

function removeConversation(id: string) {
  localStorage.removeItem(`${STORAGE_KEY}_${id}`);
}

/**
 * 自动生成对话标题（取第一条用户消息前 30 字）
 */
function autoTitle(messages: ConversationMessage[]): string {
  const first = messages.find((m) => m.type === "user");
  if (!first) return "新对话";
  const text = first.content.trim();
  return text.length > 30 ? text.slice(0, 30) + "..." : text;
}

/**
 * 对话管理 Hook
 */
export function useConversations() {
  const [metas, setMetas] = useState<ConversationMeta[]>(loadMetas);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeConv, setActiveConv] = useState<Conversation | null>(null);

  // 加载 metas 初始化
  useEffect(() => {
    setMetas(loadMetas());
  }, []);

  /**
   * 创建新对话
   */
  const createConversation = useCallback((): string => {
    const now = new Date().toISOString();
    const id = uid();
    const conv: Conversation = {
      id,
      title: "新对话",
      createdAt: now,
      updatedAt: now,
      messages: [],
    };
    saveConversation(conv);
    const newMetas = [
      { id, title: conv.title, createdAt: now, updatedAt: now },
      ...metas,
    ].slice(0, MAX_CONVERSATIONS);
    saveMetas(newMetas);
    setMetas(newMetas);
    setActiveId(id);
    setActiveConv(conv);
    return id;
  }, [metas]);

  /**
   * 切换到指定对话
   */
  const switchConversation = useCallback((id: string) => {
    const conv = loadConversation(id);
    setActiveId(id);
    setActiveConv(conv);
  }, []);

  /**
   * 保存当前对话消息
   * 只写 localStorage + 更新 sidebar meta，不调 setActiveConv。
   * 这样不会触发 Agent.tsx 的 restore useEffect 覆盖 items。
   */
  const saveMessages = useCallback(
    (messages: ConversationMessage[]) => {
      if (!activeId) return;
      const now = new Date().toISOString();
      const title = autoTitle(messages);
      // 从 localStorage 读 createdAt，避免依赖 activeConv 状态
      const existing = loadConversation(activeId);
      const conv: Conversation = {
        id: activeId,
        title,
        createdAt: existing?.createdAt || now,
        updatedAt: now,
        messages,
      };
      saveConversation(conv);

      // 更新 meta（sidebar 显示用）
      setMetas((prev) => {
        const updated = prev.map((m) =>
          m.id === activeId ? { ...m, title, updatedAt: now } : m,
        );
        const idx = updated.findIndex((m) => m.id === activeId);
        if (idx > 0) {
          const [item] = updated.splice(idx, 1);
          updated.unshift(item);
        }
        saveMetas(updated);
        return updated;
      });
    },
    [activeId],
  );

  /**
   * 删除对话
   */
  const deleteConversation = useCallback(
    (id: string) => {
      removeConversation(id);
      setMetas((prev) => {
        const updated = prev.filter((m) => m.id !== id);
        saveMetas(updated);
        return updated;
      });
      if (activeId === id) {
        setActiveId(null);
        setActiveConv(null);
      }
    },
    [activeId],
  );

  return {
    metas,
    activeId,
    activeConv,
    createConversation,
    switchConversation,
    saveMessages,
    deleteConversation,
  };
}

/**
 * 按日期分组
 */
export function groupByDate(metas: ConversationMeta[]): { label: string; items: ConversationMeta[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<string, ConversationMeta[]> = {
    "今天": [],
    "昨天": [],
    "最近 7 天": [],
    "更早": [],
  };

  for (const m of metas) {
    const d = new Date(m.updatedAt);
    if (d >= today) groups["今天"].push(m);
    else if (d >= yesterday) groups["昨天"].push(m);
    else if (d >= weekAgo) groups["最近 7 天"].push(m);
    else groups["更早"].push(m);
  }

  return Object.entries(groups)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }));
}
