/**
 * 全局概览面板 — 统计 / 力导向图 / PageRank / 前沿 / 桥接 / 共引
 * @author Bamzc
 */
import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { Link } from "react-router-dom";
import { Badge, Spinner } from "@/components/ui";
import { graphApi } from "@/services/api";
import { useToast } from "@/contexts/ToastContext";
import ForceGraph2D from "react-force-graph-2d";
import {
  FileText, Network, Layers, Tag, Share2, Star, Zap,
  Compass, RotateCw,
} from "lucide-react";
import type {
  LibraryOverview, OverviewNode, BridgesResponse,
  FrontierResponse, CocitationResponse,
} from "@/types";
import { Section, StatCard } from "./shared";

export default function OverviewPanel() {
  const { toast } = useToast();
  const [overview, setOverview] = useState<LibraryOverview | null>(null);
  const [bridges, setBridges] = useState<BridgesResponse | null>(null);
  const [frontier, setFrontier] = useState<FrontierResponse | null>(null);
  const [cocitation, setCocitation] = useState<CocitationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const loaded = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, br, fr, co] = await Promise.all([
        graphApi.overview().catch(() => null),
        graphApi.bridges().catch(() => null),
        graphApi.frontier().catch(() => null),
        graphApi.cocitationClusters().catch(() => null),
      ]);
      if (ov) setOverview(ov);
      if (br) setBridges(br);
      if (fr) setFrontier(fr);
      if (co) setCocitation(co);
    } catch { toast("error", "加载概览数据失败"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => {
    if (loaded.current) return;
    loaded.current = true;
    load();
  }, [load]);

  if (loading) return (
    <div className="flex flex-col items-center gap-3 py-16">
      <Spinner />
      <p className="text-sm text-ink-secondary animate-fade-in">加载全局数据...</p>
    </div>
  );

  if (!overview) return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-border py-16 text-center">
      <Compass className="h-8 w-8 text-ink-tertiary/30" />
      <p className="mt-4 text-sm text-ink-tertiary">暂无图谱数据，请先收集论文</p>
    </div>
  );

  return <OverviewContent overview={overview} bridges={bridges} frontier={frontier} cocitation={cocitation} onRefresh={load} />;
}

