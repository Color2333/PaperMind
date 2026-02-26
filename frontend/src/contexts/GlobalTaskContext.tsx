/**
 * 全局任务追踪 — 跨页面可见的实时任务进度
 * @author Bamzc
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import { useToast } from "@/contexts/ToastContext";

export interface ActiveTask {
  task_id: string;
  task_type: string;
  title: string;
  current: number;
  total: number;
  message: string;
  elapsed_seconds: number;
  progress_pct: number;
  finished: boolean;
  success: boolean;
  error: string | null;
}

interface GlobalTaskCtx {
  tasks: ActiveTask[];
  activeTasks: ActiveTask[];
  hasRunning: boolean;
}

const Ctx = createContext<GlobalTaskCtx>({ tasks: [], activeTasks: [], hasRunning: false });

import { tasksApi } from "@/services/api";

export function GlobalTaskProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<ActiveTask[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const previousTasksRef = useRef<Record<string, boolean>>({});
  const { toast } = useToast();

  const fetchTasks = useCallback(async () => {
    try {
      const data = await tasksApi.active();
      const newTasks = (data.tasks || []) as ActiveTask[];

      // 检测任务完成状态变化
      newTasks.forEach((task: ActiveTask) => {
        const previousState = previousTasksRef.current[task.task_id];
        const currentState = task.finished;

        // 如果之前未完成，现在完成了 → 触发通知
        if (previousState === false && currentState === true) {
          if (task.success) {
            toast("success", `✅ ${task.title} 完成！${task.message ? "\n" + task.message : "任务执行成功"}`);
          } else {
            toast("error", `❌ ${task.title} 失败！${task.error ? "\n" + task.error : task.message ? "\n" + task.message : "任务执行失败"}`);
          }
        }

        // 更新状态记录
        previousTasksRef.current[task.task_id] = currentState;
      });

      // 清理已删除的任务
      const currentTaskIds = new Set(newTasks.map((t: ActiveTask) => t.task_id));
      Object.keys(previousTasksRef.current).forEach((tid) => {
        if (!currentTaskIds.has(tid)) {
          delete previousTasksRef.current[tid];
        }
      });

      setTasks(newTasks);
    } catch {
      /* 静默失败，不影响主功能 */
    }
  }, [toast]);

  useEffect(() => {
    fetchTasks();
    intervalRef.current = setInterval(fetchTasks, 2000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchTasks]);

  const activeTasks = tasks.filter((t) => !t.finished);
  const hasRunning = activeTasks.length > 0;

  return (
    <Ctx.Provider value={{ tasks, activeTasks, hasRunning }}>
      {children}
    </Ctx.Provider>
  );
}

export function useGlobalTasks() {
  return useContext(Ctx);
}
