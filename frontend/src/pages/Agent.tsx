/**
 * Agent 对话页面 - 纯渲染壳，核心状态由 AgentSessionContext 管理
 * 切换页面不会丢失 SSE 流和进度
 * @author Bamzc
 */
import { useState, useRef, useEffect, useCallback, memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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
} from "lucide-react";
import { useAgentSession, type ChatItem, type StepItem } from "@/contexts/AgentSessionContext";

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
  ingest_arxiv: { icon: Download, label: "下载论文" },
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

  const handleScroll = useCallback(() => {
    const el = scrollAreaRef.current;
    if (!el) return;
    isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
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
        <div ref={scrollAreaRef} onScroll={handleScroll} className="flex-1 overflow-y-auto">
          {items.length === 0 ? (
            <EmptyState onSelect={(p) => handleSend(p)} />
          ) : (
            <div className="mx-auto max-w-3xl px-4 py-6">
              {items.map((item) => (
                <ChatBlock
                  key={item.id}
                  item={item}
                  isPending={item.actionId ? pendingActions.has(item.actionId) : false}
                  isConfirming={item.actionId ? confirmingActions.has(item.actionId) : false}
                  onConfirm={handleConfirmAction}
                  onReject={handleReject}
                  onOpenArtifact={(title, content, isHtml) => setCanvas({ title, markdown: content, isHtml })}
                />
              ))}
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

      {/* Canvas 侧面板 */}
      {canvas && (
        <div className="flex h-full w-[480px] shrink-0 flex-col border-l border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <PanelRightOpen className="h-4 w-4 text-ink-tertiary" />
              <span className="text-sm font-medium text-ink">{canvas.title}</span>
            </div>
            <button onClick={() => setCanvas(null)} className="flex h-7 w-7 items-center justify-center rounded-lg text-ink-tertiary hover:bg-hover hover:text-ink">
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
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{canvas.markdown}</ReactMarkdown>
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
  return (
    <div className="flex h-full flex-col items-center justify-center px-4">
      <div className="mb-8 flex h-20 w-20 items-center justify-center rounded-3xl bg-primary/10">
        <Sparkles className="h-10 w-10 text-primary" />
      </div>
      <h2 className="mb-2 text-2xl font-bold text-ink">PaperMind Agent</h2>
      <p className="mb-10 max-w-lg text-center text-sm leading-relaxed text-ink-secondary">
        告诉我你的研究需求，我会自动规划执行步骤：搜索论文、下载、分析、生成综述。
      </p>
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
  item, isPending, isConfirming, onConfirm, onReject, onOpenArtifact,
}: {
  item: ChatItem; isPending: boolean; isConfirming: boolean;
  onConfirm: (id: string) => void; onReject: (id: string) => void;
  onOpenArtifact: (title: string, content: string, isHtml?: boolean) => void;
}) {
  switch (item.type) {
    case "user": return <UserMessage content={item.content} />;
    case "assistant": return <AssistantMessage content={item.content} streaming={!!item.streaming} />;
    case "step_group": return <StepGroupCard steps={item.steps || []} />;
    case "action_confirm": return <ActionConfirmCard actionId={item.actionId || ""} description={item.actionDescription || ""} tool={item.actionTool || ""} args={item.toolArgs} isPending={isPending} isConfirming={isConfirming} onConfirm={onConfirm} onReject={onReject} />;
    case "artifact": return <ArtifactCard title={item.artifactTitle || ""} content={item.artifactContent || ""} isHtml={item.artifactIsHtml} onOpen={() => onOpenArtifact(item.artifactTitle || "", item.artifactContent || "", item.artifactIsHtml)} />;
    case "error": return <ErrorCard content={item.content} />;
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
  return (
    <div className="py-2">
      {streaming ? (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
          {content}
          <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse rounded-full bg-primary" />
        </p>
      ) : (
        <div className="prose-custom text-sm leading-relaxed text-ink">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
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

const ErrorCard = memo(function ErrorCard({ content }: { content: string }) {
  return (
    <div className="py-2">
      <div className="flex items-start gap-2 rounded-xl border border-error/30 bg-error-light px-3.5 py-2.5">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-error" />
        <p className="text-sm text-error">{content}</p>
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
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
