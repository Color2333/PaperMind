/**
 * 对话上下文 - Sidebar 和 Agent 共享对话状态
 * @author Bamzc
 */
import { createContext, useContext } from "react";
import {
  useConversations,
  type ConversationMeta,
  type Conversation,
  type ConversationMessage,
} from "@/hooks/useConversations";

interface ConversationCtx {
  metas: ConversationMeta[];
  activeId: string | null;
  activeConv: Conversation | null;
  createConversation: () => string;
  switchConversation: (id: string) => void;
  saveMessages: (messages: ConversationMessage[]) => void;
  deleteConversation: (id: string) => void;
}

const Ctx = createContext<ConversationCtx | null>(null);

export function ConversationProvider({ children }: { children: React.ReactNode }) {
  const store = useConversations();
  return <Ctx.Provider value={store}>{children}</Ctx.Provider>;
}

export function useConversationCtx(): ConversationCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useConversationCtx must be inside ConversationProvider");
  return ctx;
}
