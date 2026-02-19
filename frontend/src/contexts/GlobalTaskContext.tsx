/**
 * 全局任务追踪 — 跨页面可见的实时任务进度
 * @author Bamzc
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";

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

const API_BASE = (() => {
  try {
    const m = (window as Record<string, unknown>).__PAPERMIND_API_PORT__;
    if (m) return `http://localhost:${m}`;
  } catch { /* ignore */ }
  return import.meta.env.VITE_API_BASE || "http://localhost:8000";
})();

export function GlobalTaskProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<ActiveTask[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/tasks/active`);
      if (!resp.ok) return;
      const data = await resp.json();
      setTasks(data.tasks || []);
    } catch {
      /* 静默失败，不影响主功能 */
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    intervalRef.current = setInterval(fetchTasks, 3000);
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
