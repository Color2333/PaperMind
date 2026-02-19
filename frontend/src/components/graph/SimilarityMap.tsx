/**
 * SimilarityMap - 论文相似度 2D 散点图（Canvas 渲染）
 * @author Bamzc
 */
import { useRef, useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import type { SimilarityMapPoint } from "@/types";

const COLORS = [
  "#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6",
  "#06b6d4", "#f97316", "#ec4899", "#14b8a6", "#a855f7",
  "#64748b", "#84cc16",
];

interface Props {
  points: SimilarityMapPoint[];
  width?: number;
  height?: number;
}

export default function SimilarityMap({ points, width = 800, height = 500 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const [tooltip, setTooltip] = useState<{ x: number; y: number; point: SimilarityMapPoint } | null>(null);
  const [canvasSize, setCanvasSize] = useState({ w: width, h: height });

  // 主题 → 颜色映射
  const topicColorMap = useRef(new Map<string, string>());
  const getTopicColor = useCallback((topic: string) => {
    if (!topicColorMap.current.has(topic)) {
      topicColorMap.current.set(topic, COLORS[topicColorMap.current.size % COLORS.length]);
    }
    return topicColorMap.current.get(topic)!;
  }, []);

  // 计算数据范围和映射
  const mapToCanvas = useCallback((px: number, py: number) => {
    if (points.length === 0) return { cx: 0, cy: 0 };
    const xs = points.map(p => p.x);
    const ys = points.map(p => p.y);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yMin = Math.min(...ys), yMax = Math.max(...ys);
    const pad = 40;
    const xRange = xMax - xMin || 1;
    const yRange = yMax - yMin || 1;
    return {
      cx: pad + ((px - xMin) / xRange) * (canvasSize.w - 2 * pad),
      cy: pad + ((py - yMin) / yRange) * (canvasSize.h - 2 * pad),
    };
  }, [points, canvasSize]);

  // 响应式宽度
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver(entries => {
      const entry = entries[0];
      if (entry) setCanvasSize({ w: entry.contentRect.width, h: height });
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, [height]);

  // 绘制
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvasSize.w * dpr;
    canvas.height = canvasSize.h * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, canvasSize.w, canvasSize.h);

    // 绘制点
    for (const p of points) {
      const { cx, cy } = mapToCanvas(p.x, p.y);
      if (isNaN(cx) || isNaN(cy)) continue;

      const color = getTopicColor(p.topic);
      const r = p.read_status === "deep_read" ? 7 : p.read_status === "skimmed" ? 5.5 : 4;

      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = color + "cc";
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }, [points, canvasSize, mapToCanvas, getTopicColor]);

  // 鼠标交互
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    let closest: SimilarityMapPoint | null = null;
    let minDist = 20;

    for (const p of points) {
      const { cx, cy } = mapToCanvas(p.x, p.y);
      if (isNaN(cx) || isNaN(cy)) continue;
      const d = Math.sqrt((mx - cx) ** 2 + (my - cy) ** 2);
      if (d < minDist) { minDist = d; closest = p; }
    }

    if (closest) {
      setTooltip({ x: e.clientX, y: e.clientY, point: closest });
      canvas.style.cursor = "pointer";
    } else {
      setTooltip(null);
      canvas.style.cursor = "default";
    }
  }, [points, mapToCanvas]);

  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    for (const p of points) {
      const { cx, cy } = mapToCanvas(p.x, p.y);
      if (isNaN(cx) || isNaN(cy)) continue;
      if (Math.sqrt((mx - cx) ** 2 + (my - cy) ** 2) < 15) {
        navigate(`/papers/${p.id}`);
        return;
      }
    }
  }, [points, mapToCanvas, navigate]);

  // 图例
  const uniqueTopics = [...new Set(points.map(p => p.topic))];

  const STATUS_LABEL: Record<string, string> = { unread: "未读", skimmed: "已粗读", deep_read: "已精读" };

  return (
    <div ref={containerRef} className="relative w-full">
      <canvas
        ref={canvasRef}
        style={{ width: canvasSize.w, height: canvasSize.h }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setTooltip(null)}
        onClick={handleClick}
        className="rounded-xl border border-border bg-page/50"
      />

      {/* Tooltip */}
      {tooltip && (
        <div
          className="pointer-events-none fixed z-50 max-w-xs rounded-lg border border-border bg-surface px-3 py-2 shadow-lg"
          style={{ left: tooltip.x + 12, top: tooltip.y - 10 }}
        >
          <p className="text-xs font-semibold text-ink">{tooltip.point.title}</p>
          {tooltip.point.title_zh && <p className="mt-0.5 text-[10px] text-ink-secondary">{tooltip.point.title_zh}</p>}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-ink-tertiary">
            <span className="rounded bg-primary/10 px-1.5 py-0.5 text-primary">{tooltip.point.topic}</span>
            {tooltip.point.year && <span>{tooltip.point.year}</span>}
            <span>{STATUS_LABEL[tooltip.point.read_status] || tooltip.point.read_status}</span>
          </div>
        </div>
      )}

      {/* 图例 */}
      {uniqueTopics.length > 1 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
          {uniqueTopics.map(t => (
            <span key={t} className="flex items-center gap-1.5 text-[10px] text-ink-secondary">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: getTopicColor(t) }} />
              {t}
            </span>
          ))}
          <span className="ml-2 text-[10px] text-ink-tertiary">
            大 = 精读 · 中 = 粗读 · 小 = 未读
          </span>
        </div>
      )}
    </div>
  );
}
