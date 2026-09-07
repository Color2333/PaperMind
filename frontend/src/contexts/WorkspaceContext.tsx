/**
 * 工作区上下文：对话 ↔ 主区 双向联动的事实源。
 * - agent 调 pm_get_paper → 主区自动切到该论文工作桌；
 * - 用户在主区浏览（PaperDetail 等）→ 对话输入区显示上下文 chip，
 *   发消息时附带当前视图（agent 感知用户在看什么）。
 * @author Color2333
 */
import { createContext, useContext, useMemo, useState } from "react";

export interface WorkspaceState {
  /** 主区当前路由（papers/graph/...） */
  view: string;
  /** 主区正在查看的论文（PaperDetail 挂载/agent 工具联动时设置） */
  activePaperId: string | null;
  activePaperTitle: string | null;
  /** 来源：user=用户手动浏览；agent=agent 工具联动 */
  source: "user" | "agent";
  setView: (view: string) => void;
  openPaper: (id: string, title: string | null, source: "user" | "agent") => void;
  /** 发消息时附带的上下文提示（无上下文返回 null） */
  contextHint: string | null;
}

const Ctx = createContext<WorkspaceState | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [view, setView] = useState("papers");
  const [activePaperId, setActivePaperId] = useState<string | null>(null);
  const [activePaperTitle, setActivePaperTitle] = useState<string | null>(null);
  const [source, setSource] = useState<"user" | "agent">("user");

  const value = useMemo<WorkspaceState>(
    () => ({
      view,
      activePaperId,
      activePaperTitle,
      source,
      setView: (v) => {
        setView(v);
        if (v !== "paper") {
          setActivePaperId(null);
          setActivePaperTitle(null);
        }
      },
      openPaper: (id, title, src) => {
        setActivePaperId(id);
        setActivePaperTitle(title);
        setSource(src);
        setView("paper");
      },
      contextHint:
        activePaperId && source === "user"
          ? `（用户当前正在查看论文 ${activePaperTitle ?? ""} [${activePaperId}]，相关操作可直接对该论文执行）`
          : null,
    }),
    [view, activePaperId, activePaperTitle, source],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkspace(): WorkspaceState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useWorkspace must be inside WorkspaceProvider");
  return ctx;
}
