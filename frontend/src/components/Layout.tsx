/**
 * 主布局组件
 * @author Bamzc
 */
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import { ConversationProvider } from "@/contexts/ConversationContext";
import { AgentSessionProvider } from "@/contexts/AgentSessionContext";
import { GlobalTaskProvider } from "@/contexts/GlobalTaskContext";

export default function Layout() {
  const { pathname } = useLocation();
  const isFullscreen = pathname === "/";

  return (
    <ConversationProvider>
      <AgentSessionProvider>
        <GlobalTaskProvider>
          <div className="min-h-screen bg-page">
            <Sidebar />
            {isFullscreen ? (
              <main className="flex h-screen flex-col lg:ml-[240px]">
                <Outlet />
              </main>
            ) : (
              <main className="min-h-screen pt-14 lg:ml-[240px] lg:pt-0">
                <div className="mx-auto max-w-6xl px-4 py-6 lg:px-8 lg:py-8">
                  <Outlet />
                </div>
              </main>
            )}
          </div>
        </GlobalTaskProvider>
      </AgentSessionProvider>
    </ConversationProvider>
  );
}
