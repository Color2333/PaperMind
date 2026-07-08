import type { ReactNode } from "react";

/* ================================================================
 * 空状态报告占位
 * ================================================================ */

function EmptyReport({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="border-border bg-page/50 flex flex-col items-center justify-center rounded-2xl border border-dashed py-16 text-center">
      <div className="text-ink-tertiary/50 mb-3">{icon}</div>
      <p className="text-ink-tertiary text-sm">{label}</p>
    </div>
  );
}

export default EmptyReport;
