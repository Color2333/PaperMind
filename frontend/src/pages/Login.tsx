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
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="w-full max-w-md px-4">
        {/* Logo 和标题 */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-4">
            <Lock className="w-8 h-8 text-primary" />
          </div>
          <h1 className="text-2xl font-bold text-white mb-2">PaperMind</h1>
          <p className="text-slate-400 text-sm">请输入访问密码</p>
        </div>

        {/* 登录表单 */}
        <form onSubmit={handleSubmit} className="bg-slate-800/50 backdrop-blur-sm rounded-2xl p-6 shadow-xl border border-slate-700/50">
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="访问密码"
              className="w-full px-4 py-3 pr-12 bg-slate-900/50 border border-slate-600 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-all"
              disabled={loading}
              autoFocus
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
            >
              {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
            </button>
          </div>

          {error && (
            <p className="mt-3 text-sm text-red-400 text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full mt-4 py-3 bg-primary hover:bg-primary-hover disabled:bg-slate-600 text-white font-medium rounded-xl transition-colors flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>验证中...</span>
              </>
            ) : (
              <span>进入系统</span>
            )}
          </button>
        </form>

        {/* 底部提示 */}
        <p className="text-center mt-6 text-slate-500 text-xs">
          PaperMind · AI 驱动的学术论文研究平台
        </p>
      </div>
    </div>
  );
}