/* ---- 内部内容组件 ---- */
function OverviewContent({
  overview, bridges, frontier, cocitation, onRefresh,
}: {
  overview: LibraryOverview;
  bridges: BridgesResponse | null;
  frontier: FrontierResponse | null;
  cocitation: CocitationResponse | null;
  onRefresh: () => void;
}) {
  const graphRef = useRef<HTMLDivElement>(null);
  const [gw, setGw] = useState(800);
  const gh = 500;

  useEffect(() => {
    if (!graphRef.current) return;
    const obs = new ResizeObserver((entries) => {
      for (const e of entries) setGw(e.contentRect.width);
    });
    obs.observe(graphRef.current);
    return () => obs.disconnect();
  }, []);

  const graphData = useMemo(() => ({
    nodes: overview.nodes.map((n) => ({ ...n, val: Math.max(n.pagerank * 500, 3) })),
    links: overview.edges,
  }), [overview]);

  return (
    <div className="space-y-5 animate-fade-in">
      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="论文总数" value={overview.total_papers} icon={<FileText className="h-4 w-4 text-primary" />} />
        <StatCard label="引用关系" value={overview.total_edges} icon={<Network className="h-4 w-4 text-accent" />} />
        <StatCard label="图谱密度" value={`${(overview.density * 100).toFixed(2)}%`} icon={<Layers className="h-4 w-4 text-warning" />} />
        <StatCard label="主题数" value={Object.keys(overview.topic_stats).length} icon={<Tag className="h-4 w-4 text-success" />} />
      </div>

      {/* 全局力导向图 */}
      <Section title="全局引用网络" icon={<Share2 className="h-4 w-4 text-primary" />} desc="节点大小 = PageRank 影响力，颜色 = 主题">
        <div ref={graphRef} className="relative overflow-hidden rounded-xl bg-page" style={{ height: gh }}>
          <ForceGraph2D
            width={gw}
            height={gh}
            graphData={graphData}
            nodeRelSize={4}
            nodeLabel={(n: OverviewNode & { val: number }) => `${n.title}\nPageRank: ${n.pagerank.toFixed(4)}\n引用: ${n.in_degree} 被引: ${n.out_degree}`}
            nodeColor={(n: OverviewNode) => {
              const t = n.topics[0];
              if (!t) return "#94a3b8";
              const hash = [...t].reduce((a, c) => a + c.charCodeAt(0), 0);
              const hues = [210, 150, 30, 330, 270, 60, 0, 180];
              return `hsl(${hues[hash % hues.length]}, 65%, 55%)`;
            }}
            linkColor={() => "rgba(148,163,184,0.15)"}
            linkWidth={0.5}
            onNodeClick={(node: OverviewNode) => { window.location.href = `/papers/${node.id}`; }}
            cooldownTicks={80}
            enableZoomInteraction
          />
          <button onClick={onRefresh} className="absolute right-3 top-3 rounded-lg bg-surface/80 p-2 text-ink-tertiary hover:text-primary transition-colors" title="刷新">
            <RotateCw className="h-4 w-4" />
          </button>
        </div>
      </Section>

      {/* PageRank 排行 */}
      <Section title="影响力排行 (PageRank)" icon={<Star className="h-4 w-4 text-warning" />} desc="库内被引最多、影响力最高的论文">
        <div className="space-y-2">
          {overview.top_papers.map((p, i) => (
            <div key={p.id} className="flex items-center gap-3 rounded-xl border border-border bg-page px-4 py-3 transition-colors hover:border-primary/30">
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${i < 3 ? "bg-warning/10 text-warning" : "bg-page text-ink-tertiary"}`}>{i + 1}</span>
              <div className="min-w-0 flex-1">
                <Link to={`/papers/${p.id}`} className="text-sm font-medium text-ink hover:text-primary line-clamp-1">{p.title}</Link>
                <div className="mt-0.5 flex gap-3 text-xs text-ink-tertiary">
                  {p.year && <span>{p.year}</span>}
                  <span>引用 {p.in_degree}</span>
                  <span>被引 {p.out_degree}</span>
                  <span>PR {p.pagerank.toFixed(4)}</span>
                  {p.topics.map((t) => <Badge key={t} variant="info" className="text-[10px]">{t}</Badge>)}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* 研究前沿 */}
      {frontier && frontier.frontier.length > 0 && (
        <Section title="研究前沿" icon={<Zap className="h-4 w-4 text-accent" />} desc={`近 ${frontier.period_days} 天内引用速度最快的论文`}>
          <div className="space-y-2">
            {frontier.frontier.slice(0, 10).map((p) => (
              <div key={p.id} className="flex items-center justify-between rounded-xl border border-border bg-page px-4 py-3">
                <div className="min-w-0 flex-1">
                  <Link to={`/papers/${p.id}`} className="text-sm font-medium text-ink hover:text-primary line-clamp-1">{p.title}</Link>
                  <div className="mt-0.5 flex gap-3 text-xs text-ink-tertiary">
                    <span>{p.publication_date}</span>
                    <span>库内被引 {p.citations_in_library}</span>
                  </div>
                </div>
                <div className="ml-3 shrink-0 text-right">
                  <span className="text-sm font-bold text-accent">{p.citation_velocity}</span>
                  <span className="ml-1 text-xs text-ink-tertiary">引/月</span>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* 跨主题桥接 */}
      {bridges && bridges.bridges.length > 0 && (
        <Section title="跨主题桥接论文" icon={<Compass className="h-4 w-4 text-primary" />} desc="被多个研究主题引用的关键论文">
          <div className="space-y-2">
            {bridges.bridges.slice(0, 10).map((b) => (
              <div key={b.id} className="flex items-center justify-between rounded-xl border border-border bg-page px-4 py-3">
                <div className="min-w-0 flex-1">
                  <Link to={`/papers/${b.id}`} className="text-sm font-medium text-ink hover:text-primary line-clamp-1">{b.title}</Link>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {b.topics_citing.map((t) => <Badge key={t} variant="info" className="text-[10px]">{t}</Badge>)}
                  </div>
                </div>
                <div className="ml-3 shrink-0">
                  <Badge variant="default">{b.cross_topic_count} 主题</Badge>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* 共引聚类 */}
      {cocitation && cocitation.clusters.length > 0 && (
        <Section title="共引聚类" icon={<Layers className="h-4 w-4 text-info" />} desc="被相同论文引用的研究会自动聚在一起">
          <div className="space-y-3">
            {cocitation.clusters.slice(0, 8).map((cl, i) => (
              <div key={i} className="rounded-xl border border-border bg-page p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Badge variant="info">聚类 {i + 1}</Badge>
                  <span className="text-xs text-ink-tertiary">{cl.size} 篇论文</span>
                </div>
                <div className="space-y-1">
                  {cl.papers.map((p) => (
                    <Link key={p.id} to={`/papers/${p.id}`} className="block text-sm text-ink hover:text-primary line-clamp-1">{p.title}</Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
