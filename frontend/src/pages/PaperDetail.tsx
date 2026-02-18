/**
 * Paper Detail - 论文详情（含收藏、粗读/精读报告、图表解读）
 * @author Bamzc
 */
import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Card, CardHeader, Button, Badge, Spinner, Empty } from "@/components/ui";
import { PaperDetailSkeleton } from "@/components/Skeleton";
import Markdown from "@/components/Markdown";
import PdfReader from "@/components/PdfReader";
import { useToast } from "@/contexts/ToastContext";
import { paperApi, pipelineApi, type FigureAnalysisItem } from "@/services/api";
import type { Paper, SkimReport, DeepDiveReport, ReasoningChainResult } from "@/types";
import {
  ArrowLeft,
  ExternalLink,
  Eye,
  BookOpen,
  Cpu,
  Star,
  AlertTriangle,
  CheckCircle2,
  Lightbulb,
  FlaskConical,
  Microscope,
  Shield,
  Sparkles,
  Link2,
  Tag,
  Folder,
  Heart,
  Image as ImageIcon,
  BarChart3,
  Table2,
  FileCode2,
  Brain,
  ChevronDown,
  ChevronRight,
  TrendingUp,
  Target,
  ThumbsUp,
  ThumbsDown,
  Zap,
  FileSearch,
} from "lucide-react";

