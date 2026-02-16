/**
 * AI Chat - RAG 问答 (Claude 对话风格)
 * 覆盖 API: POST /rag/ask
 * @author Bamzc
 */
import { useState, useRef, useEffect } from "react";
import { Card, Button } from "@/components/ui";
import { ragApi } from "@/services/api";
import type { ChatMessage } from "@/types";
import { uid } from "@/lib/utils";
import {
  Send,
  Sparkles,
  User,
  BookOpen,
  Trash2,
} from "lucide-react";

export default function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async () => {
    const question = input.trim();
    if (!question || loading) return;

    const userMsg: ChatMessage = {
      id: uid(),
      role: "user",
      content: question,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await ragApi.ask({ question, top_k: 5 });
      const botMsg: ChatMessage = {
        id: uid(),
        role: "assistant",
        content: res.answer,
        cited_paper_ids: res.cited_paper_ids,
        evidence: res.evidence,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch (err) {
      const errorMsg: ChatMessage = {
        id: uid(),
        role: "assistant",
        content: `抱歉，查询时出现错误: ${err instanceof Error ? err.message : "未知错误"}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const clearChat = () => {
    setMessages([]);
  };

  return (
    <div className="animate-fade-in flex h-[calc(100vh-8rem)] flex-col">
      {/* 标题栏 */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink">AI Chat</h1>
          <p className="mt-1 text-sm text-ink-secondary">
            基于 RAG 的跨论文智能问答
          </p>
        </div>
        {messages.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 className="h-3.5 w-3.5" />}
            onClick={clearChat}
          >
            清空对话
          </Button>
        )}
      </div>

      {/* 消息区域 */}
      <div
        ref={scrollRef}
        className="flex-1 space-y-4 overflow-y-auto rounded-2xl border border-border bg-surface p-6"
      >
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center">
            <div className="rounded-2xl bg-primary-light p-4">
              <Sparkles className="h-8 w-8 text-primary" />
            </div>
            <h2 className="mt-4 text-lg font-semibold text-ink">
              PaperMind AI
            </h2>
            <p className="mt-2 max-w-md text-center text-sm text-ink-secondary">
              基于你收录的论文进行智能问答。
              支持跨文档检索，自动引用来源论文。
            </p>
            <div className="mt-6 grid max-w-lg gap-2">
              {[
                "这些论文中关于 Transformer 的主要创新是什么？",
                "有哪些论文讨论了模型压缩的方法？",
                "总结一下近期在多模态学习方面的进展",
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => setInput(q)}
                  className="rounded-xl border border-border bg-page px-4 py-3 text-left text-sm text-ink-secondary transition-colors hover:border-primary/30 hover:bg-hover hover:text-ink"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-3 animate-fade-in ${
                msg.role === "user" ? "justify-end" : ""
              }`}
            >
              {msg.role === "assistant" && (
                <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-light">
                  <Sparkles className="h-4 w-4 text-primary" />
                </div>
              )}
              <div
                className={`max-w-[75%] ${
                  msg.role === "user"
                    ? "rounded-2xl rounded-br-md bg-primary px-4 py-3 text-white"
                    : "space-y-2"
                }`}
              >
                {msg.role === "user" ? (
                  <p className="text-sm leading-relaxed">{msg.content}</p>
                ) : (
                  <>
                    <div className="rounded-2xl rounded-bl-md bg-page px-4 py-3">
                      <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
                        {msg.content}
                      </p>
                    </div>
                    {/* 引用论文 */}
                    {msg.cited_paper_ids && msg.cited_paper_ids.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 px-1">
                        {msg.cited_paper_ids.map((cid) => (
                          <span
                            key={cid}
                            className="inline-flex items-center gap-1 rounded-full bg-info-light px-2.5 py-1 text-xs text-info"
                          >
                            <BookOpen className="h-3 w-3" />
                            {cid.slice(0, 8)}...
                          </span>
                        ))}
                      </div>
                    )}
                    {/* Evidence */}
                    {msg.evidence && msg.evidence.length > 0 && (
                      <details className="px-1">
                        <summary className="cursor-pointer text-xs text-ink-tertiary hover:text-ink-secondary">
                          查看 {msg.evidence.length} 条证据
                        </summary>
                        <div className="mt-2 space-y-1.5">
                          {msg.evidence.map((ev, i) => (
                            <div
                              key={i}
                              className="rounded-lg bg-hover p-2.5 text-xs text-ink-secondary"
                            >
                              {JSON.stringify(ev, null, 2)}
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </>
                )}
              </div>
              {msg.role === "user" && (
                <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-hover">
                  <User className="h-4 w-4 text-ink-secondary" />
                </div>
              )}
            </div>
          ))
        )}

        {/* 加载中提示 */}
        {loading && (
          <div className="flex gap-3 animate-fade-in">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-light">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            <div className="rounded-2xl rounded-bl-md bg-page px-4 py-3">
              <div className="flex items-center gap-2">
                <div className="flex gap-1">
                  <span className="h-2 w-2 animate-pulse-soft rounded-full bg-primary" />
                  <span className="h-2 w-2 animate-pulse-soft rounded-full bg-primary [animation-delay:0.2s]" />
                  <span className="h-2 w-2 animate-pulse-soft rounded-full bg-primary [animation-delay:0.4s]" />
                </div>
                <span className="text-sm text-ink-secondary">正在思考...</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 输入区域 */}
      <div className="mt-4">
        <div className="flex items-end gap-3 rounded-2xl border border-border bg-surface p-3 shadow-sm transition-colors focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入你的问题..."
            rows={1}
            className="max-h-32 flex-1 resize-none bg-transparent text-sm text-ink placeholder:text-ink-placeholder focus:outline-none"
            style={{
              height: "auto",
              minHeight: "24px",
            }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement;
              target.style.height = "auto";
              target.style.height = `${Math.min(target.scrollHeight, 128)}px`;
            }}
          />
          <Button
            size="sm"
            onClick={handleSend}
            loading={loading}
            disabled={!input.trim()}
            className="shrink-0 rounded-xl"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="mt-2 text-center text-xs text-ink-tertiary">
          基于 RAG 检索增强生成，回答可能不完全准确，请以原始论文为准
        </p>
      </div>
    </div>
  );
}
