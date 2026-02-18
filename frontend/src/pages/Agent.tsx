/**
 * Agent 对话页面 - 纯渲染壳，核心状态由 AgentSessionContext 管理
 * 切换页面不会丢失 SSE 流和进度
 * @author Bamzc
 */
import { useState, useRef, useEffect, useCallback, memo } from "react";
import { useNavigate } from "react-router-dom";
import Markdown from "@/components/Markdown";
import { cn } from "@/lib/utils";
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
  const {
    items, loading, pendingActions, confirmingActions, canvas,
    hasPendingConfirm, setCanvas, sendMessage, handleConfirm, handleReject,
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

  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrollToBottom = useCallback(() => {
    if (!isAtBottomRef.current) return;
    if (scrollTimerRef.current) return;
    scrollTimerRef.current = setTimeout(() => {
      scrollTimerRef.current = null;
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 120);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [items, scrollToBottom]);

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
      sendMessage(ability.prefix);
      return;
    }
    setActiveAbility(ability);
    setInput(ability.prefix);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [sendMessage]);

  const handleSend = useCallback((text: string) => {
    isAtBottomRef.current = true;
    sendMessage(text);
    setInput("");
    setActiveAbility(null);
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
              <button
                aria-label="发送消息"
                onClick={() => handleSend(input)}
                disabled={!input.trim() || inputDisabled}
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-all",
                  input.trim() && !inputDisabled ? "bg-primary text-white shadow-sm hover:bg-primary-hover" : "bg-hover text-ink-tertiary",
                )}
              >
                {loading ? <Square className="h-3.5 w-3.5" /> : <Send className="h-4 w-4" />}
              </button>
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
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {canvas.isHtml ? (
              <div
                className="prose-custom brief-html-preview"
                dangerouslySetInnerHTML={{ __html: canvas.markdown }}
              />
            ) : (
              <div className="prose-custom">
                <Markdown>{canvas.markdown}</Markdown>
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
            <Markdown>{content}</Markdown>
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
  const [expanded, setExpanded] = useState(false);
  const meta = getToolMeta(step.toolName);
  const Icon = meta.icon;
  const hasData = step.data && Object.keys(step.data).length > 0;
  const hasProgress = step.status === "running" && step.progressTotal && step.progressTotal > 0;
  const progressPct = hasProgress ? Math.round(((step.progressCurrent || 0) / step.progressTotal!) * 100) : 0;

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
        {hasProgress && (
          <span className="truncate text-ink-secondary">{step.progressMessage}</span>
        )}
        {step.summary && <span className={cn("ml-auto shrink-0 font-medium", step.success ? "text-success" : "text-error")}>{step.summary}</span>}
        {hasData && <span className="ml-1 shrink-0 text-ink-tertiary">{expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}</span>}
      </button>
      {hasProgress && (
        <div className="mx-3.5 mb-2 h-1.5 overflow-hidden rounded-full bg-border">
          <div
            className="h-full rounded-full bg-primary transition-all duration-300 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}
      {expanded && step.data && (
        <div className="border-t border-border-light bg-page px-3.5 py-2.5">
          <StepDataView data={step.data} toolName={step.toolName} />
        </div>
      )}
    </div>
  );
}

const StepDataView = memo(function StepDataView({ data, toolName }: { data: Record<string, unknown>; toolName: string }) {
  if (toolName === "search_papers" && Array.isArray(data.papers)) {
    const papers = data.papers as Array<Record<string, unknown>>;
    return (
      <div className="space-y-1.5">
        <p className="text-[11px] font-medium text-ink-secondary">找到 {papers.length} 篇论文</p>
        <div className="max-h-48 space-y-1 overflow-y-auto">
          {papers.slice(0, 20).map((p, i) => (
            <div key={i} className="flex items-start gap-1.5 rounded-lg bg-surface px-2 py-1.5 text-[11px]">
              <span className="shrink-0 font-mono text-ink-tertiary">{i + 1}.</span>
              <div className="min-w-0">
                <p className="font-medium text-ink">{String(p.title ?? "")}</p>
                <p className="text-ink-tertiary">
                  {p.publication_date ? <span>{String(p.publication_date)} · </span> : null}
                  <span className="rounded bg-hover px-1">{String(p.read_status ?? "")}</span>
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }
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
          <div className="max-h-80 overflow-y-auto border-t border-border-light px-5 py-4">
            {isHtml ? (
              <div
                className="prose-custom brief-html-preview text-sm"
                dangerouslySetInnerHTML={{ __html: content }}
              />
            ) : (
              <div className="prose-custom text-sm">
                <Markdown>{content}</Markdown>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
