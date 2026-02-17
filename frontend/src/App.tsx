/**
 * PaperMind - 主应用路由（懒加载）
 * @author Bamzc
 */
import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "@/components/Layout";
import { Loader2 } from "lucide-react";

/* Agent 作为首页，不做懒加载，保证首屏速度 */
import AgentPage from "@/pages/Agent";

/* 其余页面全部懒加载，按需拆 chunk */
const Collect = lazy(() => import("@/pages/Collect"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Papers = lazy(() => import("@/pages/Papers"));
const PaperDetail = lazy(() => import("@/pages/PaperDetail"));
const GraphExplorer = lazy(() => import("@/pages/GraphExplorer"));
const Wiki = lazy(() => import("@/pages/Wiki"));
const DailyBrief = lazy(() => import("@/pages/DailyBrief"));
const Pipelines = lazy(() => import("@/pages/Pipelines"));
const Operations = lazy(() => import("@/pages/Operations"));
const Settings = lazy(() => import("@/pages/Settings"));

function PageFallback() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-ink-tertiary" />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<AgentPage />} />
          <Route path="/collect" element={<Suspense fallback={<PageFallback />}><Collect /></Suspense>} />
          <Route path="/dashboard" element={<Suspense fallback={<PageFallback />}><Dashboard /></Suspense>} />
          <Route path="/papers" element={<Suspense fallback={<PageFallback />}><Papers /></Suspense>} />
          <Route path="/papers/:id" element={<Suspense fallback={<PageFallback />}><PaperDetail /></Suspense>} />
          <Route path="/graph" element={<Suspense fallback={<PageFallback />}><GraphExplorer /></Suspense>} />
          <Route path="/wiki" element={<Suspense fallback={<PageFallback />}><Wiki /></Suspense>} />
          <Route path="/brief" element={<Suspense fallback={<PageFallback />}><DailyBrief /></Suspense>} />
          <Route path="/pipelines" element={<Suspense fallback={<PageFallback />}><Pipelines /></Suspense>} />
          <Route path="/operations" element={<Suspense fallback={<PageFallback />}><Operations /></Suspense>} />
          <Route path="/settings" element={<Suspense fallback={<PageFallback />}><Settings /></Suspense>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
