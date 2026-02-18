/**
 * 知识图谱 - 通用子组件
 * @author Bamzc
 */
import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Spinner } from "@/components/ui";
import {
  ChevronDown, ChevronRight, Zap, Flame, ArrowDown,
  AlertTriangle, Target,
} from "lucide-react";
import type { ResearchGapsResponse } from "@/types";

export function Section({ title, icon, desc, children, action }: {
  title: string; icon: React.ReactNode; desc?: string;
  children: React.ReactNode; action?: React.ReactNode;
}) {
  return (
    <div className="animate-fade-in rounded-2xl border border-border bg-surface p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        {icon}
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {desc && <p className="text-xs text-ink-tertiary">{desc}</p>}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

export function StatCard({ label, value, icon }: {
  label: string; value: string | number; icon: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-sm">
      <div className="flex items-center gap-2 text-ink-tertiary">
        {icon}
        <span className="text-xs">{label}</span>
      </div>
      <p className="mt-1 text-2xl font-bold text-ink">{value}</p>
    </div>
  );
}

export function PaperLink({ id, title, className }: {
  id: string; title: string; className?: string;
}) {
  return (
    <Link
      to={`/papers/${id}`}
      className={`text-sm font-medium text-ink underline decoration-transparent transition-colors hover:text-primary hover:decoration-primary/50 ${className || ""}`}
    >
      {title}
    </Link>
  );
}

export function NetStat({ label, value, highlight }: {
  label: string; value: string | number; highlight?: boolean;
}) {
  return (
    <div className={`rounded-xl border border-border p-3 text-center ${highlight ? "bg-warning/5" : "bg-page"}`}>
      <p className={`text-lg font-bold ${highlight ? "text-warning" : "text-ink"}`}>{value}</p>
      <p className="text-[10px] text-ink-tertiary">{label}</p>
    </div>
  );
}

export function StrengthBadge({ value }: { value: string | undefined }) {
  if (!value) return <span className="text-ink-tertiary">-</span>;
  const v = value.toLowerCase();
  if (v.includes("强") || v === "strong" || v === "high")
    return <span className="rounded-md bg-success/10 px-2 py-0.5 text-[10px] font-medium text-success">{value}</span>;
  if (v.includes("弱") || v === "weak" || v === "low")
    return <span className="rounded-md bg-error/10 px-2 py-0.5 text-[10px] font-medium text-error">{value}</span>;
  return <span className="rounded-md bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning">{value}</span>;
}

export function GapCard({ gap, index }: {
  gap: ResearchGapsResponse["analysis"]["research_gaps"][0]; index: number;
}) {
  const [open, setOpen] = useState(index < 2);
  const diffColors: Record<string, string> = { easy: "text-success bg-success/10", medium: "text-warning bg-warning/10", hard: "text-error bg-error/10" };
  const diffLabel: Record<string, string> = { easy: "低", medium: "中", hard: "高" };

  return (
    <div className="rounded-xl border border-border bg-page/50 transition-all">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-3 text-left">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-warning/10 text-xs font-bold text-warning">{index + 1}</div>
        <div className="min-w-0 flex-1">
          <span className="text-sm font-medium text-ink">{gap.gap_title}</span>
          <div className="mt-1 flex items-center gap-2">
            <span className={`rounded-md px-2 py-0.5 text-[10px] font-medium ${diffColors[gap.difficulty]}`}>难度: {diffLabel[gap.difficulty]}</span>
            <span className="text-[10px] text-ink-tertiary">置信度: {(gap.confidence * 100).toFixed(0)}%</span>
          </div>
        </div>
        {open ? <ChevronDown className="h-4 w-4 text-ink-tertiary" /> : <ChevronRight className="h-4 w-4 text-ink-tertiary" />}
      </button>
      {open && (
        <div className="space-y-3 border-t border-border px-4 py-3">
          <div><p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-tertiary">描述</p><p className="text-sm leading-relaxed text-ink-secondary">{gap.description}</p></div>
          {gap.evidence && <div><p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-tertiary">证据</p><p className="text-sm leading-relaxed text-ink-secondary">{gap.evidence}</p></div>}
          {gap.potential_impact && <div className="rounded-lg bg-primary/5 px-3 py-2"><p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-primary">潜在影响</p><p className="text-sm leading-relaxed text-ink-secondary">{gap.potential_impact}</p></div>}
          {gap.suggested_approach && <div className="rounded-lg bg-success/5 px-3 py-2"><p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-success">建议方向</p><p className="text-sm leading-relaxed text-ink-secondary">{gap.suggested_approach}</p></div>}
        </div>
      )}
    </div>
  );
}

const LOADING_PHASES: Record<string, string[]> = {
  insight: ["正在分析引用网络...", "正在识别趋势...", "正在检测研究空白...", "正在生成报告..."],
  overview: ["加载全局数据..."],
  citation: ["正在分析引用关系..."],
  default: ["查询中..."],
};

export function LoadingHint({ tab, isInit }: { tab: string; isInit: boolean }) {
  const [phase, setPhase] = useState(0);
  const phases = isInit ? ["加载推荐数据..."] : (LOADING_PHASES[tab] || LOADING_PHASES.default);

  useEffect(() => {
    setPhase(0);
    const interval = setInterval(() => {
      setPhase((p) => (p + 1 < phases.length ? p + 1 : p));
    }, 5000);
    return () => clearInterval(interval);
  }, [tab, isInit, phases.length]);

  return (
    <div className="flex flex-col items-center gap-3 py-12">
      <Spinner />
      <p className="text-sm text-ink-secondary animate-fade-in">{phases[phase]}</p>
    </div>
  );
}
