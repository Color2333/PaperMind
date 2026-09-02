/**
 * 设备码授权页 —— pm login 时用户在浏览器打开 verification_url 完成授权
 * 流程：打开链接 → 站点密码登录（未登录时）→ 确认设备码 → 批准/拒绝 → 回到 CLI
 * @author Color2333
 */
import { useCallback, useEffect, useState } from "react";
import { MonitorSmartphone, CheckCircle2, XCircle, Clock, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import LoginPage from "@/pages/Login";
import { authApi, deviceAuthApi, isAuthenticated } from "@/services/api";
import { getErrorMessage } from "@/lib/errorHandler";

interface DeviceInfo {
  user_code: string;
  client_name: string;
  status: string;
  expires_in: number;
}

function readUserCode(): string {
  const params = new URLSearchParams(window.location.search);
  return (params.get("user_code") || "").trim().toUpperCase();
}

export default function DeviceAuthorize() {
  const [authed, setAuthed] = useState(() => isAuthenticated());
  const [authEnabled, setAuthEnabled] = useState(true);
  const [checked, setChecked] = useState(false);
  const [userCode, setUserCode] = useState(readUserCode);
  const [info, setInfo] = useState<DeviceInfo | null>(null);
  const [loadError, setLoadError] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [decision, setDecision] = useState<"approved" | "denied" | null>(null);

  // 认证未启用时无需登录，直接进入授权流程
  useEffect(() => {
    authApi
      .status()
      .then((s) => setAuthEnabled(s.auth_enabled))
      .catch(() => setAuthEnabled(true))
      .finally(() => setChecked(true));
  }, []);

  const loadInfo = useCallback(async (code: string) => {
    if (!code) return;
    setLoadError("");
    try {
      setInfo(await deviceAuthApi.info(code));
    } catch (err) {
      setInfo(null);
      setLoadError(getErrorMessage(err));
    }
  }, []);

  useEffect(() => {
    if (checked && (authed || !authEnabled)) {
      loadInfo(userCode);
    }
  }, [checked, authed, authEnabled, userCode, loadInfo]);

  const decide = async (action: "authorize" | "deny") => {
    setDeciding(true);
    try {
      await (action === "authorize"
        ? deviceAuthApi.authorize(userCode)
        : deviceAuthApi.deny(userCode));
      setDecision(action === "authorize" ? "approved" : "denied");
    } catch (err) {
      setLoadError(getErrorMessage(err));
      await loadInfo(userCode);
    } finally {
      setDeciding(false);
    }
  };

  // 未认证：内嵌登录页（登录成功后回到本页授权流程）
  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
        <Spinner />
      </div>
    );
  }
  if (authEnabled && !authed) {
    return <LoginPage onLoginSuccess={() => setAuthed(true)} />;
  }

  const expired = info?.status === "expired";
  const finalized = decision !== null || info?.status === "denied" || expired;

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="w-full max-w-md px-4">
        <div className="mb-8 text-center">
          <div className="bg-primary/10 mb-4 inline-flex h-16 w-16 items-center justify-center rounded-2xl">
            <MonitorSmartphone className="text-primary h-8 w-8" />
          </div>
          <h1 className="mb-2 text-2xl font-bold text-white">设备登录授权</h1>
          <p className="text-sm text-slate-400">确认下面设备码与你终端 pm login 显示的一致</p>
        </div>

        <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-6 shadow-xl backdrop-blur-sm">
          {/* 设备码输入（URL 未带或需要更正时） */}
          {!info && !loadError && (
            <div className="space-y-3">
              <input
                value={userCode}
                onChange={(e) => setUserCode(e.target.value.toUpperCase())}
                placeholder="输入设备码，如 ABKQ-WERT"
                className="w-full rounded-xl border border-slate-600 bg-slate-900/50 px-4 py-3 text-center font-mono text-lg tracking-widest text-white placeholder-slate-500 outline-none focus:border-primary"
                maxLength={9}
              />
              <Button
                variant="primary"
                className="w-full"
                onClick={() => loadInfo(userCode)}
                disabled={userCode.length !== 9}
              >
                查看授权请求
              </Button>
            </div>
          )}

          {loadError && (
            <div className="rounded-lg bg-red-500/10 px-3 py-2 text-center text-sm text-red-400">
              {loadError}
              <button
                type="button"
                onClick={() => {
                  setLoadError("");
                  setUserCode("");
                }}
                className="mt-2 block w-full text-xs text-slate-400 underline"
              >
                重新输入设备码
              </button>
            </div>
          )}

          {/* 待确认 */}
          {info && !finalized && (
            <div className="space-y-5">
              <div className="text-center">
                <div className="rounded-xl border border-slate-600 bg-slate-900/50 px-4 py-4 font-mono text-3xl font-bold tracking-widest text-white">
                  {info.user_code}
                </div>
                <p className="mt-3 text-sm text-slate-300">
                  设备 <span className="font-medium text-white">{info.client_name}</span> 请求登录
                  PaperMind
                </p>
                <p className="mt-1 flex items-center justify-center gap-1 text-xs text-slate-500">
                  <Clock className="h-3 w-3" />
                  {Math.floor(info.expires_in / 60)} 分{" "}
                  {String(info.expires_in % 60).padStart(2, "0")} 秒后过期
                </p>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="secondary"
                  className="flex-1"
                  onClick={() => decide("deny")}
                  disabled={deciding}
                >
                  <XCircle className="mr-1.5 h-4 w-4" />
                  拒绝
                </Button>
                <Button
                  variant="primary"
                  className="flex-1"
                  onClick={() => decide("authorize")}
                  disabled={deciding}
                >
                  {deciding ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="mr-1.5 h-4 w-4" />
                  )}
                  批准登录
                </Button>
              </div>
            </div>
          )}

          {/* 结果态 */}
          {decision === "approved" && (
            <ResultPanel
              icon={<CheckCircle2 className="h-10 w-10 text-green-400" />}
              title="已批准"
              desc="回到终端，pm login 会自动完成登录"
            />
          )}
          {decision === "denied" && (
            <ResultPanel
              icon={<XCircle className="h-10 w-10 text-red-400" />}
              title="已拒绝"
              desc="该设备登录请求已被拒绝"
            />
          )}
          {info?.status === "denied" && decision === null && (
            <ResultPanel
              icon={<XCircle className="h-10 w-10 text-red-400" />}
              title="已拒绝"
              desc="该设备登录请求已被拒绝"
            />
          )}
          {expired && (
            <ResultPanel
              icon={<Clock className="h-10 w-10 text-slate-400" />}
              title="已过期"
              desc="授权请求超时，请在终端重新执行 pm login"
            />
          )}
        </div>

        <p className="mt-6 text-center text-xs text-slate-500">
          PaperMind · 设备码授权（类似 GitHub CLI 登录流程）
        </p>
      </div>
    </div>
  );
}

function ResultPanel({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="py-6 text-center">
      <div className="mb-3 flex justify-center">{icon}</div>
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <p className="mt-1 text-sm text-slate-400">{desc}</p>
    </div>
  );
}
