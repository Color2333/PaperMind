/**
 * 对话窄栏（知识工作台第二栏）：Pi agent 常驻输入线。
 * 会话切换/新建收进头部下拉；主体复用 AgentPage（自包含，受上下文驱动）。
 * @author Color2333
 */
import { useState } from "react";
import { MessageSquare, Plus, ChevronDown, PanelLeftClose, Trash2 } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { useConversationCtx } from "@/contexts/ConversationContext";
import AgentPage from "@/pages/Agent";

export default function ChatPane({ onCollapse }: { onCollapse: () => void }) {
  const { metas, activeId, createConversation, switchConversation, deleteConversation } =
    useConversationCtx();
  const [listOpen, setListOpen] = useState(false);

  return (
    <aside className="border-border bg-surface flex h-full w-[400px] shrink-0 flex-col border-r">
      {/* 头部：会话管理 */}
      <div className="border-border relative flex items-center gap-1.5 border-b px-2.5 py-2">
        <MessageSquare className="text-primary h-3.5 w-3.5" />
        <span className="text-ink text-xs font-semibold">研究对话</span>
        <div className="ml-auto flex items-center gap-0.5">
          <button
            aria-label="会话列表"
            onClick={() => setListOpen((v) => !v)}
            className="text-ink-secondary hover:bg-hover hover:text-ink rounded p-1.5"
          >
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", listOpen && "rotate-180")} />
          </button>
          <button
            aria-label="新对话"
            onClick={() => createConversation()}
            className="text-ink-secondary hover:bg-hover hover:text-ink rounded p-1.5"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          <button
            aria-label="收起对话"
            onClick={onCollapse}
            className="text-ink-secondary hover:bg-hover hover:text-ink rounded p-1.5"
          >
            <PanelLeftClose className="h-3.5 w-3.5" />
          </button>
        </div>
        {listOpen && (
          <div className="border-border bg-surface absolute top-full right-2 left-2 z-30 max-h-72 overflow-y-auto rounded-xl border shadow-lg">
            {metas.length === 0 && (
              <p className="text-ink-tertiary px-3 py-4 text-center text-xs">还没有对话</p>
            )}
            {metas.map((m) => (
              <div
                key={m.id}
                className={cn(
                  "hover:bg-hover group flex cursor-pointer items-center gap-2 px-3 py-2 text-xs",
                  m.id === activeId && "bg-primary/5",
                )}
                onClick={() => {
                  if (m.id !== activeId) switchConversation(m.id);
                  setListOpen(false);
                }}
              >
                <span className="text-ink min-w-0 flex-1 truncate">{m.title || "新对话"}</span>
                <span className="text-ink-tertiary shrink-0 text-[10px]">{timeAgo(m.updatedAt)}</span>
                <button
                  aria-label="删除对话"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteConversation(m.id);
                  }}
                  className="text-ink-tertiary hover:text-error hidden shrink-0 group-hover:block"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
      {/* 主体：Agent 对话（自包含组件，受全局上下文驱动） */}
      <div className="min-h-0 flex-1">
        <AgentPage />
      </div>
    </aside>
  );
}
