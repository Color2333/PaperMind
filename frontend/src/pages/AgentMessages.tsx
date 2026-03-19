import { memo, useState, useCallback, useRef, useEffect, useMemo, lazy, Suspense } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { CheckCircle2, XCircle, Loader2, Play, ChevronDown, ChevronRight } from "lucide-react";
const ReactMarkdown = lazy(() => import("react-markdown"));
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { type StepItem } from "@/contexts/AgentSessionContext";
import { getToolMeta, StepDataView } from "./AgentSteps";

const UserMessage = memo(function UserMessage({
  content,
  messageId,
}: {
  content: string;
  messageId?: string;
}) {
  return (
    <div className="flex justify-end py-2" data-message-id={messageId}>
      <div className="bg-primary/10 text-ink max-w-[80%] rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed">
        {content}
      </div>
    </div>
  );
});

const AssistantMessage = memo(function AssistantMessage({
  content,
  streaming,
}: {
  content: string;
  streaming: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const contentRef = useRef(content);

  useEffect(() => {
    contentRef.current = content;
  }, [content]);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(contentRef.current).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, []);

  const markdownKey = streaming ? content : `static_${content}`;
  const markdownContent = useMemo(() => content, [markdownKey]);

  return (
    <div className="group py-2">
      <div className="prose-custom text-ink text-sm leading-relaxed">
        <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}>
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
            {markdownContent}
          </ReactMarkdown>
        </Suspense>
      </div>
      {streaming && (
        <span className="bg-primary ml-0.5 inline-block h-4 w-[2px] animate-pulse rounded-full" />
      )}
      {!streaming && (
        <div className="mt-1 flex opacity-0 transition-opacity group-hover:opacity-100">
          <button
            type="button"
            onClick={handleCopy}
            className="text-ink-tertiary hover:bg-hover hover:text-ink-secondary flex items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-colors"
          >
            {copied ? "已复制" : "复制"}
          </button>
        </div>
      )}
    </div>
  );
});

const StepGroupCard = memo(function StepGroupCard({ steps }: { steps: StepItem[] }) {
  return (
    <div className="py-2">
      <div className="border-border bg-surface overflow-hidden rounded-xl border">
        <div className="border-border-light bg-page flex items-center gap-2 border-b px-3.5 py-2">
          <Play className="text-primary h-3 w-3" />
          <span className="text-ink-secondary text-xs font-medium">执行步骤</span>
          <span className="text-ink-tertiary ml-auto text-[11px]">
            {steps.filter((s) => s.status === "done").length}/{steps.length}
          </span>
        </div>
        <div className="divide-border-light divide-y">
          {steps.map((step, idx) => (
            <StepRow key={step.id || idx} step={step} />
          ))}
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
  const progressPct = hasProgress
    ? Math.round(((step.progressCurrent || 0) / step.progressTotal!) * 100)
    : 0;
  const showExpanded = expanded || autoExpand;

  const statusIcon =
    step.status === "running" ? (
      <Loader2 className="text-primary h-3.5 w-3.5 animate-spin" />
    ) : step.status === "done" ? (
      <CheckCircle2 className="text-success h-3.5 w-3.5" />
    ) : (
      <XCircle className="text-error h-3.5 w-3.5" />
    );

  return (
    <div>
      <button
        type="button"
        onClick={() => hasData && setExpanded(!expanded)}
        className={cn(
          "flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-xs transition-colors",
          hasData && "hover:bg-hover"
        )}
      >
        {statusIcon}
        <Icon className="text-ink-tertiary h-3.5 w-3.5 shrink-0" />
        <span className="text-ink font-medium">{meta.label}</span>
        {step.toolArgs && Object.keys(step.toolArgs).length > 0 && !hasProgress && (
          <span className="text-ink-tertiary truncate">
            {Object.entries(step.toolArgs)
              .slice(0, 2)
              .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
              .join(" · ")}
          </span>
        )}
        {hasProgress && !isIngest && (
          <span className="text-ink-secondary truncate">{step.progressMessage}</span>
        )}
        {step.summary && (
          <span
            className={cn(
              "ml-auto shrink-0 font-medium",
              step.success ? "text-success" : "text-error"
            )}
          >
            {step.summary}
          </span>
        )}
        {hasData && (
          <span className="text-ink-tertiary ml-1 shrink-0">
            {showExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </span>
        )}
      </button>

      {isIngest && hasProgress && (
        <div className="border-primary/20 bg-primary/5 mx-3.5 mb-2.5 overflow-hidden rounded-lg border">
          <div className="flex items-center gap-2 px-3 py-2">
            <div className="relative h-8 w-8 shrink-0">
              <svg className="h-8 w-8 -rotate-90" viewBox="0 0 32 32">
                <circle
                  cx="16"
                  cy="16"
                  r="13"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  className="text-border"
                />
                <circle
                  cx="16"
                  cy="16"
                  r="13"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  className="text-primary transition-all duration-500"
                  strokeDasharray={`${progressPct * 0.8168} 81.68`}
                  strokeLinecap="round"
                />
              </svg>
              <span className="text-primary absolute inset-0 flex items-center justify-center text-[9px] font-bold">
                {progressPct}%
              </span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-ink truncate text-[11px] font-medium">{step.progressMessage}</p>
              <p className="text-ink-tertiary text-[10px]">
                {step.progressCurrent ?? 0} / {step.progressTotal ?? 0} 篇
              </p>
            </div>
            <Loader2 className="text-primary/60 h-4 w-4 animate-spin" />
          </div>
          <div className="bg-border/50 h-1">
            <div
              className="bg-primary h-full transition-all duration-500 ease-out"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      )}

      {!isIngest && hasProgress && (
        <div className="bg-border mx-3.5 mb-2 h-1.5 overflow-hidden rounded-full">
          <div
            className="bg-primary h-full rounded-full transition-all duration-300 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}

      {showExpanded && step.data && (
        <div className="border-border-light bg-page border-t px-3.5 py-2.5">
          <StepDataView data={step.data} toolName={step.toolName} />
        </div>
      )}
    </div>
  );
}

export { UserMessage, AssistantMessage, StepGroupCard, StepRow };
