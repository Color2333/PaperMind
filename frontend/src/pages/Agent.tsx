/**
 * Agent 对话页面 - 纯渲染壳，核心状态由 AgentSessionContext 管理
 * 切换页面不会丢失 SSE 流和进度
 * @author Bamzc
 */
import { useState, useRef, useEffect, useCallback, memo, lazy, Suspense } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";

// Markdown 含 katex，懒加载避免首屏拉取大 chunk
const Markdown = lazy(() => import("@/components/Markdown"));
import {
  Send,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertTriangle,
  Sparkles,
  Search,
  Download,
  BookOpen,
  Brain,
  FileText,
  Newspaper,
  ChevronDown,
  ChevronRight,
  Circle,
  Play,
  Square,
  X,
  PanelRightOpen,
  TrendingUp,
  Star,
  Hash,
  Copy,
  Check,
  RotateCcw,
  ArrowDown,
} from "lucide-react";
import { useAgentSession, type ChatItem, type StepItem } from "@/contexts/AgentSessionContext";
import { todayApi, type TodaySummary } from "@/services/api";

/* ========== 能力芯片（输入框上方始终显示） ========== */

interface Ability {
  icon: typeof Search;
  label: string;
  prefix: string;
  placeholder: string;
  direct?: boolean;
}

const ABILITIES: Ability[] = [
  { icon: Search, label: "搜索论文", prefix: "帮我搜索关于 ", placeholder: "输入搜索关键词..." },
  { icon: Download, label: "下载入库", prefix: "从 arXiv 下载关于 ", placeholder: "输入主题关键词..." },
  { icon: Brain, label: "知识问答", prefix: "基于知识库回答：", placeholder: "输入你的问题..." },
  { icon: FileText, label: "生成 Wiki", prefix: "帮我生成一篇关于 ", placeholder: "输入 Wiki 主题..." },
  { icon: Newspaper, label: "生成简报", prefix: "帮我生成今日的研究简报", placeholder: "", direct: true },
];

/* ========== 快捷建议（空状态卡片） ========== */

const SUGGESTIONS = [
  { icon: Search, label: "搜索调研", desc: "搜索特定领域论文", prompt: "帮我搜索关于 3D Gaussian Splatting 的最新论文" },
  { icon: Download, label: "下载论文", desc: "从 arXiv 获取并分析", prompt: "从 arXiv 下载最新的大语言模型相关论文，然后帮我粗读分析" },
  { icon: BookOpen, label: "论文分析", desc: "粗读/精读已有论文", prompt: "帮我分析库中最近的论文，先粗读再挑选重要的精读" },
  { icon: Brain, label: "知识问答", desc: "基于知识库回答", prompt: "基于知识库回答：什么是 attention mechanism？有哪些变体？" },
  { icon: FileText, label: "生成 Wiki", desc: "生成主题综述", prompt: "帮我生成一篇关于 Neural Radiance Fields 的 Wiki 综述" },
  { icon: Newspaper, label: "生成简报", desc: "生成研究日报", prompt: "帮我生成今日的研究简报" },
];

/* ========== 工具元数据 ========== */

const TOOL_META: Record<string, { icon: typeof Search; label: string }> = {
  search_papers: { icon: Search, label: "搜索论文" },
  get_paper_detail: { icon: FileText, label: "论文详情" },
  get_similar_papers: { icon: Search, label: "相似论文" },
  ask_knowledge_base: { icon: Brain, label: "知识问答" },
  get_citation_tree: { icon: Search, label: "引用树" },
  get_timeline: { icon: Search, label: "时间线" },
  list_topics: { icon: Search, label: "主题列表" },
  get_system_status: { icon: Search, label: "系统状态" },
  search_arxiv: { icon: Search, label: "搜索 arXiv" },
  ingest_arxiv: { icon: Download, label: "入库论文" },
  skim_paper: { icon: BookOpen, label: "粗读论文" },
  deep_read_paper: { icon: BookOpen, label: "精读论文" },
  embed_paper: { icon: Brain, label: "向量嵌入" },
  generate_wiki: { icon: FileText, label: "生成 Wiki" },
  generate_daily_brief: { icon: Newspaper, label: "生成简报" },
  manage_subscription: { icon: BookOpen, label: "订阅管理" },
};

function getToolMeta(name: string) {
  return TOOL_META[name] || { icon: Circle, label: name };
}

/* ========== 主组件 ========== */

