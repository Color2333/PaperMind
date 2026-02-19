/**
 * PaperMind 桌面版 — 首次启动引导
 * 让用户选择数据目录和 .env 配置文件路径。
 * @author Bamzc
 */
import { useState } from "react";
import {
  FolderOpen,
  FileText,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Sparkles,
} from "lucide-react";
import {
  saveConfigAndStart,
  openFolderDialog,
  openFileDialog,
} from "@/lib/tauri";

interface Props {
  onReady: (port: number) => void;
}

export default function SetupWizard({ onReady }: Props) {
  const home = "~/Library/Application Support/PaperMind/data";
  const [dataDir, setDataDir] = useState(home);
  const [envFile, setEnvFile] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectFolder = async () => {
    const dir = await openFolderDialog("选择数据存储目录");
    if (dir) setDataDir(dir);
  };

  const selectEnvFile = async () => {
    const file = await openFileDialog("选择 .env 配置文件", [
      { name: "Environment", extensions: ["env"] },
      { name: "All", extensions: ["*"] },
    ]);
    if (file) setEnvFile(file);
  };

  const handleStart = async () => {
    if (!dataDir.trim()) {
      setError("请选择数据存储目录");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const port = await saveConfigAndStart(dataDir.trim(), envFile.trim());
      onReady(port);
    } catch (e) {
      setError(String(e));
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-50 dark:from-gray-950 dark:via-gray-900 dark:to-slate-900">
      <div className="w-full max-w-lg rounded-2xl border border-white/30 bg-white/80 p-8 shadow-2xl backdrop-blur-lg dark:border-white/10 dark:bg-gray-800/80">
        {/* Header */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg">
            <Sparkles className="h-8 w-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            欢迎使用 PaperMind
          </h1>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            首次启动，请配置数据存储路径
          </p>
        </div>

        {/* 数据目录 */}
        <div className="mb-6">
          <label className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
            <FolderOpen className="h-4 w-4" />
            数据存储目录
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={dataDir}
              onChange={(e) => setDataDir(e.target.value)}
              placeholder="选择数据存储目录..."
              className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 transition-colors focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:focus:border-blue-500 dark:focus:ring-blue-900"
            />
            <button
              onClick={selectFolder}
              className="shrink-0 rounded-lg bg-gray-100 px-4 py-2.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200 dark:bg-gray-600 dark:text-gray-200 dark:hover:bg-gray-500"
            >
              浏览
            </button>
          </div>
          <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
            论文、数据库、简报等文件都会存储在此目录
          </p>
        </div>

        {/* .env 文件 */}
        <div className="mb-8">
          <label className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
            <FileText className="h-4 w-4" />
            配置文件路径
            <span className="text-xs text-gray-400">(可选)</span>
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={envFile}
              onChange={(e) => setEnvFile(e.target.value)}
              placeholder="选择 .env 配置文件（可选）..."
              className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 transition-colors focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:focus:border-blue-500 dark:focus:ring-blue-900"
            />
            <button
              onClick={selectEnvFile}
              className="shrink-0 rounded-lg bg-gray-100 px-4 py-2.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200 dark:bg-gray-600 dark:text-gray-200 dark:hover:bg-gray-500"
            >
              浏览
            </button>
          </div>
          <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
            包含 API 密钥等敏感配置，不设置则使用内置默认值
          </p>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* 启动按钮 */}
        <button
          onClick={handleStart}
          disabled={loading}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-500 to-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-lg transition-all hover:from-blue-600 hover:to-indigo-700 hover:shadow-xl disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              正在启动后端服务...
            </>
          ) : (
            <>
              <CheckCircle2 className="h-4 w-4" />
              确认并启动 PaperMind
            </>
          )}
        </button>

        {/* 底部提示 */}
        <p className="mt-6 text-center text-xs text-gray-400 dark:text-gray-500">
          配置会保存在 ~/Library/Application Support/PaperMind/launcher.json
          <br />
          后续可在设置页面中修改
        </p>
      </div>
    </div>
  );
}
