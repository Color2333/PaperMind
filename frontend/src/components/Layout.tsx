import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
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
  return <Outlet />;
}


export default function Layout() {
  const { pathname } = useLocation();
  // 知识工作台（选项 A）：[侧栏][对话窄栏][知识工作区][任务右栏]
  const [chatOpen, setChatOpen] = useState(true);
  const [railOpen, setRailOpen] = useState(true);
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
            {railOpen && <TaskRail onClose={() => setRailOpen(false)} />}
          </div>
          <GlobalTaskBar />
        </GlobalTaskProvider>
      </AgentSessionProvider>
      </ConversationProvider>
    </WorkspaceProvider>
  );
}
