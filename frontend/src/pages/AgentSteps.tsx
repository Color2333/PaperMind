import { memo, useState, Suspense, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Download,
  Search,
  BookOpen,
  FileText,
  Brain,
  Newspaper,
  Star,
  Hash,
  TrendingUp,
  AlertTriangle,
} from "lucide-react";
import { useAgentSession, type StepItem } from "@/contexts/AgentSessionContext";
import { lazy } from "react";
const Markdown = lazy(() => import("@/components/Markdown"));

interface ToolMeta {
  icon: typeof Search;
  label: string;
}

function getToolMeta(name: string): ToolMeta {
  const META: Record<string, ToolMeta> = {
    search_arxiv: { icon: Search, label: "搜索 arXiv" },
    search_papers: { icon: Search, label: "搜索论文库" },
    ingest_arxiv: { icon: Download, label: "下载入库" },
    get_system_status: { icon: Brain, label: "系统状态" },
    list_topics: { icon: Hash, label: "主题列表" },
    get_timeline: { icon: TrendingUp, label: "时间线" },
    get_similar_papers: { icon: Star, label: "相似论文" },
    get_citation_tree: { icon: BookOpen, label: "引用树" },
    suggest_keywords: { icon: Hash, label: "关键词建议" },
    ask_knowledge_base: { icon: Brain, label: "知识库问答" },
    skim_paper: { icon: FileText, label: "粗读论文" },
    deep_read_paper: { icon: BookOpen, label: "精读论文" },
    reasoning_analysis: { icon: Brain, label: "推理链分析" },
    analyze_figures: { icon: FileText, label: "图表解读" },
    identify_research_gaps: { icon: Search, label: "研究空白" },
    get_paper_detail: { icon: FileText, label: "论文详情" },
    writing_assist: { icon: Newspaper, label: "写作助手" },
  };
  return META[name] || { icon: FileText, label: name };
}

function PaperListView({ papers, label }: { papers: Array<Record<string, unknown>>; label: string }) {
  const navigate = useNavigate();
  return (
    <div className="space-y-1">
      <p className="text-ink-secondary px-2 py-1 text-[11px]">{label}</p>
      {papers.slice(0, 5).map((p) => (
        <button
          type="button"
          key={String(p.id ?? "")}
          onClick={() => p.id && navigate(`/papers/${String(p.id)}`)}
          className="bg-surface hover:bg-hover flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11px] transition-colors"
        >
          <FileText className="text-primary h-3 w-3 shrink-0" />
          <span className="text-ink truncate">{String(p.title ?? "")}</span>
        </button>
      ))}
    </div>
  );
}

