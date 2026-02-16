/**
 * PaperMind - 主应用路由
 * @author Bamzc
 */
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Topics from "@/pages/Topics";
import Papers from "@/pages/Papers";
import PaperDetail from "@/pages/PaperDetail";
import GraphExplorer from "@/pages/GraphExplorer";
import Wiki from "@/pages/Wiki";
import Chat from "@/pages/Chat";
import DailyBrief from "@/pages/DailyBrief";
import Pipelines from "@/pages/Pipelines";
import Operations from "@/pages/Operations";
import Settings from "@/pages/Settings";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/topics" element={<Topics />} />
          <Route path="/papers" element={<Papers />} />
          <Route path="/papers/:id" element={<PaperDetail />} />
          <Route path="/graph" element={<GraphExplorer />} />
          <Route path="/wiki" element={<Wiki />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/brief" element={<DailyBrief />} />
          <Route path="/pipelines" element={<Pipelines />} />
          <Route path="/operations" element={<Operations />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
