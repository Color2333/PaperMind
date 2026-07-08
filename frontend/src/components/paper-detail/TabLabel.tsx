import { Loader2, Check } from "lucide-react";

/* ================================================================
 * Tab 状态指示器
 * ================================================================ */

function TabLabel({ label, status }: { label: string; status: "idle" | "loading" | "done" }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {status === "loading" && <Loader2 className="text-primary h-3 w-3 animate-spin" />}
      {status === "done" && <Check className="text-success h-3 w-3" />}
      {label}
    </span>
  );
}

export default TabLabel;