function IngestResultView({ data }: { data: Record<string, unknown> }) {
  const navigate = useNavigate();
  return (
    <div className="space-y-2 px-2 py-1.5">
      <div className="flex items-center gap-3 text-[11px]">
        <span className="text-ink font-medium">已入库 {String(data.total ?? 0)} 篇</span>
        {data.skipped !== undefined && <span className="text-ink-tertiary">（{String(data.skipped)} 篇跳过）</span>}
      </div>
      {Array.isArray(data.papers) && (data.papers as Array<Record<string, unknown>>).length > 0 && (
        <div className="space-y-1">
          {(data.papers as Array<Record<string, unknown>>).slice(0, 3).map((p) => (
            <button
              type="button"
              key={String(p.id ?? "")}
              onClick={() => p.id && navigate(`/papers/${String(p.id)}`)}
              className="bg-surface hover:bg-hover flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-[10px] transition-colors"
            >
              <CheckCircle2 className="text-success h-3 w-3 shrink-0" />
              <span className="text-ink truncate">{String(p.title ?? "")}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function inferRelevantCategories(query: string): Set<string> {
  const cats: string[] = [];
  const LOWER = query.toLowerCase();
  const ALIASES: Record<string, string[]> = {
    "cs.AI": ["artificial intelligence", "ai", "machine learning", "ml", "deep learning", "neural", "gpt", "llm", "transformer", "reinforcement learning", "nlp", "natural language"],
    "cs.CV": ["computer vision", "cv", "image", "video", "object detection", "segmentation", "recognition", "gan", "diffusion", "stable diffusion", "dino"],
    "cs.LG": ["machine learning", "ml", "deep learning", "neural network", "representation", "self-supervised", "contrastive"],
    "cs.CL": ["computational linguistics", "nlp", "natural language", "text", "language model", "translation", "parsing", "word2vec", "bert", "embedding"],
    "cs.IR": ["information retrieval", "search", "ranking", "recommender", "recommendation"],
    "cs.KR": ["knowledge representation", "reasoning", "logic", "knowledge graph"],
    "cs.Robotics": ["robotics", "robot", "autonomous", "manipulation", "navigation"],
    "cs.NE": ["neural evolution", "evolutionary", "genetic algorithm"],
    "cs.SE": ["software engineering", "program synthesis", "code generation"],
    "cs.CR": ["cryptography", "security", "privacy"],
    "cs.CY": ["cybersecurity", "security", "privacy", "attack", "defense"],
    "cs.DC": ["distributed computing", "parallel", "grid", "cluster"],
    "cs.DS": ["data science", "analytics", "data mining", "big data"],
    "cs.DB": ["database", "sql", "nosql", "query"],
    "cs.PL": ["programming language", "compiler", "type system", "parser"],
    "cs.HCI": ["human computer interaction", "ux", "ui", "interface", "vr", "ar", "virtual reality", "augmented reality"],
    "cs.GR": ["graphics", "rendering", "3d", "geometry", "animation"],
    "cs.MM": ["multimedia", "video", "audio", "speech"],
    "cs.SD": ["sound", "audio", "speech", "music"],
    "cs.LO": ["logic", "formal", "theorem proving", "coq", "lean"],
    "cs.MA": ["mathematics", "algebra", "geometry", "calculus", "optimization"],
    "cs.RO": ["optimization", "operations research", "linear programming", "integer programming"],
    "cs.ET": ["emerging technology", "blockchain", "web3", "metaverse"],
    "cs.CG": ["computational geometry", "geometry", "mesh", "voronoi"],
    "cs.AP": ["applied computing", "e-commerce", "finance", "health", "medicine", "biology", "bioinformatics"],
  };
  for (const [cat, kwList] of Object.entries(ALIASES)) {
    if (kwList.some((kw) => LOWER.includes(kw))) {
      cats.push(cat);
    }
  }
  return new Set(cats);
}

function isRelevantCandidate(cats: string[], relevantCats: Set<string>): boolean {
  if (relevantCats.size === 0) return true;
  return cats.some((c) => relevantCats.has(c));
}

const ArxivCandidateSelector = memo(function ArxivCandidateSelector({
  candidates,
  query,
}: {
  candidates: Array<Record<string, unknown>>;
  query: string;
}) {
  const { sendMessage, loading } = useAgentSession();
  const relevantCats = inferRelevantCategories(query);

  const [selected, setSelected] = useState<Set<string>>(() => {
    if (relevantCats.size === 0) return new Set(candidates.map((c) => String(c.arxiv_id ?? "")));
    const relevant = new Set<string>();
    for (const c of candidates) {
      const cats = Array.isArray(c.categories) ? (c.categories as string[]) : [];
      if (isRelevantCandidate(cats, relevantCats)) relevant.add(String(c.arxiv_id ?? ""));
    }
    return relevant.size > 0 ? relevant : new Set(candidates.map((c) => String(c.arxiv_id ?? "")));
  });
  const [submitted, setSubmitted] = useState(false);
  const allSelected = selected.size === candidates.length;
  const relevantCount =
    relevantCats.size > 0
      ? candidates.filter((c) => isRelevantCandidate(Array.isArray(c.categories) ? (c.categories as string[]) : [], relevantCats)).length
      : candidates.length;

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectRelevant = () => {
    const relevant = new Set<string>();
    for (const c of candidates) {
      const cats = Array.isArray(c.categories) ? (c.categories as string[]) : [];
      if (isRelevantCandidate(cats, relevantCats)) relevant.add(String(c.arxiv_id ?? ""));
    }
    setSelected(relevant);
  };

  const handleSubmit = () => {
    if (selected.size === 0 || submitted) return;
    setSubmitted(true);
    const ids = Array.from(selected).join(", ");
    sendMessage(`请将以下论文入库：${ids}`).catch(() => {
      setSubmitted(false);
    });
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-ink-secondary text-[11px] font-medium">
          {candidates.length} 篇候选论文
          {relevantCats.size > 0 && relevantCount < candidates.length && (
            <span className="text-success ml-1">（{relevantCount} 篇高相关）</span>
          )}
        </p>
        <div className="flex items-center gap-1.5">
          {relevantCats.size > 0 && relevantCount < candidates.length && (
            <button type="button" onClick={selectRelevant} className="text-success hover:bg-success/10 rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors">
              仅选相关
            </button>
          )}
          <button
            type="button"
            onClick={() => setSelected(allSelected ? new Set() : new Set(candidates.map((c) => String(c.arxiv_id ?? ""))))}
            className="text-primary hover:bg-primary/10 rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors"
          >
            {allSelected ? "取消全选" : "全选"}
          </button>
          <span className="text-ink-tertiary text-[10px]">已选 {selected.size}/{candidates.length}</span>
        </div>
      </div>
      <div className="max-h-64 space-y-1 overflow-y-auto">
        {candidates.map((p, i) => {
          const aid = String(p.arxiv_id ?? "");
          const isChecked = selected.has(aid);
          const cats = Array.isArray(p.categories) ? (p.categories as string[]) : [];
          const isRelevant = isRelevantCandidate(cats, relevantCats);
          return (
            <label
              key={aid || i}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2 text-[11px] transition-colors",
                isChecked ? "bg-primary/5 border border-primary/20" : "bg-surface hover:bg-hover border border-transparent",
                !isRelevant && relevantCats.size > 0 && "opacity-60"
              )}
            >
              <input
                type="checkbox"
                checked={isChecked}
                onChange={() => toggle(aid)}
                disabled={submitted}
                className="border-border text-primary focus:ring-primary/20 mt-1 h-3.5 w-3.5 shrink-0 rounded"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-1.5">
                  <p className="text-ink flex-1 leading-snug font-medium">{String(p.title ?? "")}</p>
                  {isRelevant && relevantCats.size > 0 && (
                    <span className="bg-success/10 text-success shrink-0 rounded px-1.5 py-0.5 text-[9px] font-medium">相关</span>
                  )}
                </div>
                <div className="text-ink-tertiary mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px]">
                  {p.arxiv_id ? <span className="font-mono">{aid}</span> : null}
                  {p.publication_date ? <span>{String(p.publication_date)}</span> : null}
                  {cats.slice(0, 3).map((c) => (
                    <span key={c} className={cn("rounded px-1 py-px font-mono text-[9px]", relevantCats.has(c) ? "bg-primary/10 text-primary" : "bg-ink/5 text-ink-tertiary")}>
                      {c}
                    </span>
                  ))}
                </div>
                {Array.isArray(p.authors) && (p.authors as string[]).length > 0 && (
                  <p className="text-ink-tertiary mt-0.5 truncate text-[10px]">{(p.authors as string[]).slice(0, 3).join(", ")}</p>
                )}
              </div>
            </label>
          );
        })}
      </div>
      {!submitted ? (
        <button
          type="button"
          onClick={handleSubmit}
          disabled={selected.size === 0 || loading}
          className="bg-primary hover:bg-primary-hover flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium text-white transition-all disabled:opacity-50"
        >
          <Download className="h-4 w-4" />
          入库选中 ({selected.size} 篇)
        </button>
      ) : (
        <div className="bg-primary/10 text-primary flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium">
          <Loader2 className="h-4 w-4 animate-spin" />
          已发送请求，等待确认后开始入库…
        </div>
      )}
    </div>
  );
});

const StepDataView = memo(function StepDataView({ data, toolName }: { data: Record<string, unknown>; toolName: string }) {
  const navigate = useNavigate();

  const jsonPreview = useMemo(() => JSON.stringify(data, null, 2), [data]);

  if (toolName === "search_papers" && Array.isArray(data.papers)) {
    return <PaperListView papers={data.papers as Array<Record<string, unknown>>} label={`找到 ${(data.papers as unknown[]).length} 篇论文`} />;
  }
  if (toolName === "search_arxiv" && Array.isArray(data.candidates)) {
    return <ArxivCandidateSelector candidates={data.candidates as Array<Record<string, unknown>>} query={String(data.query ?? "")} />;
  }
  if (toolName === "ingest_arxiv" && data.total !== undefined) {
    return <IngestResultView data={data} />;
  }
  if (toolName === "get_system_status") {
    return (
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "论文", value: data.paper_count, color: "text-primary" },
          { label: "已向量化", value: data.embedded_count, color: "text-success" },
          { label: "主题", value: data.topic_count, color: "text-blue-600 dark:text-blue-400" },
        ].map((s) => (
          <div key={s.label} className="bg-surface flex flex-col items-center rounded-lg py-2">
            <span className={cn("text-base font-bold", s.color)}>{String(s.value ?? 0)}</span>
            <span className="text-ink-tertiary text-[10px]">{s.label}</span>
          </div>
        ))}
      </div>
    );
  }
  if (toolName === "ask_knowledge_base" && data.markdown) {
    const evidence = Array.isArray(data.evidence) ? (data.evidence as Array<Record<string, unknown>>) : [];
    const rounds = data.rounds as number | undefined;
    return (
      <div className="space-y-2">
        {rounds && rounds > 1 && (
          <div className="text-primary flex items-center gap-1.5 text-[10px]">
            <TrendingUp className="h-3 w-3" />
            <span>经过 {rounds} 轮迭代检索优化</span>
          </div>
        )}
        <div className="prose prose-sm dark:prose-invert max-w-none text-[12px] leading-relaxed">
          <Suspense fallback={<div className="bg-surface h-4 animate-pulse rounded" />}><Markdown>{String(data.markdown)}</Markdown></Suspense>
        </div>
        {evidence.length > 0 && (
          <div className="border-border-light border-t pt-2">
            <p className="text-ink-tertiary mb-1 text-[10px] font-medium">引用 {evidence.length} 篇论文</p>
            <div className="flex flex-wrap gap-1">
              {evidence.slice(0, 8).map((e) => (
                <button type="button" key={String(e.paper_id ?? "")} onClick={() => e.paper_id && navigate(`/papers/${String(e.paper_id)}`)} className="bg-surface text-ink-secondary hover:bg-hover hover:text-primary max-w-[200px] truncate rounded px-1.5 py-0.5 text-[9px] transition-colors" title={String(e.title ?? "")}>
                  {String(e.title ?? "").slice(0, 40)}{String(e.title ?? "").length > 40 ? "..." : ""}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }
  if (toolName === "list_topics" && Array.isArray(data.topics)) {
    const topics = data.topics as Array<Record<string, unknown>>;
    return (
      <div className="space-y-1">
        {topics.map((t) => (
          <div key={String(t.name ?? "")} className="bg-surface flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px]">
            <Hash className="text-primary h-3 w-3 shrink-0" />
            <span className="text-ink font-medium">{String(t.name ?? "")}</span>
            {t.paper_count !== undefined && <span className="text-ink-tertiary">{String(t.paper_count)} 篇</span>}
            {t.enabled !== undefined && (
              <span className={cn("ml-auto rounded px-1.5 py-0.5 text-[9px]", t.enabled ? "bg-success/10 text-success" : "bg-ink/5 text-ink-tertiary")}>
                {t.enabled ? "已订阅" : "未订阅"}
              </span>
            )}
          </div>
        ))}
      </div>
    );
  }
  if (toolName === "get_timeline" && Array.isArray(data.timeline)) {
    const items = data.timeline as Array<Record<string, unknown>>;
    return (
      <div className="max-h-48 space-y-1 overflow-y-auto">
        {items.map((p) => (
          <button type="button" key={String(p.paper_id ?? "")} onClick={() => p.paper_id && navigate(`/papers/${String(p.paper_id)}`)} className="bg-surface hover:bg-hover flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11px] transition-colors">
            <span className="text-primary shrink-0 font-mono text-[10px]">{String(p.year ?? "?")}</span>
            <span className="text-ink truncate">{String(p.title ?? "")}</span>
          </button>
        ))}
      </div>
    );
  }
  if (toolName === "get_similar_papers") {
    const items = Array.isArray(data.items) ? (data.items as Array<Record<string, unknown>>) : [];
    const ids = Array.isArray(data.similar_ids) ? (data.similar_ids as string[]) : [];
    if (items.length > 0) {
      return (
        <div className="space-y-1">
          {items.map((p) => (
            <button type="button" key={String(p.id ?? "")} onClick={() => p.id && navigate(`/papers/${String(p.id)}`)} className="bg-surface hover:bg-hover flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11px] transition-colors">
              <Star className="h-3 w-3 shrink-0 text-amber-500" />
              <span className="text-ink truncate">{String(p.title ?? "")}</span>
            </button>
          ))}
        </div>
      );
    }
    if (ids.length > 0) return <p className="text-ink-secondary text-[11px]">找到 {ids.length} 篇相似论文</p>;
  }
  if (toolName === "get_citation_tree" && data.nodes) {
    const nodes = Array.isArray(data.nodes) ? data.nodes.length : 0;
    const edges = Array.isArray(data.edges) ? data.edges.length : 0;
    return (
      <div className="flex items-center gap-3 text-[11px]">
        <span className="text-ink font-medium">{nodes} 个节点</span>
        <span className="text-ink-tertiary">{edges} 条引用关系</span>
      </div>
    );
  }
  if (toolName === "suggest_keywords" && Array.isArray(data.suggestions)) {
    const suggestions = data.suggestions as Array<Record<string, unknown>>;
    return (
      <div className="space-y-1.5">
        {suggestions.map((s) => (
          <div key={String(s.name ?? "")} className="bg-surface rounded-lg px-2.5 py-2 text-[11px]">
            <p className="text-ink font-medium">{String(s.name ?? "")}</p>
            <p className="text-primary mt-0.5 font-mono text-[10px]">{String(s.query ?? "")}</p>
            {s.reason !== undefined && <p className="text-ink-tertiary mt-0.5 text-[10px]">{String(s.reason)}</p>}
          </div>
        ))}
      </div>
    );
  }
  if ((toolName === "skim_paper" || toolName === "deep_read_paper") && data.one_liner) {
    return (
      <div className="text-[11px]">
        <p className="text-ink font-medium">{String(data.one_liner)}</p>
        {data.novelty !== undefined && <p className="text-ink-secondary mt-1"><span className="font-medium">创新点:</span> {String(data.novelty)}</p>}
        {data.methodology !== undefined && <p className="text-ink-secondary mt-0.5"><span className="font-medium">方法:</span> {String(data.methodology)}</p>}
      </div>
    );
  }
  if (toolName === "reasoning_analysis" && data.reasoning_steps) {
    const steps = Array.isArray(data.reasoning_steps) ? (data.reasoning_steps as Array<Record<string, unknown>>) : [];
    return (
      <div className="max-h-48 space-y-1.5 overflow-y-auto">
        {steps.slice(0, 6).map((s) => (
          <div key={String(s.step_name ?? s.claim ?? "")} className="bg-surface rounded-lg px-2.5 py-1.5 text-[11px]">
            <p className="text-ink font-medium">{String(s.step_name ?? s.claim ?? "步骤")}</p>
            {s.evidence !== undefined && <p className="text-ink-tertiary mt-0.5 truncate text-[10px]">{String(s.evidence)}</p>}
          </div>
        ))}
      </div>
    );
  }
  if (toolName === "analyze_figures" && Array.isArray(data.figures)) {
    const figs = data.figures as Array<Record<string, unknown>>;
    return (
      <div className="space-y-1">
        {figs.map((f) => (
          <div key={String(f.figure_type ?? "")} className="bg-surface rounded-lg px-2.5 py-1.5 text-[11px]">
            <p className="text-ink font-medium">{String(f.figure_type ?? "图表")} — p.{String(f.page ?? "?")}</p>
            <p className="text-ink-tertiary mt-0.5 truncate text-[10px]">{String(f.description ?? f.analysis ?? "")}</p>
          </div>
        ))}
      </div>
    );
  }
  if (toolName === "identify_research_gaps" && data.analysis) {
    const analysis = data.analysis as Record<string, unknown>;
    const gaps = Array.isArray(analysis.research_gaps) ? (analysis.research_gaps as Array<Record<string, unknown>>) : [];
    return (
      <div className="space-y-1.5">
        {gaps.slice(0, 5).map((g) => (
          <div key={String(g.gap_title ?? g.title ?? "")} className="bg-surface rounded-lg px-2.5 py-1.5 text-[11px]">
            <p className="text-ink font-medium">{String(g.gap_title ?? g.title ?? "空白")}</p>
            <p className="text-ink-tertiary mt-0.5 truncate text-[10px]">{String(g.description ?? g.evidence ?? "")}</p>
          </div>
        ))}
      </div>
    );
  }
  if (toolName === "get_paper_detail" && data.title) {
    return (
      <div className="text-[11px]">
        <button type="button" onClick={() => data.id && navigate(`/papers/${String(data.id)}`)} className="text-primary font-medium hover:underline">
          {String(data.title)}
        </button>
        {data.abstract_zh !== undefined && <p className="text-ink-secondary mt-1 line-clamp-3">{String(data.abstract_zh)}</p>}
        <div className="text-ink-tertiary mt-1 flex flex-wrap gap-1.5 text-[10px]">
          {data.arxiv_id ? <span className="font-mono">{String(data.arxiv_id)}</span> : null}
          {data.read_status ? <span>{String(data.read_status)}</span> : null}
        </div>
      </div>
    );
  }
  if (toolName === "writing_assist" && data.content) {
    return (
      <div className="prose prose-sm dark:prose-invert max-h-48 max-w-none overflow-y-auto text-[12px]">
        <Suspense fallback={<div className="bg-surface h-4 animate-pulse rounded" />}><Markdown>{String(data.content)}</Markdown></Suspense>
      </div>
    );
  }
  return <pre className="bg-surface text-ink-secondary max-h-40 overflow-auto rounded-lg p-2.5 text-[11px]">{jsonPreview}</pre>;
});

export { getToolMeta, ArxivCandidateSelector, StepDataView, ActionConfirmCard };

const ActionConfirmCard = memo(function ActionConfirmCard({
  actionId,
  description,
  tool,
  args,
  isPending,
  isConfirming,
  onConfirm,
  onReject,
}: {
  actionId: string;
  description: string;
  tool: string;
  args?: Record<string, unknown>;
  isPending: boolean;
  isConfirming: boolean;
  onConfirm: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const meta = getToolMeta(tool);
  const Icon = meta.icon;
  return (
    <div className="py-2">
      <div
        className={cn(
          "bg-surface overflow-hidden rounded-xl border transition-all",
          isPending
            ? "border-warning/60 shadow-warning/10 animate-[confirm-glow_2s_ease-in-out_infinite] shadow-md"
            : "border-border"
        )}
      >
        <div
          className={cn(
            "flex items-center gap-2 px-3.5 py-2.5",
            isPending ? "bg-warning-light" : "bg-page"
          )}
        >
          <AlertTriangle
            className={cn(
              "h-3.5 w-3.5",
              isPending ? "text-warning animate-pulse" : "text-ink-tertiary"
            )}
          />
          <span className="text-ink text-xs font-semibold">
            {isPending ? "⚠️ 需要你的确认" : "已处理"}
          </span>
        </div>
        <div className="space-y-3 px-3.5 py-3">
          <div className="flex items-start gap-2.5">
            <div className="bg-warning-light flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
              <Icon className="text-warning h-4 w-4" />
            </div>
            <div>
              <p className="text-ink text-sm font-medium">{description}</p>
              {args && Object.keys(args).length > 0 && (
                <div className="bg-page mt-1.5 rounded-lg px-2.5 py-1.5">
                  {Object.entries(args).map(([k, v]) => (
                    <div key={k} className="flex gap-1.5 text-[11px]">
                      <span className="text-ink-secondary font-medium">{k}:</span>
                      <span className="text-ink-tertiary">
                        {typeof v === "string" ? v : JSON.stringify(v)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          {isPending && (
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onConfirm(actionId)}
                disabled={isConfirming}
                className="bg-primary hover:bg-primary-hover flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2 text-xs font-medium text-white transition-all disabled:opacity-50"
              >
                {isConfirming ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                )}
                确认执行
              </button>
              <button
                type="button"
                onClick={() => onReject(actionId)}
                disabled={isConfirming}
                className="border-border bg-surface text-ink-secondary hover:bg-hover flex flex-1 items-center justify-center gap-1.5 rounded-lg border py-2 text-xs font-medium transition-all disabled:opacity-50"
              >
                <XCircle className="h-3.5 w-3.5" />
                跳过
              </button>
            </div>
          )}
          {!isPending && (
            <div className="text-success flex items-center gap-1 text-[11px]">
              <CheckCircle2 className="h-3 w-3" />
              已处理
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
