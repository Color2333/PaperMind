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

// 有任务运行时快速轮询，空闲时降速
const POLL_FAST = 2000;
const POLL_IDLE = 10000;

export function GlobalTaskProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<ActiveTask[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const previousTasksRef = useRef<Record<string, boolean>>({});
  const hasRunningRef = useRef(false);
  const { toast } = useToast();

  const fetchTasks = useCallback(async () => {
    try {
      const data = await tasksApi.active();
      const newTasks = (data.tasks || []) as ActiveTask[];

      newTasks.forEach((task: ActiveTask) => {
        const previousState = previousTasksRef.current[task.task_id];
        const currentState = task.finished;
        if (previousState === false && currentState === true) {
          if (task.success) {
            toast("success", `✅ ${task.title} 完成！${task.message ? "\n" + task.message : "任务执行成功"}`);
          } else {
            toast("error", `❌ ${task.title} 失败！${task.error ? "\n" + task.error : task.message ? "\n" + task.message : "任务执行失败"}`);
          }
        }
        previousTasksRef.current[task.task_id] = currentState;
      });

      const currentTaskIds = new Set(newTasks.map((t: ActiveTask) => t.task_id));
      Object.keys(previousTasksRef.current).forEach((tid) => {
        if (!currentTaskIds.has(tid)) delete previousTasksRef.current[tid];
      });

      setTasks(newTasks);

      // 动态调整轮询间隔：有运行中任务 2s，否则 10s
      const nowRunning = newTasks.some((t) => !t.finished);
      if (nowRunning !== hasRunningRef.current) {
        hasRunningRef.current = nowRunning;
        if (intervalRef.current) clearInterval(intervalRef.current);
        intervalRef.current = setInterval(fetchTasks, nowRunning ? POLL_FAST : POLL_IDLE);
      }
    } catch {
      /* 静默失败 */
    }
  }, [toast]);

  useEffect(() => {
    fetchTasks();
    intervalRef.current = setInterval(fetchTasks, POLL_IDLE);
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
