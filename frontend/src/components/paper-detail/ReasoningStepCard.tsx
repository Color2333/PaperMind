import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

function ReasoningStepCard({
  step,
  index,
}: {
  step: { step: string; thinking: string; conclusion: string };
  index: number;
}) {
  const [open, setOpen] = useState(index < 2);
  return (
    <div className="border-border bg-surface/50 rounded-xl border transition-all">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-purple-500/10 text-xs font-bold text-purple-500">
          {index + 1}
        </div>
        <span className="text-ink flex-1 text-sm font-medium">{step.step}</span>
        {open ? (
          <ChevronDown className="text-ink-tertiary h-4 w-4" />
        ) : (
          <ChevronRight className="text-ink-tertiary h-4 w-4" />
        )}
      </button>
      {open && (
        <div className="border-border space-y-3 border-t px-4 py-3">
          {step.thinking && (
            <div className="rounded-xl bg-purple-500/5 px-3 py-2.5 dark:bg-purple-500/10">
              <p className="mb-1 text-[10px] font-semibold tracking-wider text-purple-500 uppercase">
                思考过程
              </p>
              <p className="text-ink-secondary text-sm leading-relaxed whitespace-pre-wrap">
                {step.thinking}
              </p>
            </div>
          )}
          {step.conclusion && (
            <div className="rounded-xl bg-green-500/5 px-3 py-2.5 dark:bg-green-500/10">
              <p className="mb-1 text-[10px] font-semibold tracking-wider text-green-500 uppercase">
                结论
              </p>
              <p className="text-ink-secondary text-sm leading-relaxed">{step.conclusion}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ReasoningStepCard;
