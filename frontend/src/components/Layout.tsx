import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Activity } from "lucide-react";
import Sidebar from "./Sidebar";
import ChatPane from "./ChatPane";
import TaskRail from "./TaskRail";
import { WorkspaceProvider, useWorkspace } from "@/contexts/WorkspaceContext";
import { ConversationProvider } from "@/contexts/ConversationContext";
import { AgentSessionProvider } from "@/contexts/AgentSessionContext";
import { GlobalTaskProvider } from "@/contexts/GlobalTaskContext";
import GlobalTaskBar from "./GlobalTaskBar";


function CenterPane() {
  const { setView } = useWorkspace();
  const { pathname } = useLocation();
  useEffect(() => {
    setView(pathname.replace(/^\//, "").split("/")[0] || "papers");
  }, [pathname, setView]);
  // 路由切换过渡：key=pathname 触发淡入
  return (
    <div key={pathname} className="page-enter min-h-full">
      <Outlet />
    </div>
  );
}


export default function Layout() {
  const { pathname } = useLocation();
  // 知识工作台（选项 A）：[侧栏][对话窄栏][知识工作区][任务右栏]
  const [chatOpen, setChatOpen] = useState(true);
  const [railOpen, setRailOpen] = useState(false); // 默认收起（VS Code 协议：面板按需展开）
  const isDevice = pathname === "/device";
  if (isDevice) {
    return (
      <ConversationProvider>
        <AgentSessionProvider>
          <GlobalTaskProvider>
            <div className="min-h-screen bg-page">
              <Outlet />
            </div>
          </GlobalTaskProvider>
        </AgentSessionProvider>
      </ConversationProvider>
    );
  }

  return (
    <WorkspaceProvider>
      <ConversationProvider>
        <AgentSessionProvider>
        <GlobalTaskProvider>
          <div className="bg-page flex h-screen overflow-hidden">
            <Sidebar />
            {chatOpen && <ChatPane onCollapse={() => setChatOpen(false)} />}
            <main className="min-w-0 flex-1 overflow-y-auto">
              <CenterPane />
            </main>
            {railOpen ? (
              <TaskRail onClose={() => setRailOpen(false)} />
            ) : (
              <button
                onClick={() => setRailOpen(true)}
                aria-label="展开任务流"
                className="border-border bg-surface text-ink-secondary hover:text-ink hidden h-full w-9 shrink-0 items-center justify-center border-l xl:flex"
              >
                <Activity className="h-4 w-4" />
              </button>
            )}
          </div>
          <GlobalTaskBar />
        </GlobalTaskProvider>
      </AgentSessionProvider>
      </ConversationProvider>
    </WorkspaceProvider>
  );
}
