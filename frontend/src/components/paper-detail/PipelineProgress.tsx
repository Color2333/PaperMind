import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { SKIM_STAGES, DEEP_STAGES, FIGURE_STAGES } from "./stages";

/* ================================================================
 * PipelineProgress — 内联进度面板
 * ================================================================ */

function PipelineProgress({
  type,
  onCancel,
}: {
  type: "skim" | "deep" | "figure" | "reasoning" | "embed";
  onCancel?: () => void;
}) {
  const [progress, setProgress] = useState(0);
  const [stageIdx, setStageIdx] = useState(0);

  const stages =
    type === "skim"
      ? SKIM_STAGES
      : type === "deep"
        ? DEEP_STAGES
        : type === "figure"
          ? FIGURE_STAGES
          : type === "reasoning"
            ? ["构建推理链...", "分析方法推导...", "评估影响力...", "生成评估报告..."]
            : ["计算向量嵌入..."];

  const estimate =
    type === "skim"
      ? "10-20 秒"
      : type === "deep"
        ? "30-60 秒"
        : type === "figure"
          ? "30-60 秒"
          : type === "reasoning"
            ? "20-40 秒"
            : "5-10 秒";

  useEffect(() => {
    const progressTimer = setInterval(() => {
      setProgress((p) => (p < 90 ? p + Math.random() * 3 + 0.5 : p));
    }, 500);
    const stageTimer = setInterval(
      () => {
        setStageIdx((i) => (i < stages.length - 1 ? i + 1 : i));
      },
      type === "embed" ? 3000 : 8000
    );
    return () => {
      clearInterval(progressTimer);
      clearInterval(stageTimer);
    };
  }, [stages.length, type]);

  return (
    <div className="animate-fade-in border-primary/20 bg-primary/5 dark:bg-primary/10 rounded-2xl border p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center">
            <svg className="h-10 w-10 -rotate-90" viewBox="0 0 36 36">
              <circle
                cx="18"
                cy="18"
                r="15.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="text-border"
              />
              <circle
                cx="18"
                cy="18"
                r="15.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                className="text-primary transition-all duration-500"
                strokeDasharray={`${progress} ${100 - progress}`}
                strokeLinecap="round"
              />
            </svg>
            <span className="text-primary absolute text-[10px] font-bold">
              {Math.round(progress)}%
            </span>
          </div>
          <div>
            <p className="text-ink text-sm font-medium">{stages[stageIdx]}</p>
            <p className="text-ink-tertiary text-xs">预计 {estimate}</p>
          </div>
        </div>
        {onCancel && (
          <button
            onClick={onCancel}
            className="text-ink-tertiary hover:bg-hover hover:text-ink flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs transition-colors"
          >
            <X className="h-3.5 w-3.5" /> 取消
          </button>
        )}
      </div>
      <div className="bg-border mt-3 h-1.5 overflow-hidden rounded-full">
        <div
          className="from-primary h-full rounded-full bg-gradient-to-r to-blue-400 transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

export default PipelineProgress;
