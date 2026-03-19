/**
 * PaperMind - 登录页面
 * @author Color2333
 */
import { useState, useEffect } from "react";
import { Lock, Loader2, Eye, EyeOff } from "lucide-react";
import { authApi } from "@/services/api";

interface LoginPageProps {
  onLoginSuccess: () => void;
}

export default function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    // 页面加载时检查是否需要认证
    checkAuthStatus();
  }, []);

  async function checkAuthStatus() {
    try {
      const status = await authApi.status();
      if (!status.auth_enabled) {
        // 未启用认证，直接进入
        onLoginSuccess();
      }
    } catch {
      // 忽略错误，继续显示登录页
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!password.trim()) {
      setError("请输入密码");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const result = await authApi.login(password);
      localStorage.setItem("auth_token", result.access_token);
      onLoginSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="w-full max-w-md px-4">
        {/* Logo 和标题 */}
        <div className="mb-8 text-center">
          <div className="bg-primary/10 mb-4 inline-flex h-16 w-16 items-center justify-center rounded-2xl">
            <Lock className="text-primary h-8 w-8" />
          </div>
          <h1 className="mb-2 text-2xl font-bold text-white">PaperMind</h1>
          <p className="text-sm text-slate-400">请输入访问密码</p>
        </div>

        {/* 登录表单 */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-6 shadow-xl backdrop-blur-sm"
        >
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="访问密码"
              className="focus:ring-primary w-full rounded-xl border border-slate-600 bg-slate-900/50 px-4 py-3 pr-12 text-white placeholder-slate-500 transition-all focus:border-transparent focus:ring-2 focus:outline-none"
              disabled={loading}
              autoFocus
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute top-1/2 right-3 -translate-y-1/2 text-slate-500 transition-colors hover:text-slate-300"
            >
              {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
            </button>
          </div>

          {error && <p className="mt-3 text-center text-sm text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="bg-primary hover:bg-primary-hover mt-4 flex w-full items-center justify-center gap-2 rounded-xl py-3 font-medium text-white transition-colors disabled:bg-slate-600"
          >
            {loading ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>验证中...</span>
              </>
            ) : (
              <span>进入系统</span>
            )}
          </button>
        </form>

        {/* 底部提示 */}
        <p className="mt-6 text-center text-xs text-slate-500">
          PaperMind · AI 驱动的学术论文研究平台
        </p>
      </div>
    </div>
  );
}
