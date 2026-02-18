/**
 * Toast 通知渲染组件
 * @author Bamzc
 */
import { useToast, type ToastType } from "@/contexts/ToastContext";
import { CheckCircle2, XCircle, Info, AlertTriangle, X } from "lucide-react";

const ICON: Record<ToastType, React.ReactNode> = {
  success: <CheckCircle2 className="h-4 w-4 text-success" />,
  error: <XCircle className="h-4 w-4 text-error" />,
  info: <Info className="h-4 w-4 text-info" />,
  warning: <AlertTriangle className="h-4 w-4 text-warning" />,
};

const BG: Record<ToastType, string> = {
  success: "border-success/30 bg-success/5",
  error: "border-error/30 bg-error/5",
  info: "border-info/30 bg-info/5",
  warning: "border-warning/30 bg-warning/5",
};

export default function ToastContainer() {
  const { toasts, dismiss } = useToast();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed right-4 top-4 z-[9999] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`animate-slide-in flex items-start gap-2.5 rounded-xl border px-4 py-3 shadow-lg backdrop-blur-sm ${BG[t.type]}`}
          style={{ minWidth: 260, maxWidth: 400 }}
        >
          <span className="mt-0.5 shrink-0">{ICON[t.type]}</span>
          <p className="flex-1 text-sm text-ink">{t.message}</p>
          <button onClick={() => dismiss(t.id)} className="shrink-0 rounded p-0.5 text-ink-tertiary hover:text-ink">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
