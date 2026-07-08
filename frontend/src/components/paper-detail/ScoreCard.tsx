import type { ReactNode } from "react";

function ScoreCard({
  label,
  score,
  icon,
  color,
  bg,
}: {
  label: string;
  score: number;
  icon: ReactNode;
  color: string;
  bg: string;
}) {
  const pct = Math.round(score * 100);
  return (
    <div className="border-border bg-surface rounded-xl border p-4 text-center">
      <div
        className={`mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full ${bg} ${color}`}
      >
        {icon}
      </div>
      <div className="text-ink text-2xl font-bold">
        {pct}
        <span className="text-ink-tertiary text-sm">%</span>
      </div>
      <div className="text-ink-tertiary mt-1 text-xs">{label}</div>
      <div className="bg-hover mt-2 h-1.5 w-full overflow-hidden rounded-full">
        <div
          className={`h-full rounded-full transition-all duration-700 ${score > 0.7 ? "bg-green-500" : score > 0.4 ? "bg-amber-500" : "bg-red-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default ScoreCard;
