/**
 * 全局任务进度条 — 固定在页面底部
 * @author Bamzc
 */
import { useGlobalTasks, type ActiveTask } from "@/contexts/GlobalTaskContext";
import { Loader2, CheckCircle2, XCircle, ChevronUp, ChevronDown } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

function TaskItem({ task }: { task: ActiveTask }) {
  const pct = task.progress_pct;
  return (
    <div className="flex items-center gap-3 px-4 py-2 text-xs">
      {task.finished ? (
        task.success ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" />
        ) : (
          <XCircle className="h-3.5 w-3.5 shrink-0 text-error" />
        )
      ) : (
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between">
          <span className="truncate font-medium text-ink">{task.title}</span>
          <span className="ml-2 shrink-0 text-[10px] text-ink-tertiary">
            {task.total > 0 ? `${task.current}/${task.total}` : ""}
            {task.finished ? "" : ` · ${task.elapsed_seconds}s`}
          </span>
        </div>
        {task.message && (
          <p className="truncate text-[10px] text-ink-tertiary">{task.message}</p>
        )}
        {!task.finished && task.total > 0 && (
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-border">
            <div
              className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default function GlobalTaskBar() {
  const { tasks, hasRunning } = useGlobalTasks();
  const [expanded, setExpanded] = useState(false);

  if (tasks.length === 0) return null;

  const running = tasks.filter((t) => !t.finished);
  const recent = tasks.filter((t) => t.finished).slice(0, 3);
  const displayTasks = expanded ? [...running, ...recent] : running.slice(0, 1);

  if (running.length === 0 && !expanded) return null;

  return (
    <div className={cn(
      "fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-surface/95 backdrop-blur-sm",
      "lg:left-[240px]",
      "transition-all duration-300",
    )}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-1.5 text-[10px] font-medium text-ink-secondary hover:bg-hover transition-colors"
      >
        <div className="flex items-center gap-2">
          {hasRunning && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
          <span>
            {running.length > 0
              ? `${running.length} 个任务进行中`
              : "任务已完成"}
          </span>
        </div>
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
      </button>
      {displayTasks.length > 0 && (
        <div className="max-h-48 divide-y divide-border-light overflow-y-auto">
          {displayTasks.map((t) => (
            <TaskItem key={t.task_id} task={t} />
          ))}
        </div>
      )}
    </div>
  );
}