export default function PaperDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [paper, setPaper] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);
  const [skimReport, setSkimReport] = useState<SkimReport | null>(null);
  const [deepReport, setDeepReport] = useState<DeepDiveReport | null>(null);
  const [savedSkim, setSavedSkim] = useState<{ summary_md: string; skim_score: number | null; key_insights: Record<string, unknown> } | null>(null);
  const [savedDeep, setSavedDeep] = useState<{ deep_dive_md: string; key_insights: Record<string, unknown> } | null>(null);
  const [similarIds, setSimilarIds] = useState<string[]>([]);
  const [skimLoading, setSkimLoading] = useState(false);
  const [deepLoading, setDeepLoading] = useState(false);
  const [embedLoading, setEmbedLoading] = useState(false);
  const [embedDone, setEmbedDone] = useState<boolean | null>(null);
  const [similarLoading, setSimilarLoading] = useState(false);

  /* 图表解读 */
  const [figures, setFigures] = useState<FigureAnalysisItem[]>([]);
  const [figuresLoading, setFiguresLoading] = useState(false);
  const [figuresAnalyzing, setFiguresAnalyzing] = useState(false);

  /* 推理链分析 */
  const [reasoning, setReasoning] = useState<ReasoningChainResult | null>(null);
  const [reasoningLoading, setReasoningLoading] = useState(false);

  /* PDF 阅读器 */
  const [readerOpen, setReaderOpen] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      paperApi.detail(id),
      paperApi.getFigures(id).catch(() => ({ items: [] as FigureAnalysisItem[] })),
    ])
      .then(([p, figRes]) => {
        setPaper(p);
        setEmbedDone(p.has_embedding ?? false);
        if (p.skim_report) setSavedSkim(p.skim_report);
        if (p.deep_report) setSavedDeep(p.deep_report);
        setFigures(figRes.items);
        const rc = p.metadata?.reasoning_chain as ReasoningChainResult | undefined;
        if (rc) setReasoning(rc);
      })
      .catch(() => { toast("error", "加载论文详情失败"); })
      .finally(() => setLoading(false));
  }, [id, toast]);

  const handleSkim = async () => {
    if (!id) return;
    setSkimLoading(true);
    try {
      const report = await pipelineApi.skim(id);
      setSkimReport(report);
      toast("success", "粗读完成");
    } catch { toast("error", "粗读失败"); } finally { setSkimLoading(false); }
  };

  const handleDeep = async () => {
    if (!id) return;
    setDeepLoading(true);
    try {
      const report = await pipelineApi.deep(id);
      setDeepReport(report);
      toast("success", "精读完成");
    } catch { toast("error", "精读失败"); } finally { setDeepLoading(false); }
  };

  const handleEmbed = async () => {
    if (!id) return;
    setEmbedLoading(true);
    try {
      await pipelineApi.embed(id);
      setEmbedDone(true);
      toast("success", "嵌入完成");
    } catch { toast("error", "嵌入失败"); } finally { setEmbedLoading(false); }
  };

  const handleSimilar = async () => {
    if (!id) return;
    setSimilarLoading(true);
    try {
      const res = await paperApi.similar(id);
      setSimilarIds(res.similar_ids);
    } catch { toast("error", "获取相似论文失败"); } finally { setSimilarLoading(false); }
  };

  const handleAnalyzeFigures = async () => {
    if (!id) return;
    setFiguresAnalyzing(true);
    try {
      const res = await paperApi.analyzeFigures(id, 10);
      setFigures(res.items);
    } catch { toast("error", "图表分析失败"); } finally { setFiguresAnalyzing(false); }
  };

  const handleReasoning = async () => {
    if (!id) return;
    setReasoningLoading(true);
    try {
      const res = await paperApi.reasoningAnalysis(id);
      setReasoning(res.reasoning);
    } catch { toast("error", "推理链分析失败"); } finally { setReasoningLoading(false); }
  };

  const handleToggleFavorite = useCallback(async () => {
    if (!id || !paper) return;
    const prevFavorited = paper.favorited;
    try {
      const res = await paperApi.toggleFavorite(id);
      setPaper((prev) => prev ? { ...prev, favorited: res.favorited } : prev);
    } catch {
      toast("error", "收藏操作失败");
      setPaper((prev) => prev ? { ...prev, favorited: prevFavorited } : prev);
    }
  }, [id, paper, toast]);

  if (loading) return <PaperDetailSkeleton />;
  if (!paper) {
    return (
      <Empty
        title="论文不存在"
        description="该论文可能已被删除"
        action={<Button variant="secondary" onClick={() => navigate("/papers")}>返回列表</Button>}
      />
    );
  }

  const statusConfig: Record<string, { label: string; variant: "default" | "warning" | "success" }> = {
    unread: { label: "未读", variant: "default" },
    skimmed: { label: "已粗读", variant: "warning" },
    deep_read: { label: "已精读", variant: "success" },
  };
  const sc = statusConfig[paper.read_status] || statusConfig.unread;

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="flex items-center justify-between">
        <button onClick={() => navigate("/papers")} className="flex items-center gap-1.5 text-sm text-ink-secondary transition-colors hover:text-ink">
          <ArrowLeft className="h-4 w-4" /> 返回论文列表
        </button>
        <button onClick={handleToggleFavorite} className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors hover:bg-error/10" title={paper.favorited ? "取消收藏" : "收藏"}>
          <Heart className={`h-5 w-5 ${paper.favorited ? "fill-red-500 text-red-500" : "text-ink-tertiary"}`} />
          <span className={paper.favorited ? "text-red-500" : "text-ink-tertiary"}>{paper.favorited ? "已收藏" : "收藏"}</span>
        </button>
      </div>

      {/* 论文信息 */}
      <Card>
        <div className="flex items-start gap-2">
          <Badge variant={sc.variant}>{sc.label}</Badge>
          {paper.arxiv_id && (
            <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs text-primary hover:underline">
              <ExternalLink className="h-3 w-3" />{paper.arxiv_id}
            </a>
          )}
        </div>
        <h1 className="mt-3 text-2xl font-bold leading-snug text-ink">{paper.title}</h1>
        {paper.title_zh && <p className="mt-1 text-base text-ink-secondary">{paper.title_zh}</p>}
        {paper.abstract && <p className="mt-4 leading-relaxed text-ink-secondary">{paper.abstract}</p>}
        {paper.abstract_zh && (
          <div className="mt-3 rounded-xl border border-border bg-page p-4">
            <p className="mb-1 text-xs font-medium text-ink-tertiary">中文摘要</p>
            <p className="text-sm leading-relaxed text-ink-secondary">{paper.abstract_zh}</p>
          </div>
        )}
        {paper.publication_date && <p className="mt-3 text-sm text-ink-tertiary">发表日期: {paper.publication_date}</p>}
        {paper.topics && paper.topics.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Folder className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium text-ink-secondary">主题:</span>
            {paper.topics.map((t) => (
              <span key={t} className="inline-flex items-center rounded-md bg-primary-light px-2.5 py-1 text-xs font-medium text-primary">{t}</span>
            ))}
          </div>
        )}
        {paper.keywords && paper.keywords.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Tag className="h-4 w-4 text-ink-tertiary" />
            <span className="text-sm font-medium text-ink-secondary">关键词:</span>
            {paper.keywords.map((kw) => (
              <span key={kw} className="inline-flex items-center rounded-md bg-hover px-2.5 py-1 text-xs text-ink-secondary">{kw}</span>
            ))}
          </div>
        )}
        {paper.categories && paper.categories.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ink-secondary">ArXiv 分类:</span>
            {paper.categories.map((c) => (
              <span key={c} className="inline-flex items-center rounded-md border border-border bg-surface px-2 py-0.5 text-xs text-ink-tertiary">{c}</span>
            ))}
          </div>
        )}
      </Card>

      {/* 操作按钮 */}
      <div className="flex flex-wrap gap-3">
        {paper.pdf_path && (
          <Button icon={<FileSearch className="h-4 w-4" />} onClick={() => setReaderOpen(true)}>
            阅读原文
          </Button>
        )}
        <Button variant="secondary" icon={<Eye className="h-4 w-4" />} onClick={handleSkim} loading={skimLoading}>粗读 (Skim)</Button>
        <Button variant="secondary" icon={<BookOpen className="h-4 w-4" />} onClick={handleDeep} loading={deepLoading}>精读 (Deep Read)</Button>
        <Button variant="secondary" icon={<ImageIcon className="h-4 w-4" />} onClick={handleAnalyzeFigures} loading={figuresAnalyzing} disabled={!paper.pdf_path}>
          {figures.length > 0 ? `图表解读 (${figures.length})` : "图表解读"}
        </Button>
        <Button variant="secondary" icon={<Brain className="h-4 w-4" />} onClick={handleReasoning} loading={reasoningLoading}>
          {reasoning ? "推理链 ✓" : "推理链分析"}
        </Button>
        <Button variant="secondary" icon={<Cpu className="h-4 w-4" />} onClick={handleEmbed} loading={embedLoading} disabled={embedDone === true}>
          {embedDone ? "✓ 已向量化" : "向量嵌入 (Embed)"}
        </Button>
        <Button variant="secondary" icon={<Link2 className="h-4 w-4" />} onClick={handleSimilar} loading={similarLoading}>相似论文</Button>
      </div>

      {/* ========== 图表解读 ========== */}
      {(figures.length > 0 || figuresLoading || figuresAnalyzing) && (
        <Card className="animate-fade-in border-info/20">
          <CardHeader
            title="图表解读"
            description={figures.length > 0 ? `共 ${figures.length} 张图表` : "正在解读..."}
          />
          {figuresAnalyzing && <Spinner text="Vision 模型解读图表中..." />}
          {figures.length > 0 && (
            <div className="space-y-4">
              {figures.map((fig, i) => (
                <FigureCard key={fig.id || `${fig.page_number}-${i}`} figure={fig} index={i} />
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ========== 推理链深度分析 ========== */}
      {(reasoning || reasoningLoading) && (
        <Card className="animate-fade-in border-purple-500/20">
          <CardHeader
            title="推理链深度分析"
            description="分步推理：问题定义 → 方法推导 → 理论验证 → 实验评估 → 影响预测"
          />
          {reasoningLoading && <Spinner text="LLM 推理链分析中，请稍候..." />}
          {reasoning && <ReasoningPanel reasoning={reasoning} />}
        </Card>
      )}

      {/* 已保存的粗读报告 */}
      {savedSkim && !skimReport && (
        <Card className="animate-fade-in border-primary/20">
          <CardHeader
            title="粗读报告（已保存）"
            action={savedSkim.skim_score != null ? (
              <div className="flex items-center gap-1.5">
                <Star className="h-4 w-4 text-warning" />
                <span className="text-sm font-semibold text-ink">{savedSkim.skim_score.toFixed(2)}</span>
              </div>
            ) : null}
          />
          <div className="prose prose-sm max-w-none text-ink-secondary dark:prose-invert">
            <Markdown>{savedSkim.summary_md}</Markdown>
          </div>
        </Card>
      )}

      {/* 新执行的 Skim 报告 */}
      {skimReport && (
        <Card className="animate-fade-in border-primary/20">
          <CardHeader title="粗读报告" action={
            <div className="flex items-center gap-1.5">
              <Star className="h-4 w-4 text-warning" />
              <span className="text-sm font-semibold text-ink">{skimReport.relevance_score.toFixed(2)}</span>
            </div>
          } />
          <div className="space-y-4">
            <div className="rounded-xl bg-primary/5 p-4">
              <div className="flex items-start gap-2">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <p className="text-sm font-medium text-ink">{skimReport.one_liner}</p>
              </div>
            </div>
            <div>
              <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
                <Lightbulb className="h-4 w-4 text-warning" /> 创新点
              </h4>
              <ul className="space-y-1.5">
                {skimReport.innovations.map((item, i) => (
                  <li key={i} className="flex items-start gap-2 rounded-lg bg-page px-3 py-2 text-sm text-ink-secondary">
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />{item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      )}

      {/* 已保存的精读报告 */}
      {savedDeep && !deepReport && (
        <Card className="animate-fade-in border-info/20">
          <CardHeader title="精读报告（已保存）" />
          <div className="prose prose-sm max-w-none text-ink-secondary dark:prose-invert">
            <Markdown>{savedDeep.deep_dive_md}</Markdown>
          </div>
        </Card>
      )}

      {/* 新执行的 Deep Dive 报告 */}
      {deepReport && (
        <Card className="animate-fade-in border-info/20">
          <CardHeader title="精读报告" />
          <div className="space-y-4">
            <ReportSection icon={<FlaskConical className="h-4 w-4 text-info" />} title="方法论" content={deepReport.method_summary} />
            <ReportSection icon={<Microscope className="h-4 w-4 text-success" />} title="实验结果" content={deepReport.experiments_summary} />
            <ReportSection icon={<Sparkles className="h-4 w-4 text-warning" />} title="消融实验" content={deepReport.ablation_summary} />
            {deepReport.reviewer_risks.length > 0 && (
              <div>
                <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
                  <Shield className="h-4 w-4 text-error" /> 审稿风险
                </h4>
                <ul className="space-y-1.5">
                  {deepReport.reviewer_risks.map((risk, i) => (
                    <li key={i} className="flex items-start gap-2 rounded-lg bg-error-light px-3 py-2 text-sm text-ink-secondary">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-error" />{risk}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* 相似论文 */}
      {similarIds.length > 0 && (
        <Card className="animate-fade-in">
          <CardHeader title="相似论文" description={`找到 ${similarIds.length} 篇相似论文`} />
          <div className="space-y-2">
            {similarIds.map((sid) => (
              <button key={sid} onClick={() => navigate(`/papers/${sid}`)} className="flex w-full items-center justify-between rounded-lg bg-page px-4 py-3 text-left transition-colors hover:bg-hover">
                <span className="text-sm text-ink">{sid}</span>
                <ExternalLink className="h-3.5 w-3.5 text-ink-tertiary" />
              </button>
            ))}
          </div>
        </Card>
      )}

      {/* PDF 阅读器 */}
      {readerOpen && paper.pdf_path && (
        <PdfReader
          paperId={id!}
          paperTitle={paper.title}
          onClose={() => setReaderOpen(false)}
        />
      )}
    </div>
  );
}

/* ========== 图表解读卡片 ========== */
const TYPE_ICONS: Record<string, React.ReactNode> = {
  figure: <ImageIcon className="h-4 w-4 text-info" />,
  table: <Table2 className="h-4 w-4 text-warning" />,
  algorithm: <FileCode2 className="h-4 w-4 text-success" />,
  equation: <BarChart3 className="h-4 w-4 text-primary" />,
};

const TYPE_LABELS: Record<string, string> = {
  figure: "图表",
  table: "表格",
  algorithm: "算法",
  equation: "公式",
};

function FigureCard({ figure, index }: { figure: FigureAnalysisItem; index: number }) {
  const [expanded, setExpanded] = useState(index < 3);

  return (
    <div className="rounded-xl border border-border bg-page/50 transition-all">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface">
          {TYPE_ICONS[figure.image_type] || TYPE_ICONS.figure}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-info-light px-2 py-0.5 text-[10px] font-medium text-info">
              {TYPE_LABELS[figure.image_type] || figure.image_type}
            </span>
            <span className="text-[10px] text-ink-tertiary">第 {figure.page_number} 页</span>
          </div>
          {figure.caption && (
            <p className="mt-0.5 truncate text-xs font-medium text-ink">{figure.caption}</p>
          )}
        </div>
        <span className="shrink-0 text-[10px] text-ink-tertiary">{expanded ? "收起" : "展开"}</span>
      </button>
      {expanded && (
        <div className="border-t border-border px-4 py-3">
          <div className="prose prose-sm max-w-none text-ink-secondary dark:prose-invert">
            <Markdown>{figure.description}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

/* ========== 推理链面板 ========== */
function ReasoningPanel({ reasoning }: { reasoning: ReasoningChainResult }) {
  const steps = reasoning.reasoning_steps ?? [];
  const mc = reasoning.method_chain ?? {} as Record<string, string>;
  const ec = reasoning.experiment_chain ?? {} as Record<string, string>;
  const ia = reasoning.impact_assessment ?? {} as Record<string, unknown>;

  const novelty = (ia.novelty_score as number) ?? 0;
  const rigor = (ia.rigor_score as number) ?? 0;
  const impact = (ia.impact_score as number) ?? 0;
  const overall = (ia.overall_assessment as string) ?? "";
  const strengths = (ia.strengths as string[]) ?? [];
  const weaknesses = (ia.weaknesses as string[]) ?? [];
  const suggestions = (ia.future_suggestions as string[]) ?? [];

  return (
    <div className="space-y-6">
      {/* 评分概览 */}
      <div className="grid grid-cols-3 gap-4">
        <ScoreCard label="创新性" score={novelty} icon={<Zap className="h-4 w-4" />} color="text-purple-500" bg="bg-purple-500/10" />
        <ScoreCard label="严谨性" score={rigor} icon={<Target className="h-4 w-4" />} color="text-blue-500" bg="bg-blue-500/10" />
        <ScoreCard label="影响力" score={impact} icon={<TrendingUp className="h-4 w-4" />} color="text-orange-500" bg="bg-orange-500/10" />
      </div>

      {/* 综合评估 */}
      {overall && (
        <div className="rounded-xl bg-page p-4">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-secondary">{overall}</p>
        </div>
      )}

      {/* 推理步骤 */}
      {steps.length > 0 && (
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
            <Brain className="h-4 w-4 text-purple-500" /> 推理过程
          </h4>
          <div className="space-y-2">
            {steps.map((step, i) => (
              <ReasoningStepCard key={i} step={step} index={i} />
            ))}
          </div>
        </div>
      )}

      {/* 方法论推导链 */}
      {Object.values(mc).some(Boolean) && (
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
            <FlaskConical className="h-4 w-4 text-info" /> 方法论推导链
          </h4>
          <div className="space-y-3">
            {mc.problem_definition && <ChainItem label="问题定义" text={mc.problem_definition} />}
            {mc.core_hypothesis && <ChainItem label="核心假设" text={mc.core_hypothesis} />}
            {mc.method_derivation && <ChainItem label="方法推导" text={mc.method_derivation} />}
            {mc.theoretical_basis && <ChainItem label="理论基础" text={mc.theoretical_basis} />}
            {mc.innovation_analysis && <ChainItem label="创新性分析" text={mc.innovation_analysis} />}
          </div>
        </div>
      )}

      {/* 实验验证链 */}
      {Object.values(ec).some(Boolean) && (
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
            <Microscope className="h-4 w-4 text-success" /> 实验验证链
          </h4>
          <div className="space-y-3">
            {ec.experimental_design && <ChainItem label="实验设计" text={ec.experimental_design} />}
            {ec.baseline_fairness && <ChainItem label="基线公平性" text={ec.baseline_fairness} />}
            {ec.result_validation && <ChainItem label="结果验证" text={ec.result_validation} />}
            {ec.ablation_insights && <ChainItem label="消融洞察" text={ec.ablation_insights} />}
          </div>
        </div>
      )}

      {/* 优势与不足 */}
      <div className="grid gap-4 sm:grid-cols-2">
        {strengths.length > 0 && (
          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
              <ThumbsUp className="h-4 w-4 text-success" /> 优势
            </h4>
            <ul className="space-y-1.5">
              {strengths.map((s, i) => (
                <li key={i} className="flex items-start gap-2 rounded-lg bg-success/5 px-3 py-2 text-sm text-ink-secondary">
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />{s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {weaknesses.length > 0 && (
          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
              <ThumbsDown className="h-4 w-4 text-error" /> 不足
            </h4>
            <ul className="space-y-1.5">
              {weaknesses.map((w, i) => (
                <li key={i} className="flex items-start gap-2 rounded-lg bg-error/5 px-3 py-2 text-sm text-ink-secondary">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-error" />{w}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* 未来建议 */}
      {suggestions.length > 0 && (
        <div>
          <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
            <Lightbulb className="h-4 w-4 text-warning" /> 未来研究建议
          </h4>
          <ul className="space-y-1.5">
            {suggestions.map((f, i) => (
              <li key={i} className="flex items-start gap-2 rounded-lg bg-warning/5 px-3 py-2 text-sm text-ink-secondary">
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />{f}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ReasoningStepCard({ step, index }: { step: { step: string; thinking: string; conclusion: string }; index: number }) {
  const [open, setOpen] = useState(index < 2);

  return (
    <div className="rounded-xl border border-border bg-page/50 transition-all">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-3 text-left">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-purple-500/10 text-xs font-bold text-purple-500">
          {index + 1}
        </div>
        <span className="flex-1 text-sm font-medium text-ink">{step.step}</span>
        {open ? <ChevronDown className="h-4 w-4 text-ink-tertiary" /> : <ChevronRight className="h-4 w-4 text-ink-tertiary" />}
      </button>
      {open && (
        <div className="space-y-3 border-t border-border px-4 py-3">
          {step.thinking && (
            <div className="rounded-lg bg-purple-500/5 px-3 py-2">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-purple-500">思考过程</p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-secondary">{step.thinking}</p>
            </div>
          )}
          {step.conclusion && (
            <div className="rounded-lg bg-success/5 px-3 py-2">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-success">结论</p>
              <p className="text-sm leading-relaxed text-ink-secondary">{step.conclusion}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ScoreCard({ label, score, icon, color, bg }: { label: string; score: number; icon: React.ReactNode; color: string; bg: string }) {
  const pct = Math.round(score * 100);
  return (
    <div className="rounded-xl border border-border bg-page p-4 text-center">
      <div className={`mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full ${bg} ${color}`}>{icon}</div>
      <div className="text-2xl font-bold text-ink">{pct}<span className="text-sm text-ink-tertiary">%</span></div>
      <div className="mt-1 text-xs text-ink-tertiary">{label}</div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-hover">
        <div className={`h-full rounded-full ${score > 0.7 ? "bg-success" : score > 0.4 ? "bg-warning" : "bg-error"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ChainItem({ label, text }: { label: string; text: string }) {
  return (
    <div className="rounded-lg border border-border bg-page/50 px-4 py-3">
      <p className="mb-1 text-xs font-semibold text-ink-tertiary">{label}</p>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-secondary">{text}</p>
    </div>
  );
}

/* ========== 通用报告区块 ========== */
function ReportSection({ icon, title, content }: { icon: React.ReactNode; title: string; content: string }) {
  return (
    <div>
      <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">{icon}{title}</h4>
      <div className="rounded-xl bg-page px-4 py-3">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-secondary">{content}</p>
      </div>
    </div>
  );
}
