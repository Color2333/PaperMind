import { useGlobalTasks, TASK_CATEGORY_CONFIG, type ActiveTask } from "@/contexts/GlobalTaskContext";
import { Loader2, CheckCircle2, XCircle, ChevronRight, X, Clock, RotateCcw } from "lucide-react";
import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";

function getTaskConfig(task: ActiveTask) {
  const cat = task.category || "general";
  return TASK_CATEGORY_CONFIG[cat as keyof typeof TASK_CATEGORY_CONFIG] || TASK_CATEGORY_CONFIG.general;
}

function TaskItem({ task }: { task: ActiveTask }) {
  const cfg = getTaskConfig(task);
  const pct = task.progress_pct;

  return (
    <div className={cn("flex items-start gap-3 rounded-lg p-3 transition-colors hover:bg-border/30", cfg.bg)}>
      <span className="text-base mt-0.5">{cfg.icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-ink truncate">{task.title}</span>
          <div className="flex items-center gap-1 shrink-0">
            {task.finished ? (
              task.success
                ? <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                : <XCircle className="h-3.5 w-3.5 text-error" />
            ) : (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 mt-1">
          <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full", cfg.color, cfg.bg)}>{cfg.label}</span>
          <span className="text-[10px] text-ink-tertiary">
            {task.total > 0 ? `${task.current}/${task.total}` : ""}
          </span>
          {task.elapsed_seconds > 0 && (
            <span className="text-[10px] text-ink-tertiary flex items-center gap-0.5">
              <Clock className="h-2.5 w-2.5" />{task.elapsed_seconds}s
            </span>
          )}
        </div>

        {task.message && (
          <p className="text-[10px] text-ink-secondary mt-1 truncate">{task.message}</p>
        )}

        {!task.finished && task.total > 0 && (
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-border">
            <div
              className={cn("h-full rounded-full transition-all duration-500 ease-out",
                task.progress_pct > 80 ? "bg-success" : "bg-primary")}
              style={{ width: `${pct}%` }}
            />
          </div>
        )}

        {task.finished && !task.success && task.error && (
          <p className="text-[10px] text-error mt-1">{task.error}</p>
        )}
      </div>
    </div>
  );
}

export default function GlobalTaskBar() {
  const { tasks, activeTasks, hasRunning } = useGlobalTasks();
  const [expanded, setExpanded] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (tasks.length > 0) setVisible(true);
  }, [tasks.length]);

  const runningCount = activeTasks.length;
  const finishedCount = tasks.filter(t => t.finished).length;

  if (tasks.length === 0 || !visible) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className={cn(
          "fixed bottom-4 right-4 z-50 flex items-center gap-2 rounded-full px-4 py-2.5 shadow-xl transition-all duration-300",
          hasRunning
            ? "bg-gradient-to-r from-primary to-info text-white"
            : "bg-surface border border-border text-ink hover:bg-hover",
          expanded ? "rounded-br-none" : ""
        )}
      >
        {hasRunning ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm font-semibold">{runningCount} 个任务进行中</span>
            <ChevronRight className={cn("h-4 w-4 transition-transform", expanded ? "rotate-90" : "")} />
          </>
        ) : (
          <>
            <CheckCircle2 className="h-4 w-4 text-success" />
            <span className="text-sm font-medium">任务中心</span>
            {finishedCount > 0 && (
              <span className="ml-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-success/20 px-1.5 text-xs font-bold text-success">
                {finishedCount}
              </span>
            )}
            <ChevronRight className={cn("h-4 w-4 transition-transform", expanded ? "rotate-90" : "")} />
          </>
        )}
      </button>

      {expanded && (
        <div className={cn(
          "fixed bottom-16 right-4 z-50 w-96 max-h-[60vh] overflow-hidden rounded-2xl",
          "bg-surface border border-border shadow-2xl",
          "flex flex-col"
        )}>
          <div className="flex items-center justify-between border-b border-border px-4 py-3 bg-gradient-to-r from-primary/5 to-info/5">
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-ink">任务中心</span>
              {runningCount > 0 && (
                <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary/20 px-1.5 text-xs font-bold text-primary">
                  {runningCount}
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="rounded-lg p-1 text-ink-tertiary hover:bg-hover hover:text-ink transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {activeTasks.length > 0 && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-ink-tertiary mb-2 px-1">
                  进行中 ({activeTasks.length})
                </p>
                {activeTasks.map((task) => (
                  <TaskItem key={task.task_id} task={task} />
                ))}
              </div>
            )}

            {tasks.filter(t => t.finished).length > 0 && (
              <div className="pt-2 border-t border-border">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-ink-tertiary mb-2 px-1 flex items-center gap-1">
                  <RotateCcw className="h-3 w-3" />
                  最近完成 ({tasks.filter(t => t.finished).length})
                </p>
                {tasks.filter(t => t.finished).slice(0, 5).map((task) => (
                  <TaskItem key={task.task_id} task={task} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
