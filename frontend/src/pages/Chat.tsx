/**
 * AI Chat - RAG 问答 (Claude 对话风格)
 * 覆盖 API: POST /rag/ask
 * @author Color2333
 */
import { useState, useRef, useEffect } from "react";
import { Card, Button } from "@/components/ui";
import { ragApi } from "@/services/api";
import type { ChatMessage } from "@/types";
import { uid } from "@/lib/utils";
import { Send, Sparkles, User, BookOpen, Trash2 } from "lucide-react";

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
          <h1 className="text-ink text-2xl font-bold">AI Chat</h1>
          <p className="text-ink-secondary mt-1 text-sm">基于 RAG 的跨论文智能问答</p>
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
        className="border-border bg-surface flex-1 space-y-4 overflow-y-auto rounded-2xl border p-6"
      >
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center">
            <div className="bg-primary-light rounded-2xl p-4">
              <Sparkles className="text-primary h-8 w-8" />
            </div>
            <h2 className="text-ink mt-4 text-lg font-semibold">PaperMind AI</h2>
            <p className="text-ink-secondary mt-2 max-w-md text-center text-sm">
              基于你收录的论文进行智能问答。 支持跨文档检索，自动引用来源论文。
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
                  className="border-border bg-page text-ink-secondary hover:border-primary/30 hover:bg-hover hover:text-ink rounded-xl border px-4 py-3 text-left text-sm transition-colors"
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
              className={`animate-fade-in flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}
            >
              {msg.role === "assistant" && (
                <div className="bg-primary-light mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full">
                  <Sparkles className="text-primary h-4 w-4" />
                </div>
              )}
              <div
                className={`max-w-[75%] ${
                  msg.role === "user"
                    ? "bg-primary rounded-2xl rounded-br-md px-4 py-3 text-white"
                    : "space-y-2"
                }`}
              >
                {msg.role === "user" ? (
                  <p className="text-sm leading-relaxed">{msg.content}</p>
                ) : (
                  <>
                    <div className="bg-page rounded-2xl rounded-bl-md px-4 py-3">
                      <p className="text-ink text-sm leading-relaxed whitespace-pre-wrap">
                        {msg.content}
                      </p>
                    </div>
                    {/* 引用论文 */}
                    {msg.cited_paper_ids && msg.cited_paper_ids.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 px-1">
                        {msg.cited_paper_ids.map((cid) => (
                          <span
                            key={cid}
                            className="bg-info-light text-info inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs"
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
                        <summary className="text-ink-tertiary hover:text-ink-secondary cursor-pointer text-xs">
                          查看 {msg.evidence.length} 条证据
                        </summary>
                        <div className="mt-2 space-y-1.5">
                          {msg.evidence.map((ev, i) => (
                            <div
                              key={i}
                              className="bg-hover text-ink-secondary rounded-lg p-2.5 text-xs"
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
                <div className="bg-hover mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full">
                  <User className="text-ink-secondary h-4 w-4" />
                </div>
              )}
            </div>
          ))
        )}

        {/* 加载中提示 */}
        {loading && (
          <div className="animate-fade-in flex gap-3">
            <div className="bg-primary-light flex h-8 w-8 shrink-0 items-center justify-center rounded-full">
              <Sparkles className="text-primary h-4 w-4" />
            </div>
            <div className="bg-page rounded-2xl rounded-bl-md px-4 py-3">
              <div className="flex items-center gap-2">
                <div className="flex gap-1">
                  <span className="animate-pulse-soft bg-primary h-2 w-2 rounded-full" />
                  <span className="animate-pulse-soft bg-primary h-2 w-2 rounded-full [animation-delay:0.2s]" />
                  <span className="animate-pulse-soft bg-primary h-2 w-2 rounded-full [animation-delay:0.4s]" />
                </div>
                <span className="text-ink-secondary text-sm">正在思考...</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 输入区域 */}
      <div className="mt-4">
        <div className="border-border bg-surface focus-within:border-primary/40 focus-within:ring-primary/10 flex items-end gap-3 rounded-2xl border p-3 shadow-sm transition-colors focus-within:ring-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入你的问题..."
            rows={1}
            className="text-ink placeholder:text-ink-placeholder max-h-32 flex-1 resize-none bg-transparent text-sm focus:outline-none"
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
        <p className="text-ink-tertiary mt-2 text-center text-xs">
          基于 RAG 检索增强生成，回答可能不完全准确，请以原始论文为准
        </p>
      </div>
    </div>
  );
}