export default function Agent() {
  const navigate = useNavigate();
  const {
    items, loading, pendingActions, confirmingActions, canvas,
    hasPendingConfirm, setCanvas, sendMessage, handleConfirm, handleReject, stopGeneration,
  } = useAgentSession();

  const [input, setInput] = useState("");
  const [activeAbility, setActiveAbility] = useState<Ability | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  /* ---- 滚动控制 ---- */
  const isAtBottomRef = useRef(true);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const handleScroll = useCallback(() => {
    const el = scrollAreaRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    isAtBottomRef.current = atBottom;
    setShowScrollBtn(!atBottom);
  }, []);

  const scrollRafRef = useRef<number | null>(null);
  const scrollToBottom = useCallback((force = false) => {
    if (!force && !isAtBottomRef.current) return;
    if (scrollRafRef.current) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    });
  }, []);

  useEffect(() => {
    scrollToBottom(loading);
  }, [items, loading, scrollToBottom]);

  // 有新的 pendingAction 时强制滚动到底部
  useEffect(() => {
    if (pendingActions.size > 0) {
      isAtBottomRef.current = true;
      requestAnimationFrame(() => endRef.current?.scrollIntoView({ behavior: "smooth" }));
    }
  }, [pendingActions]);

  const inputDisabled = loading || hasPendingConfirm;

  const handleAbilityClick = useCallback((ability: Ability) => {
    if (ability.direct) {
      isAtBottomRef.current = true;
      sendMessage(ability.prefix).catch(() => {});
      return;
    }
    setActiveAbility(ability);
    setInput(ability.prefix);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [sendMessage]);

  const handleSend = useCallback(async (text: string) => {
    const savedInput = text;
    isAtBottomRef.current = true;
    setInput("");
    setActiveAbility(null);
    try {
      await sendMessage(text);
    } catch {
      setInput(savedInput);
    }
  }, [sendMessage]);

  const handleConfirmAction = useCallback((actionId: string) => {
    isAtBottomRef.current = true;
    handleConfirm(actionId);
  }, [handleConfirm]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(input);
    }
    if (e.key === "Backspace" && activeAbility && input === activeAbility.prefix) {
      e.preventDefault();
      setActiveAbility(null);
      setInput("");
    }
  };

  return (
    <div className="flex h-full">
      {/* 主对话区域 */}
      <div className={cn("flex flex-1 flex-col transition-all", canvas ? "mr-0" : "")}>
        <div ref={scrollAreaRef} onScroll={handleScroll} className="relative flex-1 overflow-y-auto">
          {items.length === 0 ? (
            <EmptyState onSelect={(p) => handleSend(p)} />
          ) : (
            <div className="mx-auto max-w-3xl px-4 py-6">
              {items.map((item, idx) => {
                const retryFn = item.type === "error" ? (() => {
                  for (let i = idx - 1; i >= 0; i--) {
                    if (items[i].type === "user") {
                      handleSend(items[i].content);
                      return;
                    }
                  }
                }) : undefined;
                return (
                  <ChatBlock
                    key={item.id}
                    item={item}
                    isPending={item.actionId ? pendingActions.has(item.actionId) : false}
                    isConfirming={item.actionId ? confirmingActions.has(item.actionId) : false}
                    onConfirm={handleConfirmAction}
                    onReject={handleReject}
                    onOpenArtifact={(title, content, isHtml) => setCanvas({ title, markdown: content, isHtml })}
                    onRetry={retryFn}
                  />
                );
              })}
              {loading && items[items.length - 1]?.type !== "action_confirm" && (
                <div className="flex items-center gap-2 py-3 text-sm text-ink-tertiary">
                  <div className="flex gap-1">
                    <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:0ms]" />
                    <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:150ms]" />
                    <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:300ms]" />
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>
          )}

          {/* 滚到底部按钮 */}
          {showScrollBtn && items.length > 0 && (
            <button
              onClick={() => {
                isAtBottomRef.current = true;
                endRef.current?.scrollIntoView({ behavior: "smooth" });
              }}
              className="absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-ink-secondary shadow-lg transition-all hover:bg-hover hover:text-ink"
            >
              <ArrowDown className="h-3.5 w-3.5" />
              回到底部
            </button>
          )}
        </div>

        {/* 输入区域 */}
        <div className="border-t border-border bg-surface px-4 py-3">
          <div className="mx-auto max-w-3xl space-y-2">
            {hasPendingConfirm && (
              <div className="flex items-center gap-2 rounded-lg bg-warning-light px-3 py-2 text-xs text-warning">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>请先处理上方的确认请求，再继续对话</span>
              </div>
            )}

            {/* 能力芯片 */}
            {!hasPendingConfirm && (
              <div className="flex flex-wrap gap-1.5">
                {ABILITIES.map((ab) => {
                  const isActive = activeAbility?.label === ab.label;
                  return (
                    <button
                      key={ab.label}
                      onClick={() => isActive ? (setActiveAbility(null), setInput("")) : handleAbilityClick(ab)}
                      disabled={loading}
                      className={cn(
                        "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all",
                        isActive
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border bg-surface text-ink-secondary hover:border-primary/30 hover:bg-primary/5 hover:text-primary",
                        loading && "opacity-50",
                      )}
                    >
                      <ab.icon className="h-3 w-3" />
                      {ab.label}
                    </button>
                  );
                })}
              </div>
            )}

            {/* 输入框 */}
            <div className={cn(
              "flex items-end gap-3 rounded-2xl border border-border bg-page px-4 py-3 shadow-sm transition-all focus-within:border-primary/40 focus-within:shadow-md",
              hasPendingConfirm && "opacity-60",
            )}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  if (activeAbility && !e.target.value.startsWith(activeAbility.prefix)) {
                    setActiveAbility(null);
                  }
                }}
                onKeyDown={handleKeyDown}
                placeholder={
                  hasPendingConfirm ? "请先处理上方确认..."
                  : activeAbility ? activeAbility.placeholder
                  : "描述你的研究需求，或点击上方能力快捷使用..."
                }
                className="max-h-32 min-h-[40px] flex-1 resize-none bg-transparent text-sm text-ink placeholder:text-ink-placeholder focus:outline-none"
                rows={1}
                disabled={inputDisabled}
              />
              {loading ? (
                <button
                  aria-label="停止生成"
                  onClick={stopGeneration}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-error/90 text-white shadow-sm transition-all hover:bg-error"
                >
                  <Square className="h-3.5 w-3.5" />
                </button>
              ) : (
                <button
                  aria-label="发送消息"
                  onClick={() => handleSend(input)}
                  disabled={!input.trim() || inputDisabled}
                  className={cn(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-all",
                    input.trim() && !inputDisabled ? "bg-primary text-white shadow-sm hover:bg-primary-hover" : "bg-hover text-ink-tertiary",
                  )}
                >
                  <Send className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Canvas 面板 - 小屏全屏覆盖，大屏侧边 */}
      {canvas && (
        <div className="fixed inset-0 z-50 flex flex-col bg-surface lg:static lg:inset-auto lg:z-auto lg:h-full lg:w-[480px] lg:shrink-0 lg:border-l lg:border-border">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <PanelRightOpen className="h-4 w-4 text-ink-tertiary" />
              <span className="text-sm font-medium text-ink">{canvas.title}</span>
            </div>
            <button aria-label="关闭面板" onClick={() => setCanvas(null)} className="flex h-7 w-7 items-center justify-center rounded-lg text-ink-tertiary hover:bg-hover hover:text-ink">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div
            className="flex-1 overflow-y-auto px-6 py-4"
            onClick={(e) => {
              const card = (e.target as HTMLElement).closest<HTMLElement>("[data-paper-id]");
              if (card?.dataset.paperId) navigate(`/papers/${card.dataset.paperId}`);
            }}
          >
            {canvas.isHtml ? (
              <div
                className="prose-custom brief-html-preview brief-content"
                dangerouslySetInnerHTML={{ __html: canvas.markdown }}
              />
            ) : (
              <div className="prose-custom">
                <Suspense fallback={<div className="h-4 animate-pulse rounded bg-surface" />}>
                  <Markdown>{canvas.markdown}</Markdown>
                </Suspense>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ========== 空状态 ========== */

const EmptyState = memo(function EmptyState({ onSelect }: { onSelect: (p: string) => void }) {
  const navigate = useNavigate();
  const [today, setToday] = useState<TodaySummary | null>(null);

  useEffect(() => {
    todayApi.summary().then(setToday).catch(() => {});
  }, []);

  return (
    <div className="flex h-full flex-col items-center px-4 pt-12 pb-4 overflow-y-auto">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
        <Sparkles className="h-8 w-8 text-primary" />
      </div>
      <h2 className="mb-1 text-2xl font-bold text-ink">PaperMind Agent</h2>
      <p className="mb-6 max-w-lg text-center text-sm leading-relaxed text-ink-secondary">
        告诉我你的研究需求，我会自动规划执行步骤：搜索论文、下载、分析、生成综述。
      </p>

      {/* 今日研究速览 */}
      {today && (today.today_new > 0 || today.week_new > 0 || today.recommendations.length > 0) && (
        <div className="mb-6 w-full max-w-2xl space-y-4">
          {/* 统计卡片 */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-2xl font-bold text-primary">{today.total_papers}</div>
              <div className="text-xs text-ink-tertiary">论文总量</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-2xl font-bold text-emerald-500">{today.today_new}</div>
              <div className="text-xs text-ink-tertiary">今日新增</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-2xl font-bold text-amber-500">{today.week_new}</div>
              <div className="text-xs text-ink-tertiary">本周新增</div>
            </div>
          </div>

          {/* 为你推荐 */}
          {today.recommendations.length > 0 && (
            <div className="rounded-xl border border-border bg-surface p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
                <Star className="h-4 w-4 text-amber-500" />
                为你推荐
              </div>
              <div className="space-y-2">
                {today.recommendations.slice(0, 3).map((r) => (
                  <button
                    key={r.id}
                    onClick={() => navigate(`/papers/${r.id}`)}
                    className="flex w-full items-start gap-3 rounded-lg p-2.5 text-left transition-colors hover:bg-hover"
                  >
                    <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-bold text-primary">
                      {Math.round(r.similarity * 100)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium leading-snug text-ink line-clamp-1">{r.title}</div>
                      {r.title_zh && (
                        <div className="text-xs text-ink-tertiary line-clamp-1">{r.title_zh}</div>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 热点关键词 */}
          {today.hot_keywords.length > 0 && (
            <div className="rounded-xl border border-border bg-surface p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
                <TrendingUp className="h-4 w-4 text-rose-500" />
                本周热点
              </div>
              <div className="flex flex-wrap gap-2">
                {today.hot_keywords.map((kw) => (
                  <span
                    key={kw.keyword}
                    className="inline-flex items-center gap-1 rounded-md bg-primary/5 px-2.5 py-1 text-xs text-ink-secondary"
                  >
                    <Hash className="h-3 w-3 text-primary" />
                    {kw.keyword}
                    <span className="font-medium text-primary">({kw.count})</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 快捷建议 */}
      <div className="grid w-full max-w-2xl grid-cols-2 gap-3 md:grid-cols-3">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.label}
            onClick={() => onSelect(s.prompt)}
            className="group flex flex-col gap-1.5 rounded-2xl border border-border bg-surface p-4 text-left transition-all hover:border-primary/30 hover:shadow-md"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 transition-colors group-hover:bg-primary/20">
              <s.icon className="h-4.5 w-4.5 text-primary" />
            </div>
            <span className="text-sm font-medium text-ink">{s.label}</span>
            <span className="text-xs text-ink-tertiary">{s.desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
});

/* ========== 消息块 ========== */

const ChatBlock = memo(function ChatBlock({
  item, isPending, isConfirming, onConfirm, onReject, onOpenArtifact, onRetry,
}: {
  item: ChatItem; isPending: boolean; isConfirming: boolean;
  onConfirm: (id: string) => void; onReject: (id: string) => void;
  onOpenArtifact: (title: string, content: string, isHtml?: boolean) => void;
  onRetry?: () => void;
}) {
  switch (item.type) {
    case "user": return <UserMessage content={item.content} />;
    case "assistant": return <AssistantMessage content={item.content} streaming={!!item.streaming} />;
    case "step_group": return <StepGroupCard steps={item.steps || []} />;
    case "action_confirm": return <ActionConfirmCard actionId={item.actionId || ""} description={item.actionDescription || ""} tool={item.actionTool || ""} args={item.toolArgs} isPending={isPending} isConfirming={isConfirming} onConfirm={onConfirm} onReject={onReject} />;
    case "artifact": return <ArtifactCard title={item.artifactTitle || ""} content={item.artifactContent || ""} isHtml={item.artifactIsHtml} onOpen={() => onOpenArtifact(item.artifactTitle || "", item.artifactContent || "", item.artifactIsHtml)} />;
    case "error": return <ErrorCard content={item.content} onRetry={onRetry} />;
    default: return null;
  }
});

/**
 * 用户消息 - Claude 风格：无头像，右对齐浅色气泡
 */
const UserMessage = memo(function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end py-2">
      <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary/10 px-4 py-3 text-sm leading-relaxed text-ink">
        {content}
      </div>
    </div>
  );
});

/**
 * Assistant 消息 - Claude 风格：无头像，无气泡背景，纯文字流
 */
const AssistantMessage = memo(function AssistantMessage({
  content,
  streaming,
}: {
  content: string;
  streaming: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [content]);

  return (
    <div className="group py-2">
      {streaming ? (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
          {content}
          <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse rounded-full bg-primary" />
        </p>
      ) : (
        <>
          <div className="prose-custom text-sm leading-relaxed text-ink">
            <Suspense fallback={<div className="h-4 animate-pulse rounded bg-surface" />}>
              <Markdown>{content}</Markdown>
            </Suspense>
          </div>
          <div className="mt-1 flex opacity-0 transition-opacity group-hover:opacity-100">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-ink-tertiary transition-colors hover:bg-hover hover:text-ink-secondary"
            >
              {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
              {copied ? "已复制" : "复制"}
            </button>
          </div>
        </>
      )}
    </div>
  );
});

/* ========== 步骤组 ========== */

const StepGroupCard = memo(function StepGroupCard({ steps }: { steps: StepItem[] }) {
  return (
    <div className="py-2">
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex items-center gap-2 border-b border-border-light bg-page px-3.5 py-2">
          <Play className="h-3 w-3 text-primary" />
          <span className="text-xs font-medium text-ink-secondary">执行步骤</span>
          <span className="ml-auto text-[11px] text-ink-tertiary">
            {steps.filter((s) => s.status === "done").length}/{steps.length}
          </span>
        </div>
        <div className="divide-y divide-border-light">
          {steps.map((step, idx) => <StepRow key={step.id || idx} step={step} />)}
        </div>
      </div>
    </div>
  );
});

function StepRow({ step }: { step: StepItem }) {
  const isIngest = step.toolName === "ingest_arxiv";
  const autoExpand = isIngest && step.status === "running";
  const [expanded, setExpanded] = useState(false);
  const meta = getToolMeta(step.toolName);
  const Icon = meta.icon;
  const hasData = step.data && Object.keys(step.data).length > 0;
  const hasProgress = step.status === "running" && step.progressTotal && step.progressTotal > 0;
  const progressPct = hasProgress ? Math.round(((step.progressCurrent || 0) / step.progressTotal!) * 100) : 0;
  const showExpanded = expanded || autoExpand;

  const statusIcon =
    step.status === "running" ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
    : step.status === "done" ? <CheckCircle2 className="h-3.5 w-3.5 text-success" />
    : <XCircle className="h-3.5 w-3.5 text-error" />;

  return (
    <div>
      <button
        onClick={() => hasData && setExpanded(!expanded)}
        className={cn("flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-xs transition-colors", hasData && "hover:bg-hover")}
      >
        {statusIcon}
        <Icon className="h-3.5 w-3.5 shrink-0 text-ink-tertiary" />
        <span className="font-medium text-ink">{meta.label}</span>
        {step.toolArgs && Object.keys(step.toolArgs).length > 0 && !hasProgress && (
          <span className="truncate text-ink-tertiary">
            {Object.entries(step.toolArgs).slice(0, 2).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(" · ")}
          </span>
        )}
        {hasProgress && !isIngest && (
          <span className="truncate text-ink-secondary">{step.progressMessage}</span>
        )}
        {step.summary && <span className={cn("ml-auto shrink-0 font-medium", step.success ? "text-success" : "text-error")}>{step.summary}</span>}
        {hasData && <span className="ml-1 shrink-0 text-ink-tertiary">{showExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}</span>}
      </button>

      {/* 入库进度面板 - 独立的可视化区域 */}
      {isIngest && hasProgress && (
        <div className="mx-3.5 mb-2.5 overflow-hidden rounded-lg border border-primary/20 bg-primary/5">
          <div className="flex items-center gap-2 px-3 py-2">
            <div className="relative h-8 w-8 shrink-0">
              <svg className="h-8 w-8 -rotate-90" viewBox="0 0 32 32">
                <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="3" className="text-border" />
                <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="3" className="text-primary transition-all duration-500" strokeDasharray={`${progressPct * 0.8168} 81.68`} strokeLinecap="round" />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold text-primary">{progressPct}%</span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[11px] font-medium text-ink">{step.progressMessage}</p>
              <p className="text-[10px] text-ink-tertiary">{step.progressCurrent ?? 0} / {step.progressTotal ?? 0} 篇</p>
            </div>
            <Loader2 className="h-4 w-4 animate-spin text-primary/60" />
          </div>
          <div className="h-1 bg-border/50">
            <div className="h-full bg-primary transition-all duration-500 ease-out" style={{ width: `${progressPct}%` }} />
          </div>
        </div>
      )}

      {/* 非入库工具的简单进度条 */}
      {!isIngest && hasProgress && (
        <div className="mx-3.5 mb-2 h-1.5 overflow-hidden rounded-full bg-border">
          <div className="h-full rounded-full bg-primary transition-all duration-300 ease-out" style={{ width: `${progressPct}%` }} />
        </div>
      )}

      {showExpanded && step.data && (
        <div className="border-t border-border-light bg-page px-3.5 py-2.5">
          <StepDataView data={step.data} toolName={step.toolName} />
        </div>
      )}
    </div>
  );
}

/**
 * 论文列表卡片（search_papers / search_arxiv 共用）
 */
const PaperListView = memo(function PaperListView({
  papers, label,
}: {
  papers: Array<Record<string, unknown>>; label: string;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-medium text-ink-secondary">{label}</p>
      <div className="max-h-56 space-y-1 overflow-y-auto">
        {papers.slice(0, 30).map((p, i) => (
          <div key={i} className="flex items-start gap-2 rounded-lg bg-surface px-2.5 py-2 text-[11px] transition-colors hover:bg-hover">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <p className="font-medium leading-snug text-ink">{String(p.title ?? "")}</p>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-ink-tertiary">
                {p.arxiv_id ? <span className="font-mono">{String(p.arxiv_id)}</span> : null}
                {p.publication_date ? <span>{String(p.publication_date)}</span> : null}
                {p.read_status ? <span className="rounded bg-primary/10 px-1 py-0.5 text-primary">{String(p.read_status)}</span> : null}
              </div>
              {Array.isArray(p.authors) && (p.authors as string[]).length > 0 && (
                <p className="mt-0.5 truncate text-[10px] text-ink-tertiary">{(p.authors as string[]).slice(0, 3).join(", ")}{(p.authors as string[]).length > 3 ? " ..." : ""}</p>
              )}
              {Array.isArray(p.categories) && (p.categories as string[]).length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {(p.categories as string[]).slice(0, 3).map((c) => (
                    <span key={c} className="rounded bg-hover px-1.5 py-0.5 text-[9px] text-ink-tertiary">{c}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

/**
 * 入库结果卡片
 */
const IngestResultView = memo(function IngestResultView({ data }: { data: Record<string, unknown> }) {
  const total = Number(data.total ?? 0);
  const embedded = Number(data.embedded ?? 0);
  const skimmed = Number(data.skimmed ?? 0);
  const topic = String(data.topic ?? "");
  const ingested = Array.isArray(data.ingested) ? data.ingested as Array<Record<string, unknown>> : [];
  const failed = Array.isArray(data.failed) ? data.failed as Array<Record<string, unknown>> : [];
  const suggestSub = !!data.suggest_subscribe;

  return (
    <div className="space-y-2.5">
      {/* 统计条 */}
      <div className="grid grid-cols-4 gap-2">
        {[
          { label: "入库", value: total, color: "text-primary", bg: "bg-primary/10" },
          { label: "向量化", value: embedded, color: "text-success", bg: "bg-success/10" },
          { label: "粗读", value: skimmed, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-500/10" },
          { label: "失败", value: failed.length, color: failed.length > 0 ? "text-error" : "text-ink-tertiary", bg: failed.length > 0 ? "bg-error/10" : "bg-hover" },
        ].map((s) => (
          <div key={s.label} className={cn("flex flex-col items-center rounded-lg py-2", s.bg)}>
            <span className={cn("text-base font-bold", s.color)}>{s.value}</span>
            <span className="text-[10px] text-ink-tertiary">{s.label}</span>
          </div>
        ))}
      </div>

      {topic && (
        <div className="flex items-center gap-1.5 text-[11px]">
          <Hash className="h-3 w-3 text-primary" />
          <span className="text-ink-secondary">主题：</span>
          <span className="rounded-md bg-primary/10 px-1.5 py-0.5 font-medium text-primary">{topic}</span>
          {suggestSub && <span className="rounded bg-warning-light px-1.5 py-0.5 text-[10px] text-warning">新主题，建议订阅</span>}
        </div>
      )}

      {/* 入库论文列表 */}
      {ingested.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-success">已入库 ({ingested.length})</p>
          <div className="max-h-32 space-y-0.5 overflow-y-auto">
            {ingested.map((p, i) => (
              <div key={i} className="flex items-center gap-1.5 rounded px-2 py-1 text-[11px]">
                <CheckCircle2 className="h-3 w-3 shrink-0 text-success" />
                <span className="truncate text-ink">{String(p.title ?? p.arxiv_id ?? "")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 失败列表 */}
      {failed.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-error">失败 ({failed.length})</p>
          <div className="max-h-24 space-y-0.5 overflow-y-auto">
            {failed.map((p, i) => (
              <div key={i} className="flex items-center gap-1.5 rounded bg-error/5 px-2 py-1 text-[11px]">
                <XCircle className="h-3 w-3 shrink-0 text-error" />
                <span className="truncate text-ink">{String(p.title ?? p.arxiv_id ?? "")}</span>
                {p.error ? <span className="ml-auto shrink-0 text-[10px] text-error">{String(p.error).slice(0, 40)}</span> : null}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

/* ========== arXiv 候选论文选择器 ========== */

const QUERY_TO_CATEGORIES: Record<string, string[]> = {
  "graphics": ["cs.GR"], "rendering": ["cs.GR", "cs.CV"], "vision": ["cs.CV"],
  "nlp": ["cs.CL"], "language": ["cs.CL"], "robot": ["cs.RO"], "learning": ["cs.LG", "cs.AI"],
  "neural": ["cs.LG", "cs.CV", "cs.AI"], "3d": ["cs.GR", "cs.CV"], "image": ["cs.CV"],
  "audio": ["cs.SD", "eess.AS"], "speech": ["cs.CL", "cs.SD"], "security": ["cs.CR"],
  "network": ["cs.NI"], "database": ["cs.DB"], "attention": ["cs.LG", "cs.CL"],
  "transformer": ["cs.LG", "cs.CL"], "diffusion": ["cs.CV", "cs.LG"],
  "gaussian": ["cs.GR", "cs.CV"], "nerf": ["cs.GR", "cs.CV"], "reconstruction": ["cs.GR", "cs.CV"],
  "detection": ["cs.CV"], "segmentation": ["cs.CV"], "generation": ["cs.CV", "cs.LG"],
  "llm": ["cs.CL", "cs.AI"], "agent": ["cs.AI", "cs.CL"], "rl": ["cs.LG", "cs.AI"],
  "reinforcement": ["cs.LG", "cs.AI"], "optimization": ["math.OC", "cs.LG"],
};

function inferRelevantCategories(query: string): Set<string> {
  const qLower = query.toLowerCase();
  const cats = new Set<string>();
  for (const [kw, kwCats] of Object.entries(QUERY_TO_CATEGORIES)) {
    if (qLower.includes(kw)) kwCats.forEach(c => cats.add(c));
  }
  return cats;
}

function isRelevantCandidate(cats: string[], relevantCats: Set<string>): boolean {
  if (relevantCats.size === 0) return true;
  return cats.some(c => relevantCats.has(c));
}

function ArxivCandidateSelector({ candidates, query }: {
  candidates: Array<Record<string, unknown>>;
  query: string;
}) {
  const { sendMessage, loading } = useAgentSession();
  const relevantCats = inferRelevantCategories(query);

  const [selected, setSelected] = useState<Set<string>>(() => {
    if (relevantCats.size === 0) return new Set(candidates.map(c => String(c.arxiv_id ?? "")));
    const relevant = new Set<string>();
    for (const c of candidates) {
      const cats = Array.isArray(c.categories) ? (c.categories as string[]) : [];
      if (isRelevantCandidate(cats, relevantCats)) relevant.add(String(c.arxiv_id ?? ""));
    }
    return relevant.size > 0 ? relevant : new Set(candidates.map(c => String(c.arxiv_id ?? "")));
  });
  const [submitted, setSubmitted] = useState(false);
  const allSelected = selected.size === candidates.length;
  const relevantCount = relevantCats.size > 0
    ? candidates.filter(c => isRelevantCandidate(Array.isArray(c.categories) ? (c.categories as string[]) : [], relevantCats)).length
    : candidates.length;

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const selectRelevant = () => {
    const relevant = new Set<string>();
    for (const c of candidates) {
      const cats = Array.isArray(c.categories) ? (c.categories as string[]) : [];
      if (isRelevantCandidate(cats, relevantCats)) relevant.add(String(c.arxiv_id ?? ""));
    }
    setSelected(relevant);
  };

  const handleSubmit = () => {
    if (selected.size === 0 || submitted) return;
    setSubmitted(true);
    const ids = Array.from(selected).join(", ");
    sendMessage(`请将以下论文入库：${ids}`).catch(() => { setSubmitted(false); });
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium text-ink-secondary">
          {candidates.length} 篇候选论文
          {relevantCats.size > 0 && relevantCount < candidates.length && (
            <span className="ml-1 text-success">（{relevantCount} 篇高相关）</span>
          )}
        </p>
        <div className="flex items-center gap-1.5">
          {relevantCats.size > 0 && relevantCount < candidates.length && (
            <button
              onClick={selectRelevant}
              className="rounded-md px-2 py-0.5 text-[10px] font-medium text-success hover:bg-success/10 transition-colors"
            >
              仅选相关
            </button>
          )}
          <button
            onClick={() => setSelected(allSelected ? new Set() : new Set(candidates.map(c => String(c.arxiv_id ?? ""))))}
            className="rounded-md px-2 py-0.5 text-[10px] font-medium text-primary hover:bg-primary/10 transition-colors"
          >
            {allSelected ? "取消全选" : "全选"}
          </button>
          <span className="text-[10px] text-ink-tertiary">已选 {selected.size}/{candidates.length}</span>
        </div>
      </div>
      <div className="max-h-64 space-y-1 overflow-y-auto">
        {candidates.map((p, i) => {
          const aid = String(p.arxiv_id ?? "");
          const isChecked = selected.has(aid);
          const cats = Array.isArray(p.categories) ? (p.categories as string[]) : [];
          const isRelevant = isRelevantCandidate(cats, relevantCats);
          return (
            <label key={aid || i} className={cn(
              "flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-[11px] cursor-pointer transition-colors",
              isChecked ? "bg-primary/5 border border-primary/20" : "bg-surface hover:bg-hover border border-transparent",
              !isRelevant && relevantCats.size > 0 && "opacity-60",
            )}>
              <input
                type="checkbox"
                checked={isChecked}
                onChange={() => toggle(aid)}
                disabled={submitted}
                className="mt-1 h-3.5 w-3.5 rounded border-border text-primary focus:ring-primary/20 shrink-0"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-1.5">
                  <p className="font-medium leading-snug text-ink flex-1">{String(p.title ?? "")}</p>
                  {isRelevant && relevantCats.size > 0 && (
                    <span className="shrink-0 rounded bg-success/10 px-1.5 py-0.5 text-[9px] font-medium text-success">相关</span>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-ink-tertiary">
                  {p.arxiv_id ? <span className="font-mono">{aid}</span> : null}
                  {p.publication_date ? <span>{String(p.publication_date)}</span> : null}
                  {cats.length > 0 && cats.slice(0, 3).map(c => (
                    <span key={c} className={cn(
                      "rounded px-1 py-px text-[9px] font-mono",
                      relevantCats.has(c) ? "bg-primary/10 text-primary" : "bg-ink/5 text-ink-tertiary",
                    )}>{c}</span>
                  ))}
                </div>
                {Array.isArray(p.authors) && (p.authors as string[]).length > 0 && (
                  <p className="mt-0.5 truncate text-[10px] text-ink-tertiary">{(p.authors as string[]).slice(0, 3).join(", ")}</p>
                )}
              </div>
            </label>
          );
        })}
      </div>
      {!submitted ? (
        <button
          onClick={handleSubmit}
          disabled={selected.size === 0 || loading}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-primary-hover disabled:opacity-50"
        >
          <Download className="h-4 w-4" />
          入库选中 ({selected.size} 篇)
        </button>
      ) : (
        <div className="flex items-center justify-center gap-2 rounded-xl bg-primary/10 px-4 py-2.5 text-sm font-medium text-primary">
          <Loader2 className="h-4 w-4 animate-spin" />
          已发送请求，等待确认后开始入库…
        </div>
      )}
    </div>
  );
}

const StepDataView = memo(function StepDataView({ data, toolName }: { data: Record<string, unknown>; toolName: string }) {
  const navigate = useNavigate();

  if (toolName === "search_papers" && Array.isArray(data.papers)) {
    return <PaperListView papers={data.papers as Array<Record<string, unknown>>} label={`找到 ${(data.papers as unknown[]).length} 篇论文`} />;
  }
  if (toolName === "search_arxiv" && Array.isArray(data.candidates)) {
    return <ArxivCandidateSelector candidates={data.candidates as Array<Record<string, unknown>>} query={String(data.query ?? "")} />;
  }
  if (toolName === "ingest_arxiv" && data.total !== undefined) {
    return <IngestResultView data={data} />;
  }
  if (toolName === "get_system_status") {
    return (
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "论文", value: data.paper_count, color: "text-primary" },
          { label: "已向量化", value: data.embedded_count, color: "text-success" },
          { label: "主题", value: data.topic_count, color: "text-blue-600 dark:text-blue-400" },
        ].map((s) => (
          <div key={s.label} className="flex flex-col items-center rounded-lg bg-surface py-2">
            <span className={cn("text-base font-bold", s.color)}>{String(s.value ?? 0)}</span>
            <span className="text-[10px] text-ink-tertiary">{s.label}</span>
          </div>
        ))}
      </div>
    );
  }
  /* ask_knowledge_base — Markdown 答案 + 引用论文 */
  if (toolName === "ask_knowledge_base" && data.markdown) {
    const evidence = Array.isArray(data.evidence) ? (data.evidence as Array<Record<string, unknown>>) : [];
    const rounds = data.rounds as number | undefined;
    return (
      <div className="space-y-2">
        {rounds && rounds > 1 && (
          <div className="flex items-center gap-1.5 text-[10px] text-primary">
            <TrendingUp className="h-3 w-3" />
            <span>经过 {rounds} 轮迭代检索优化</span>
          </div>
        )}
        <div className="prose prose-sm dark:prose-invert max-w-none text-[12px] leading-relaxed">
          <Suspense fallback={<div className="h-4 animate-pulse rounded bg-surface" />}>
            <Markdown>{String(data.markdown)}</Markdown>
          </Suspense>
        </div>
        {evidence.length > 0 && (
          <div className="border-t border-border-light pt-2">
            <p className="mb-1 text-[10px] font-medium text-ink-tertiary">引用 {evidence.length} 篇论文</p>
            <div className="flex flex-wrap gap-1">
              {evidence.slice(0, 8).map((e, i) => (
                <button
                  key={i}
                  onClick={() => e.paper_id && navigate(`/papers/${String(e.paper_id)}`)}
                  className="rounded bg-surface px-1.5 py-0.5 text-[9px] text-ink-secondary hover:bg-hover hover:text-primary transition-colors truncate max-w-[200px]"
                  title={String(e.title ?? "")}
                >
                  {String(e.title ?? "").slice(0, 40)}{String(e.title ?? "").length > 40 ? "..." : ""}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }
  /* list_topics — 主题列表 */
  if (toolName === "list_topics" && Array.isArray(data.topics)) {
    const topics = data.topics as Array<Record<string, unknown>>;
    return (
      <div className="space-y-1">
        {topics.map((t, i) => (
          <div key={i} className="flex items-center gap-2 rounded-lg bg-surface px-2.5 py-1.5 text-[11px]">
            <Hash className="h-3 w-3 text-primary shrink-0" />
            <span className="font-medium text-ink">{String(t.name ?? "")}</span>
            {t.paper_count !== undefined && <span className="text-ink-tertiary">{String(t.paper_count)} 篇</span>}
            {t.enabled !== undefined && (
              <span className={cn("ml-auto rounded px-1.5 py-0.5 text-[9px]", t.enabled ? "bg-success/10 text-success" : "bg-ink/5 text-ink-tertiary")}>
                {t.enabled ? "已订阅" : "未订阅"}
              </span>
            )}
          </div>
        ))}
      </div>
    );
  }
  /* get_timeline — 时间线 */
  if (toolName === "get_timeline" && Array.isArray(data.timeline)) {
    const items = data.timeline as Array<Record<string, unknown>>;
    return (
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {items.map((p, i) => (
          <button
            key={i}
            onClick={() => p.paper_id && navigate(`/papers/${String(p.paper_id)}`)}
            className="flex items-center gap-2 w-full text-left rounded-lg bg-surface px-2.5 py-1.5 text-[11px] hover:bg-hover transition-colors"
          >
            <span className="shrink-0 font-mono text-[10px] text-primary">{String(p.year ?? "?")}</span>
            <span className="truncate text-ink">{String(p.title ?? "")}</span>
          </button>
        ))}
      </div>
    );
  }
  /* get_similar_papers — 相似论文 */
  if (toolName === "get_similar_papers") {
    const items = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : [];
    const ids = Array.isArray(data.similar_ids) ? (data.similar_ids as string[]) : [];
    if (items.length > 0) {
      return (
        <div className="space-y-1">
          {items.map((p, i) => (
            <button
              key={i}
              onClick={() => p.id && navigate(`/papers/${String(p.id)}`)}
              className="flex items-center gap-2 w-full text-left rounded-lg bg-surface px-2.5 py-1.5 text-[11px] hover:bg-hover transition-colors"
            >
              <Star className="h-3 w-3 text-amber-500 shrink-0" />
              <span className="truncate text-ink">{String(p.title ?? "")}</span>
            </button>
          ))}
        </div>
      );
    }
    if (ids.length > 0) {
      return <p className="text-[11px] text-ink-secondary">找到 {ids.length} 篇相似论文</p>;
    }
  }
  /* get_citation_tree — 引用树统计 */
  if (toolName === "get_citation_tree" && data.nodes) {
    const nodes = Array.isArray(data.nodes) ? data.nodes.length : 0;
    const edges = Array.isArray(data.edges) ? data.edges.length : 0;
    return (
      <div className="flex items-center gap-3 text-[11px]">
        <span className="font-medium text-ink">{nodes} 个节点</span>
        <span className="text-ink-tertiary">{edges} 条引用关系</span>
      </div>
    );
  }
  /* suggest_keywords — 关键词建议 */
  if (toolName === "suggest_keywords" && Array.isArray(data.suggestions)) {
    const suggestions = data.suggestions as Array<Record<string, unknown>>;
    return (
      <div className="space-y-1.5">
        {suggestions.map((s, i) => (
          <div key={i} className="rounded-lg bg-surface px-2.5 py-2 text-[11px]">
            <p className="font-medium text-ink">{String(s.name ?? "")}</p>
            <p className="mt-0.5 font-mono text-[10px] text-primary">{String(s.query ?? "")}</p>
            {s.reason !== undefined && <p className="mt-0.5 text-[10px] text-ink-tertiary">{String(s.reason)}</p>}
          </div>
        ))}
      </div>
    );
  }
  /* skim_paper / deep_read_paper — 报告摘要 */
  if ((toolName === "skim_paper" || toolName === "deep_read_paper") && data.one_liner) {
    return (
      <div className="text-[11px]">
        <p className="font-medium text-ink">{String(data.one_liner)}</p>
        {data.novelty !== undefined && <p className="mt-1 text-ink-secondary"><span className="font-medium">创新点:</span> {String(data.novelty)}</p>}
        {data.methodology !== undefined && <p className="mt-0.5 text-ink-secondary"><span className="font-medium">方法:</span> {String(data.methodology)}</p>}
      </div>
    );
  }
  /* reasoning_analysis — 推理链 */
  if (toolName === "reasoning_analysis" && data.reasoning_steps) {
    const steps = Array.isArray(data.reasoning_steps) ? (data.reasoning_steps as Array<Record<string, unknown>>) : [];
    return (
      <div className="space-y-1.5 max-h-48 overflow-y-auto">
        {steps.slice(0, 6).map((s, i) => (
          <div key={i} className="rounded-lg bg-surface px-2.5 py-1.5 text-[11px]">
            <p className="font-medium text-ink">{String(s.step_name ?? s.claim ?? `步骤 ${i + 1}`)}</p>
            {s.evidence !== undefined && <p className="mt-0.5 text-[10px] text-ink-tertiary truncate">{String(s.evidence)}</p>}
          </div>
        ))}
      </div>
    );
  }
  /* analyze_figures — 图表列表 */
  if (toolName === "analyze_figures" && Array.isArray(data.figures)) {
    const figs = data.figures as Array<Record<string, unknown>>;
    return (
      <div className="space-y-1">
        {figs.map((f, i) => (
          <div key={i} className="rounded-lg bg-surface px-2.5 py-1.5 text-[11px]">
            <p className="font-medium text-ink">{String(f.figure_type ?? "图表")} — p.{String(f.page ?? "?")}</p>
            <p className="mt-0.5 text-[10px] text-ink-tertiary truncate">{String(f.description ?? f.analysis ?? "")}</p>
          </div>
        ))}
      </div>
    );
  }
  /* identify_research_gaps — 研究空白 */
  if (toolName === "identify_research_gaps" && data.analysis) {
    const analysis = data.analysis as Record<string, unknown>;
    const gaps = Array.isArray(analysis.research_gaps) ? (analysis.research_gaps as Array<Record<string, unknown>>) : [];
    return (
      <div className="space-y-1.5">
        {gaps.slice(0, 5).map((g, i) => (
          <div key={i} className="rounded-lg bg-surface px-2.5 py-1.5 text-[11px]">
            <p className="font-medium text-ink">{String(g.gap_title ?? g.title ?? `空白 ${i + 1}`)}</p>
            <p className="mt-0.5 text-[10px] text-ink-tertiary truncate">{String(g.description ?? g.evidence ?? "")}</p>
          </div>
        ))}
      </div>
    );
  }
  /* get_paper_detail — 论文详情卡片 */
  if (toolName === "get_paper_detail" && data.title) {
    return (
      <div className="text-[11px]">
        <button
          onClick={() => data.id && navigate(`/papers/${String(data.id)}`)}
          className="font-medium text-primary hover:underline"
        >
          {String(data.title)}
        </button>
        {data.abstract_zh !== undefined && <p className="mt-1 text-ink-secondary line-clamp-3">{String(data.abstract_zh)}</p>}
        <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-ink-tertiary">
          {data.arxiv_id ? <span className="font-mono">{String(data.arxiv_id)}</span> : null}
          {data.read_status ? <span>{String(data.read_status)}</span> : null}
        </div>
      </div>
    );
  }
  /* writing_assist — 写作助手结果 */
  if (toolName === "writing_assist" && data.content) {
    return (
      <div className="prose prose-sm dark:prose-invert max-w-none text-[12px] max-h-48 overflow-y-auto">
        <Suspense fallback={<div className="h-4 animate-pulse rounded bg-surface" />}>
          <Markdown>{String(data.content)}</Markdown>
        </Suspense>
      </div>
    );
  }
  /* 兜底：原始 JSON */
  return (
    <pre className="max-h-40 overflow-auto rounded-lg bg-surface p-2.5 text-[11px] text-ink-secondary">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
});

/* ========== 确认卡片 ========== */

const ActionConfirmCard = memo(function ActionConfirmCard({
  actionId, description, tool, args, isPending, isConfirming, onConfirm, onReject,
}: {
  actionId: string; description: string; tool: string; args?: Record<string, unknown>;
  isPending: boolean; isConfirming: boolean; onConfirm: (id: string) => void; onReject: (id: string) => void;
}) {
  const meta = getToolMeta(tool);
  const Icon = meta.icon;
  return (
    <div className="py-2">
      <div className={cn(
        "overflow-hidden rounded-xl border bg-surface transition-all",
        isPending ? "border-warning/60 shadow-md shadow-warning/10 animate-[confirm-glow_2s_ease-in-out_infinite]" : "border-border",
      )}>
        <div className={cn(
          "flex items-center gap-2 px-3.5 py-2.5",
          isPending ? "bg-warning-light" : "bg-page",
        )}>
          <AlertTriangle className={cn("h-3.5 w-3.5", isPending ? "text-warning animate-pulse" : "text-ink-tertiary")} />
          <span className="text-xs font-semibold text-ink">{isPending ? "⚠️ 需要你的确认" : "已处理"}</span>
        </div>
        <div className="space-y-3 px-3.5 py-3">
          <div className="flex items-start gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warning-light">
              <Icon className="h-4 w-4 text-warning" />
            </div>
            <div>
              <p className="text-sm font-medium text-ink">{description}</p>
              {args && Object.keys(args).length > 0 && (
                <div className="mt-1.5 rounded-lg bg-page px-2.5 py-1.5">
                  {Object.entries(args).map(([k, v]) => (
                    <div key={k} className="flex gap-1.5 text-[11px]">
                      <span className="font-medium text-ink-secondary">{k}:</span>
                      <span className="text-ink-tertiary">{typeof v === "string" ? v : JSON.stringify(v)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          {isPending && (
            <div className="flex gap-2">
              <button onClick={() => onConfirm(actionId)} disabled={isConfirming} className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary py-2 text-xs font-medium text-white transition-all hover:bg-primary-hover disabled:opacity-50">
                {isConfirming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                确认执行
              </button>
              <button onClick={() => onReject(actionId)} disabled={isConfirming} className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-border bg-surface py-2 text-xs font-medium text-ink-secondary transition-all hover:bg-hover disabled:opacity-50">
                <XCircle className="h-3.5 w-3.5" />
                跳过
              </button>
            </div>
          )}
          {!isPending && (
            <div className="flex items-center gap-1 text-[11px] text-success">
              <CheckCircle2 className="h-3 w-3" />
              已处理
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

const ErrorCard = memo(function ErrorCard({ content, onRetry }: { content: string; onRetry?: () => void }) {
  return (
    <div className="py-2">
      <div className="flex items-start gap-2 rounded-xl border border-error/30 bg-error-light px-3.5 py-2.5">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-error" />
        <p className="flex-1 text-sm text-error">{content}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-error transition-colors hover:bg-error/10"
          >
            <RotateCcw className="h-3 w-3" />
            重试
          </button>
        )}
      </div>
    </div>
  );
});

/* ========== 嵌入式内容卡片（Artifact） ========== */

const ArtifactCard = memo(function ArtifactCard({
  title, content, isHtml, onOpen,
}: {
  title: string; content: string; isHtml?: boolean; onOpen: () => void;
}) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const isWiki = !isHtml;
  const iconColor = isWiki ? "text-primary" : "text-amber-500";
  const borderColor = isWiki ? "border-primary/30" : "border-amber-400/30";
  const bgAccent = isWiki ? "bg-primary/5" : "bg-amber-50 dark:bg-amber-900/10";
  const IconComp = isWiki ? FileText : Newspaper;

  const preview = (isHtml
    ? content.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ")
    : content.replace(/[#*_`\[\]()>-]/g, "").replace(/\s+/g, " ")
  ).trim().slice(0, 200);

  return (
    <div className="py-2">
      <div className={cn("overflow-hidden rounded-xl border transition-all", borderColor, "bg-surface hover:shadow-md")}>
        <button
          onClick={onOpen}
          className={cn("flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-hover", bgAccent)}
        >
          <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", isWiki ? "bg-primary/10" : "bg-amber-100 dark:bg-amber-900/20")}>
            <IconComp className={cn("h-4.5 w-4.5", iconColor)} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-ink">{title}</p>
            <p className="mt-0.5 truncate text-xs text-ink-tertiary">{preview}...</p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <span className="rounded-md bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
              点击查看
            </span>
            <PanelRightOpen className="h-4 w-4 text-ink-tertiary" />
          </div>
        </button>

        <div className="flex items-center gap-1 border-t border-border-light px-4 py-1.5">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-[11px] text-ink-tertiary hover:text-ink-secondary"
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {expanded ? "收起预览" : "展开预览"}
          </button>
        </div>

        {expanded && (
          <div
            className="max-h-80 overflow-y-auto border-t border-border-light px-5 py-4"
            onClick={(e) => {
              const card = (e.target as HTMLElement).closest<HTMLElement>("[data-paper-id]");
              if (card?.dataset.paperId) navigate(`/papers/${card.dataset.paperId}`);
            }}
          >
            {isHtml ? (
              <div
                className="prose-custom brief-html-preview brief-content text-sm"
                dangerouslySetInnerHTML={{ __html: content }}
              />
            ) : (
              <div className="prose-custom text-sm">
                <Suspense fallback={<div className="h-4 animate-pulse rounded bg-surface" />}>
                  <Markdown>{content}</Markdown>
                </Suspense>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
