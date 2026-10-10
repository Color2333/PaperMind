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
  const [checkingAuth, setCheckingAuth] = useState(true); // 检查认证状态期间显示 loading，防竞态

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
      // 接口失败：保留登录页，但提示用户可尝试输入（认证可能仍启用）
      setError("无法确认认证状态，若已启用密码请直接输入");
    } finally {
      setCheckingAuth(false);
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
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-[#1B1917] via-[#141210] to-[#1B1917]">
      <div className="w-full max-w-md px-4">
        {/* Logo 和标题 */}
        <div className="mb-8 text-center">
          <div className="bg-primary/10 mb-4 inline-flex h-16 w-16 items-center justify-center rounded-2xl">
            <Lock className="text-primary h-8 w-8" />
          </div>
          <h1 className="mb-2 text-2xl font-bold text-white">PaperMind</h1>
          <p className="text-sm text-[#A2988C]">请输入访问密码</p>
        </div>

        {/* 登录表单 */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-[#2E2A25]/60 bg-[#201D1A]/70 p-6 shadow-xl backdrop-blur-sm"
        >
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="访问密码"
              className="focus:ring-primary w-full rounded-xl border border-[#2E2A25] bg-[#131110]/60 px-4 py-3 pr-12 text-white placeholder-[#575047] transition-all focus:border-transparent focus:ring-2 focus:outline-none"
              disabled={loading || checkingAuth}
              autoFocus
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute top-1/2 right-3 -translate-y-1/2 text-[#A2988C] transition-colors hover:text-[#EBE5DC]"
            >
              {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
            </button>
          </div>

          {error && <p className="mt-3 text-center text-sm text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading || checkingAuth}
            className="bg-primary hover:bg-primary-hover mt-4 flex w-full items-center justify-center gap-2 rounded-xl py-3 font-medium text-white transition-colors disabled:bg-[#575047]"
          >
            {checkingAuth ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>检查认证状态...</span>
              </>
            ) : loading ? (
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
        <p className="mt-6 text-center text-xs text-[#A2988C]">
          PaperMind · AI 驱动的学术论文研究平台
        </p>
      </div>
    </div>
  );
}
