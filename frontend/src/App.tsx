/**
 * PaperMind - 主应用路由（懒加载）
 * @author Bamzc
 */
import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ToastProvider } from "@/contexts/ToastContext";
import ToastContainer from "@/components/Toast";
import { Loader2, FileQuestion } from "lucide-react";

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
const EmailSettings = lazy(() => import("@/pages/EmailSettings"));
const Writing = lazy(() => import("@/pages/Writing"));

function PageFallback() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-ink-tertiary" />
    </div>
  );
}

function NotFound() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <FileQuestion className="h-16 w-16 text-ink-tertiary" />
      <h1 className="text-2xl font-semibold text-ink">404 - 页面不存在</h1>
      <p className="text-sm text-ink-secondary">你访问的页面不存在或已被移除</p>
      <a href="/" className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-hover">
        返回首页
      </a>
    </div>
  );
}

/**
 * 首屏加载完成后，利用浏览器空闲时间预取重型 chunk
 * markdown(168KB) + katex(259KB) 在 Agent 首条 AI 回复时需要
 */
function PrefetchChunks() {
  useEffect(() => {
    const prefetch = () => {
      import("@/components/Markdown");
    };
    if ("requestIdleCallback" in window) {
      const id = requestIdleCallback(prefetch);
      return () => cancelIdleCallback(id);
    }
    const timer = setTimeout(prefetch, 3000);
    return () => clearTimeout(timer);
  }, []);
  return null;
}
export default function App() {
  return (
    <ErrorBoundary>
    <ToastProvider>
    <BrowserRouter>
      <ToastContainer />
      <PrefetchChunks />
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
          <Route path="/email-settings" element={<Suspense fallback={<PageFallback />}><EmailSettings /></Suspense>} />
          <Route path="/writing" element={<Suspense fallback={<PageFallback />}><Writing /></Suspense>} />

          {/* 常见拼写重定向 */}
          <Route path="/briefs" element={<Navigate to="/brief" replace />} />
          <Route path="/settings" element={<Navigate to="/collect" replace />} />

          {/* 404 */}
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
    </ToastProvider>
    </ErrorBoundary>
  );
}
