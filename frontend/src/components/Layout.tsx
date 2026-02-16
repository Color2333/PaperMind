/**
 * 主布局组件
 * @author Bamzc
 */
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import { ConversationProvider } from "@/contexts/ConversationContext";
import { AgentSessionProvider } from "@/contexts/AgentSessionContext";

export default function Layout() {
  const { pathname } = useLocation();
  const isFullscreen = pathname === "/";

  return (
    <ConversationProvider>
      <AgentSessionProvider>
        <div className="min-h-screen bg-page">
          <Sidebar />
          {isFullscreen ? (
            <main className="ml-[240px] flex h-screen flex-col">
              <Outlet />
            </main>
          ) : (
            <main className="ml-[240px] min-h-screen">
              <div className="mx-auto max-w-6xl px-8 py-8">
                <Outlet />
              </div>
            </main>
          )}
        </div>
      </AgentSessionProvider>
    </ConversationProvider>
  );
}
