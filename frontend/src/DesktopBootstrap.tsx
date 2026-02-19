/**
 * PaperMind 启动引导
 * Web 模式直接渲染 App；Tauri 模式先检测配置、等待后端就绪。
 * @author Bamzc
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import App from "./App";
import { isTauri, needsSetup, waitForBackend, setApiPort, listen } from "@/lib/tauri";

const SetupWizard = lazy(() => import("@/pages/SetupWizard"));

type Phase = "checking" | "setup" | "waiting" | "ready";

function LoadingScreen({ message, error }: { message: string; error?: string }) {
  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-4 bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-50 dark:from-gray-950 dark:via-gray-900 dark:to-slate-900">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg">
        <Sparkles className="h-8 w-8 text-white" />
      </div>
      {error ? (
        <>
          <p className="text-lg font-semibold text-red-600 dark:text-red-400">后端启动失败</p>
          <p className="max-w-sm text-center text-sm text-red-500">{error}</p>
        </>
      ) : (
        <>
          <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          <p className="text-sm text-gray-500 dark:text-gray-400">{message}</p>
        </>
      )}
    </div>
  );
}

export default function DesktopBootstrap() {
  const [phase, setPhase] = useState<Phase>(isTauri() ? "checking" : "ready");
  const [backendError, setBackendError] = useState("");

  useEffect(() => {
    if (!isTauri()) return;

    let unlistenError: (() => void) | null = null;

    (async () => {
      unlistenError = await listen<string>("backend-error", (msg) => {
        setBackendError(msg);
      });

      const setup = await needsSetup();
      if (setup) {
        setPhase("setup");
      } else {
        setPhase("waiting");
        const port = await waitForBackend();
        setApiPort(port);
        setPhase("ready");
      }
    })();

    return () => {
      unlistenError?.();
    };
  }, []);

  if (phase === "ready") {
    return <App />;
  }

  if (phase === "setup") {
    return (
      <Suspense fallback={<LoadingScreen message="加载引导页..." />}>
        <SetupWizard
          onReady={(port: number) => {
            setApiPort(port);
            setPhase("ready");
          }}
        />
      </Suspense>
    );
  }

  return (
    <LoadingScreen
      message={phase === "checking" ? "正在检查配置..." : "正在启动后端服务..."}
      error={backendError || undefined}
    />
  );
}
