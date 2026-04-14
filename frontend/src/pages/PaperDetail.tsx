/**
 * Paper Detail - 论文详情（重构版：进度面板 + Tab 化报告 + 统一布局）
 * @author Color2333
 */
import { useEffect, useState, useCallback, useRef, lazy, Suspense } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Card, CardHeader, Button, Badge, Empty } from "@/components/ui";
import { Tabs } from "@/components/ui/Tabs";
import { PaperDetailSkeleton } from "@/components/Skeleton";

// 重型依赖懒加载，只在真正需要时加载
const Markdown = lazy(() => import("@/components/Markdown"));
const PdfReader = lazy(() => import("@/components/PdfReader"));
import { useToast } from "@/contexts/ToastContext";
import { paperApi, pipelineApi, tagApi } from "@/services/api";
import type {
  Paper,
  SkimReport,
  DeepDiveReport,
  ReasoningChainResult,
  FigureAnalysisItem,
  Tag as TagType,
} from "@/types";
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
  X,
  Loader2,
  Check,
  Download,
  Plus,
} from "lucide-react";

/* ================================================================
 * PipelineProgress — 内联进度面板
 * ================================================================ */

const SKIM_STAGES = ["提取论文摘要...", "分析方法论...", "评估创新点...", "生成报告..."];
const DEEP_STAGES = ["深度分析方法论...", "评估实验设计...", "识别审稿风险...", "综合评估..."];
const FIGURE_STAGES = ["提取 PDF 图表...", "Vision 模型分析中...", "整理解读结果..."];

function PipelineProgress({
  type,
  onCancel,
}: {
  type: "skim" | "deep" | "figure" | "reasoning" | "embed";
  onCancel?: () => void;
}) {
  const [progress, setProgress] = useState(0);
  const [stageIdx, setStageIdx] = useState(0);

  const stages =
    type === "skim"
      ? SKIM_STAGES
      : type === "deep"
        ? DEEP_STAGES
        : type === "figure"
          ? FIGURE_STAGES
          : type === "reasoning"
            ? ["构建推理链...", "分析方法推导...", "评估影响力...", "生成评估报告..."]
            : ["计算向量嵌入..."];

  const estimate =
    type === "skim"
      ? "10-20 秒"
      : type === "deep"
        ? "30-60 秒"
        : type === "figure"
          ? "30-60 秒"
          : type === "reasoning"
            ? "20-40 秒"
            : "5-10 秒";

  useEffect(() => {
    const progressTimer = setInterval(() => {
      setProgress((p) => (p < 90 ? p + Math.random() * 3 + 0.5 : p));
    }, 500);
    const stageTimer = setInterval(
      () => {
        setStageIdx((i) => (i < stages.length - 1 ? i + 1 : i));
      },
      type === "embed" ? 3000 : 8000
    );
    return () => {
      clearInterval(progressTimer);
      clearInterval(stageTimer);
    };
  }, [stages.length, type]);

  return (
    <div className="animate-fade-in border-primary/20 bg-primary/5 dark:bg-primary/10 rounded-2xl border p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center">
            <svg className="h-10 w-10 -rotate-90" viewBox="0 0 36 36">
              <circle
                cx="18"
                cy="18"
                r="15.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="text-border"
              />
              <circle
                cx="18"
                cy="18"
                r="15.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                className="text-primary transition-all duration-500"
                strokeDasharray={`${progress} ${100 - progress}`}
                strokeLinecap="round"
              />
            </svg>
            <span className="text-primary absolute text-[10px] font-bold">
              {Math.round(progress)}%
            </span>
          </div>
          <div>
            <p className="text-ink text-sm font-medium">{stages[stageIdx]}</p>
            <p className="text-ink-tertiary text-xs">预计 {estimate}</p>
          </div>
        </div>
        {onCancel && (
          <button
            onClick={onCancel}
            className="text-ink-tertiary hover:bg-hover hover:text-ink flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs transition-colors"
          >
            <X className="h-3.5 w-3.5" /> 取消
          </button>
        )}
      </div>
      <div className="bg-border mt-3 h-1.5 overflow-hidden rounded-full">
        <div
          className="from-primary h-full rounded-full bg-gradient-to-r to-blue-400 transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

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

/* ================================================================
 * 主组件
 * ================================================================ */

export default function PaperDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);

  const [skimReport, setSkimReport] = useState<SkimReport | null>(null);
  const [deepReport, setDeepReport] = useState<DeepDiveReport | null>(null);
  const [savedSkim, setSavedSkim] = useState<{
    summary_md: string;
    skim_score: number | null;
    key_insights: Record<string, unknown>;
  } | null>(null);
  const [savedDeep, setSavedDeep] = useState<{
    deep_dive_md: string;
    key_insights: Record<string, unknown>;
  } | null>(null);
  const [similarIds, setSimilarIds] = useState<string[]>([]);
  const [similarItems, setSimilarItems] = useState<
    { id: string; title: string; arxiv_id?: string; read_status?: string }[]
  >([]);

  const [skimLoading, setSkimLoading] = useState(false);
  const [deepLoading, setDeepLoading] = useState(false);
  const [embedLoading, setEmbedLoading] = useState(false);
  const [embedDone, setEmbedDone] = useState<boolean | null>(null);
  const [similarLoading, setSimilarLoading] = useState(false);

  const [figures, setFigures] = useState<FigureAnalysisItem[]>([]);
  const [figuresAnalyzing, setFiguresAnalyzing] = useState(false);

  const [reasoning, setReasoning] = useState<ReasoningChainResult | null>(null);
  const [reasoningLoading, setReasoningLoading] = useState(false);

  const [readerOpen, setReaderOpen] = useState(false);
  const [reportTab, setReportTab] = useState("skim");

  /* 标签相关 */
  const [allTags, setAllTags] = useState<TagType[]>([]);
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const [newTagColor, setNewTagColor] = useState("#3b82f6");
  const [tagsLoading, setTagsLoading] = useState(false);

  const skimAbort = useRef<AbortController | null>(null);
  const deepAbort = useRef<AbortController | null>(null);

  /* 加载标签列表 */
  const loadTags = useCallback(async () => {
    try {
      const res = await tagApi.list();
      setAllTags(res.items);
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      paperApi.detail(id),
      paperApi.getFigures(id).catch(() => ({ items: [] as FigureAnalysisItem[] })),
      tagApi.list().catch(() => ({ items: [] as TagType[] })),
    ])
      .then(([p, figRes, tagRes]) => {
        setPaper(p);
        setEmbedDone(p.has_embedding ?? false);
        if (p.skim_report) setSavedSkim(p.skim_report);
        if (p.deep_report) setSavedDeep(p.deep_report);
        setFigures(figRes.items);
        setAllTags(tagRes.items);
        const rc = p.metadata?.reasoning_chain as ReasoningChainResult | undefined;
        if (rc) setReasoning(rc);
        if (p.deep_report) setReportTab("deep");
        else if (p.skim_report) setReportTab("skim");
      })
      .catch(() => {
        toast("error", "加载论文详情失败");
      })
      .finally(() => setLoading(false));
  }, [id, toast]);

  const handleSkim = async () => {
    if (!id) return;
    setSkimLoading(true);
    setReportTab("skim");
    try {
      const report = await pipelineApi.skim(id);
      setSkimReport(report);
      // 刷新论文信息，更新粗读报告
      const updated = await paperApi.detail(id);
      setPaper(updated);
      if (updated.skim_report) setSavedSkim(updated.skim_report);
      toast("success", "粗读完成");
    } catch {
      toast("error", "粗读失败");
    } finally {
      setSkimLoading(false);
    }
  };

  const handleDeep = async () => {
    if (!id) return;
    setDeepLoading(true);
    setReportTab("deep");
    try {
      const report = await pipelineApi.deep(id);
      setDeepReport(report);
      toast("success", "精读完成");
    } catch {
      toast("error", "精读失败");
    } finally {
      setDeepLoading(false);
    }
  };

  const handleEmbed = async () => {
    if (!id) return;
    setEmbedLoading(true);
    try {
      await pipelineApi.embed(id);
      setEmbedDone(true);
      toast("success", "嵌入完成");
    } catch {
      toast("error", "嵌入失败");
    } finally {
      setEmbedLoading(false);
    }
  };

  const handleSimilar = async () => {
    if (!id) return;
    setSimilarLoading(true);
    setReportTab("similar");
    try {
      const res = await paperApi.similar(id);
      setSimilarIds(res.similar_ids);
      if (res.items) setSimilarItems(res.items);
    } catch {
      toast("error", "获取相似论文失败");
    } finally {
      setSimilarLoading(false);
    }
  };

  const handleAnalyzeFigures = async () => {
    if (!id) return;
    setFiguresAnalyzing(true);
    setReportTab("figures");
    try {
      const res = await paperApi.analyzeFigures(id, 10);
      setFigures(res.items);
      toast("success", `解读完成，共 ${res.items.length} 张图表`);
    } catch {
      toast("error", "图表分析失败");
    } finally {
      setFiguresAnalyzing(false);
    }
  };

  const [autoAnalyzing, setAutoAnalyzing] = useState(false);
  const [autoStage, setAutoStage] = useState("");

  const handleAutoAnalyze = async () => {
    if (!id || !paper) return;
    setAutoAnalyzing(true);
    try {
      // Step 1: 向量嵌入（不需要 PDF）
      if (!paper.has_embedding) {
        setAutoStage("向量嵌入中...");
        setEmbedLoading(true);
        try {
          await pipelineApi.embed(id);
          setEmbedDone(true);
        } catch {}
        setEmbedLoading(false);
      }

      // Step 2: 粗读（不需要 PDF）
      if (!hasSkim) {
        setAutoStage("粗读分析中...");
        setSkimLoading(true);
        setReportTab("skim");
        try {
          const r = await pipelineApi.skim(id);
          setSkimReport(r);
        } catch {}
        setSkimLoading(false);
      }

      if (paper.pdf_path) {
        // Step 3: 精读（需要 PDF）
        if (!hasDeep) {
          setAutoStage("精读分析中...");
          setDeepLoading(true);
          setReportTab("deep");
          try {
            const r = await pipelineApi.deep(id);
            setDeepReport(r);
          } catch {}
          setDeepLoading(false);
        }

        // Step 4: 图表解读（需要 PDF）
        if (figures.length === 0) {
          setAutoStage("图表解读中...");
          setFiguresAnalyzing(true);
          setReportTab("figures");
          try {
            const r = await paperApi.analyzeFigures(id, 10);
            setFigures(r.items);
          } catch {}
          setFiguresAnalyzing(false);
        }

        // Step 5: 推理链（需要 PDF）
        if (!reasoning) {
          setAutoStage("推理链分析中...");
          setReasoningLoading(true);
          setReportTab("reasoning");
          try {
            const r = await paperApi.reasoningAnalysis(id);
            setReasoning(r.reasoning);
          } catch {}
          setReasoningLoading(false);
        }
      }

      setAutoStage("");
      toast("success", "深度分析完成");
      setReportTab("skim");
    } finally {
      setAutoAnalyzing(false);
      setAutoStage("");
    }
  };

  const handleReasoning = async () => {
    if (!id) return;
    setReasoningLoading(true);
    setReportTab("reasoning");
    try {
      const res = await paperApi.reasoningAnalysis(id);
      setReasoning(res.reasoning);
      toast("success", "推理链分析完成");
    } catch {
      toast("error", "推理链分析失败");
    } finally {
      setReasoningLoading(false);
    }
  };

  const handleToggleFavorite = useCallback(async () => {
    if (!id || !paper) return;
    const prevFavorited = paper.favorited;
    try {
      const res = await paperApi.toggleFavorite(id);
      setPaper((prev) => (prev ? { ...prev, favorited: res.favorited } : prev));
    } catch {
      toast("error", "收藏操作失败");
      setPaper((prev) => (prev ? { ...prev, favorited: prevFavorited } : prev));
    }
  }, [id, paper, toast]);

  /* 标签管理 */
  const handleToggleTag = useCallback(
    async (tagId: string, isSelected: boolean) => {
      if (!id) return;
      try {
        if (isSelected) {
          await tagApi.removePaperTag(id, tagId);
          setPaper((prev) =>
            prev
              ? {
                  ...prev,
                  tags: (prev.tags || []).filter((t) => t.id !== tagId),
                }
              : prev
          );
        } else {
          const res = await tagApi.addPaperTag(id, tagId);
          setPaper((prev) =>
            prev
              ? {
                  ...prev,
                  tags: [...(prev.tags || []), res.tag],
                }
              : prev
          );
        }
      } catch {
        toast("error", "标签操作失败");
      }
    },
    [id, toast]
  );

  const handleCreateTag = useCallback(async () => {
    if (!newTagName.trim()) {
      toast("error", "标签名称不能为空");
      return;
    }
    setTagsLoading(true);
    try {
      const newTag = await tagApi.create(newTagName.trim(), newTagColor);
      setAllTags((prev) => [...prev, newTag]);
      if (id) {
        const res = await tagApi.addPaperTag(id, newTag.id);
        setPaper((prev) =>
          prev
            ? {
                ...prev,
                tags: [...(prev.tags || []), res.tag],
              }
            : prev
        );
      }
      toast("success", "标签创建成功");
      setTagModalOpen(false);
      setNewTagName("");
      setNewTagColor("#3b82f6");
    } catch {
      toast("error", "创建标签失败");
    } finally {
      setTagsLoading(false);
    }
  }, [newTagName, newTagColor, id, toast]);

  if (loading) return <PaperDetailSkeleton />;
  if (!paper) {
    return (
      <Empty
        title="论文不存在"
        description="该论文可能已被删除"
        action={
          <Button variant="secondary" onClick={() => navigate("/papers")}>
            返回列表
          </Button>
        }
      />
    );
  }

  const statusConfig: Record<
    string,
    { label: string; variant: "default" | "warning" | "success" }
  > = {
    unread: { label: "未读", variant: "default" },
    skimmed: { label: "已粗读", variant: "warning" },
    deep_read: { label: "已精读", variant: "success" },
  };
  const sc = statusConfig[paper.read_status] || statusConfig.unread;

  const hasSkim = !!(savedSkim || skimReport);
  const hasDeep = !!(savedDeep || deepReport);
  const hasFigures = figures.length > 0;
  const hasReasoning = !!reasoning;
  const hasSimilar = similarIds.length > 0;

  const skimStatus: "idle" | "loading" | "done" = skimLoading
    ? "loading"
    : hasSkim
      ? "done"
      : "idle";
  const deepStatus: "idle" | "loading" | "done" = deepLoading
    ? "loading"
    : hasDeep
      ? "done"
      : "idle";
  const figureStatus: "idle" | "loading" | "done" = figuresAnalyzing
    ? "loading"
    : hasFigures
      ? "done"
      : "idle";
  const reasoningStatus: "idle" | "loading" | "done" = reasoningLoading
    ? "loading"
    : hasReasoning
      ? "done"
      : "idle";
  const similarStatus: "idle" | "loading" | "done" = similarLoading
    ? "loading"
    : hasSimilar
      ? "done"
      : "idle";

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate("/papers")}
          className="text-ink-secondary hover:text-ink flex items-center gap-1.5 text-sm transition-colors"
        >
          <ArrowLeft className="h-4 w-4" /> 返回论文列表
        </button>
        <button
          onClick={handleToggleFavorite}
          className="hover:bg-error/10 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors"
          title={paper.favorited ? "取消收藏" : "收藏"}
        >
          <Heart
            className={`h-5 w-5 transition-all ${paper.favorited ? "scale-110 fill-red-500 text-red-500" : "text-ink-tertiary"}`}
          />
          <span className={paper.favorited ? "text-red-500" : "text-ink-tertiary"}>
            {paper.favorited ? "已收藏" : "收藏"}
          </span>
        </button>
      </div>

      {/* 论文信息卡 */}
      <Card className="rounded-2xl">
        <div className="flex items-start gap-2">
          <Badge variant={sc.variant}>{sc.label}</Badge>
          {embedDone && <Badge variant="info">已向量化</Badge>}
          {paper.arxiv_id && (
            <a
              href={`https://arxiv.org/abs/${paper.arxiv_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary flex items-center gap-1 text-xs hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              {paper.arxiv_id}
            </a>
          )}
        </div>
        <h1 className="text-ink mt-3 text-2xl leading-snug font-bold">{paper.title}</h1>
        {paper.title_zh && <p className="text-ink-secondary mt-1 text-base">{paper.title_zh}</p>}
        {paper.abstract ? (
          <>
            <p className="text-ink-secondary mt-4 text-sm leading-relaxed">{paper.abstract}</p>
            {paper.abstract_zh && (
              <div className="border-border bg-page mt-3 rounded-xl border p-4">
                <p className="text-ink-tertiary mb-1 text-xs font-medium">中文翻译</p>
                <p className="text-ink-secondary text-sm leading-relaxed">{paper.abstract_zh}</p>
              </div>
            )}
          </>
        ) : paper.abstract_zh ? (
          <p className="text-ink-secondary mt-4 text-sm leading-relaxed">{paper.abstract_zh}</p>
        ) : null}
        {paper.publication_date && (
          <p className="text-ink-tertiary mt-3 text-sm">发表日期: {paper.publication_date}</p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {paper.topics &&
            paper.topics.length > 0 &&
            paper.topics.map((t) => (
              <span
                key={t}
                className="bg-primary-light text-primary inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium"
              >
                <Folder className="h-3 w-3" />
                {t}
              </span>
            ))}
          {/* 用户自定义标签 */}
          {paper.tags &&
            paper.tags.length > 0 &&
            paper.tags.map((tag) => (
              <span
                key={tag.id}
                className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium"
                style={{
                  backgroundColor: `${tag.color}20`,
                  color: tag.color,
                }}
              >
                <Tag className="h-3 w-3" />
                {tag.name}
              </span>
            ))}
          {paper.keywords &&
            paper.keywords.map((kw) => (
              <span
                key={kw}
                className="bg-hover text-ink-secondary inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs"
              >
                <Tag className="h-3 w-3" />
                {kw}
              </span>
            ))}
          {paper.categories &&
            paper.categories.map((c) => (
              <span
                key={c}
                className="border-border bg-surface text-ink-tertiary inline-flex items-center rounded-md border px-2 py-0.5 text-xs"
              >
                {c}
              </span>
            ))}
        </div>

        {/* 标签管理区域 */}
        <div className="border-border mt-4 rounded-xl border p-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-ink-tertiary text-xs font-medium">标签管理</p>
            <button
              onClick={() => {
                setNewTagName("");
                setNewTagColor("#3b82f6");
                setTagModalOpen(true);
              }}
              className="text-primary hover:bg-primary/5 inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors"
            >
              <Plus className="h-3 w-3" />
              新建标签
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {allTags.length === 0 ? (
              <p className="text-ink-tertiary px-1 py-2 text-xs">暂无标签，点击上方按钮创建</p>
            ) : (
              allTags.map((tag) => {
                const isSelected = paper.tags?.some((t) => t.id === tag.id) ?? false;
                return (
                  <button
                    key={tag.id}
                    onClick={() => handleToggleTag(tag.id, isSelected)}
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-all ${
                      isSelected ? "ring-2 ring-offset-1" : "hover:opacity-80"
                    }`}
                    style={{
                      backgroundColor: isSelected ? tag.color : `${tag.color}15`,
                      color: isSelected ? "white" : tag.color,
                      boxShadow: isSelected ? `0 0 0 2px ${tag.color}` : "none",
                    }}
                  >
                    <Tag className="h-3 w-3" />
                    {tag.name}
                    {isSelected && <Check className="h-3 w-3" />}
                  </button>
                );
              })
            )}
          </div>
        </div>
      </Card>

      {/* ========== 操作区：一键分析 + 主操作 + 辅助操作 ========== */}
      <div className="space-y-3">
        {/* 一键深度分析 */}
        {!(hasSkim && hasDeep && hasFigures && hasReasoning) && (
          <button
            onClick={handleAutoAnalyze}
            disabled={autoAnalyzing}
            className="border-primary/20 from-primary/5 to-primary/10 hover:from-primary/10 hover:to-primary/15 flex w-full items-center gap-3 rounded-2xl border bg-gradient-to-r p-4 transition-all hover:shadow-md disabled:opacity-60"
          >
            <div className="bg-primary/15 text-primary flex h-10 w-10 items-center justify-center rounded-xl">
              {autoAnalyzing ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Zap className="h-5 w-5" />
              )}
            </div>
            <div className="text-left">
              <p className="text-ink text-sm font-semibold">
                {autoAnalyzing ? autoStage || "分析中..." : "一键深度分析"}
              </p>
              <p className="text-ink-tertiary text-xs">
                {autoAnalyzing
                  ? "请耐心等待，全部完成后自动停止"
                  : `自动串联：嵌入 → 粗读${paper.pdf_path ? " → 精读 → 图表 → 推理链" : ""}`}
              </p>
            </div>
          </button>
        )}

        {/* 主操作 */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          {/* PDF 下载按钮 */}
          <button
            onClick={async () => {
              if (!id) return;
              try {
                toast("info", "正在下载 PDF...");
                const res = await paperApi.downloadPdf(id);
                toast(
                  "success",
                  `PDF 已下载：${res.status === "exists" ? "文件已存在" : "下载成功"}`
                );
                // 刷新论文信息
                const updated = await paperApi.detail(id);
                setPaper(updated);
                if (updated.pdf_path) setReaderOpen(true);
              } catch (e) {
                toast("error", e instanceof Error ? e.message : "PDF 下载失败");
              }
            }}
            disabled={!paper.arxiv_id || paper.arxiv_id.startsWith("ss-")}
            className="border-border bg-surface hover:border-primary/30 flex items-center gap-3 rounded-2xl border p-4 transition-all hover:shadow-md disabled:opacity-50"
            title={
              !paper.arxiv_id || paper.arxiv_id.startsWith("ss-")
                ? "该论文没有有效的 arXiv ID，无法下载 PDF"
                : "下载 PDF 到本地存储"
            }
          >
            <div className="bg-primary/10 text-primary flex h-10 w-10 items-center justify-center rounded-xl">
              <Download className="h-5 w-5" />
            </div>
            <div className="text-left">
              <p className="text-ink text-sm font-semibold">下载 PDF</p>
              <p className="text-ink-tertiary text-xs">
                {paper.pdf_path ? "已下载" : "从 arXiv 获取"}
              </p>
            </div>
          </button>
          {/* 阅读原文 */}
          {paper.pdf_path || (paper.arxiv_id && !paper.arxiv_id.startsWith("ss-")) ? (
            <button
              onClick={() => setReaderOpen(true)}
              className="border-border bg-surface hover:border-primary/30 flex items-center gap-3 rounded-2xl border p-4 transition-all hover:shadow-md"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10 text-blue-500">
                <FileSearch className="h-5 w-5" />
              </div>
              <div className="text-left">
                <p className="text-ink text-sm font-semibold">阅读原文</p>
                <p className="text-ink-tertiary text-xs">
                  {paper.pdf_path ? "PDF 阅读器（本地）" : "PDF 阅读器（arXiv 在线）"}
                </p>
              </div>
            </button>
          ) : (
            <div className="border-border bg-page/50 flex items-center gap-3 rounded-2xl border border-dashed p-4 opacity-50">
              <div className="bg-ink-tertiary/10 text-ink-tertiary flex h-10 w-10 items-center justify-center rounded-xl">
                <FileSearch className="h-5 w-5" />
              </div>
              <div className="text-left">
                <p className="text-ink-tertiary text-sm font-semibold">无 PDF</p>
                <p className="text-ink-tertiary text-xs">引用同步入库，无原文</p>
              </div>
            </div>
          )}
          <button
            onClick={handleSkim}
            disabled={skimLoading}
            className="border-border bg-surface hover:border-primary/30 flex items-center gap-3 rounded-2xl border p-4 transition-all hover:shadow-md disabled:opacity-60"
          >
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-xl ${hasSkim ? "bg-success/10 text-success" : "bg-amber-500/10 text-amber-500"}`}
            >
              {skimLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : hasSkim ? (
                <Check className="h-5 w-5" />
              ) : (
                <Eye className="h-5 w-5" />
              )}
            </div>
            <div className="text-left">
              <p className="text-ink text-sm font-semibold">{hasSkim ? "已粗读" : "粗读 (Skim)"}</p>
              <p className="text-ink-tertiary text-xs">
                {skimLoading ? "分析中..." : "快速提取要点"}
              </p>
            </div>
          </button>
          <button
            onClick={handleDeep}
            disabled={deepLoading || !paper.pdf_path}
            className="border-border bg-surface hover:border-primary/30 flex items-center gap-3 rounded-2xl border p-4 transition-all hover:shadow-md disabled:opacity-60"
            title={!paper.pdf_path ? "需要先下载 PDF 才能精读" : ""}
          >
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-xl ${hasDeep ? "bg-success/10 text-success" : !paper.pdf_path ? "bg-ink-tertiary/10 text-ink-tertiary" : "bg-indigo-500/10 text-indigo-500"}`}
            >
              {deepLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : hasDeep ? (
                <Check className="h-5 w-5" />
              ) : (
                <BookOpen className="h-5 w-5" />
              )}
            </div>
            <div className="text-left">
              <p className="text-ink text-sm font-semibold">
                {hasDeep ? "已精读" : "精读 (Deep Read)"}
              </p>
              <p className="text-ink-tertiary text-xs">
                {deepLoading
                  ? "深度分析中..."
                  : !paper.pdf_path
                    ? "无 PDF，需先下载"
                    : "方法论 + 实验 + 风险"}
              </p>
            </div>
          </button>
        </div>

        {/* 辅助操作 */}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={handleAnalyzeFigures}
            disabled={figuresAnalyzing || !paper.pdf_path}
            className="border-border bg-surface text-ink-secondary hover:border-primary/30 hover:text-ink inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all disabled:opacity-50"
          >
            {figuresAnalyzing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : hasFigures ? (
              <Check className="text-success h-3.5 w-3.5" />
            ) : (
              <ImageIcon className="h-3.5 w-3.5" />
            )}
            {hasFigures ? `图表 (${figures.length})` : "图表解读"}
          </button>
          <button
            onClick={handleReasoning}
            disabled={reasoningLoading || !paper.pdf_path}
            title={!paper.pdf_path ? "需要 PDF 才能进行推理链分析" : ""}
            className="border-border bg-surface text-ink-secondary hover:border-primary/30 hover:text-ink inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all disabled:opacity-50"
          >
            {reasoningLoading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : hasReasoning ? (
              <Check className="text-success h-3.5 w-3.5" />
            ) : (
              <Brain className="h-3.5 w-3.5" />
            )}
            {!paper.pdf_path ? "推理链 (无 PDF)" : "推理链分析"}
          </button>
          <button
            onClick={handleEmbed}
            disabled={embedLoading || embedDone === true}
            className="border-border bg-surface text-ink-secondary hover:border-primary/30 hover:text-ink inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all disabled:opacity-50"
          >
            {embedLoading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : embedDone ? (
              <Check className="text-success h-3.5 w-3.5" />
            ) : (
              <Cpu className="h-3.5 w-3.5" />
            )}
            {embedDone ? "已向量化" : "向量嵌入"}
          </button>
          <button
            onClick={handleSimilar}
            disabled={similarLoading || !paper.has_embedding}
            title={!paper.has_embedding ? "请先执行向量嵌入" : ""}
            className="border-border bg-surface text-ink-secondary hover:border-primary/30 hover:text-ink inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all disabled:opacity-50"
          >
            {similarLoading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Link2 className="h-3.5 w-3.5" />
            )}
            {!paper.has_embedding ? "相似 (需嵌入)" : "相似论文"}
          </button>
        </div>
      </div>

      {/* ========== 进度面板（任何 pipeline 运行时展示） ========== */}
      {skimLoading && (
        <PipelineProgress
          type="skim"
          onCancel={() => {
            skimAbort.current?.abort();
            setSkimLoading(false);
          }}
        />
      )}
      {deepLoading && (
        <PipelineProgress
          type="deep"
          onCancel={() => {
            deepAbort.current?.abort();
            setDeepLoading(false);
          }}
        />
      )}
      {figuresAnalyzing && <PipelineProgress type="figure" />}
      {reasoningLoading && <PipelineProgress type="reasoning" />}
      {embedLoading && <PipelineProgress type="embed" />}

      {/* ========== Tab 化报告区域 ========== */}
      <div className="space-y-4">
        <Tabs
          tabs={[
            { id: "skim", label: <TabLabel label="粗读" status={skimStatus} /> },
            { id: "deep", label: <TabLabel label="精读" status={deepStatus} /> },
            { id: "figures", label: <TabLabel label="图表" status={figureStatus} /> },
            { id: "reasoning", label: <TabLabel label="推理链" status={reasoningStatus} /> },
            { id: "similar", label: <TabLabel label="相似" status={similarStatus} /> },
          ]}
          active={reportTab}
          onChange={setReportTab}
        />

        <div className="min-h-[200px]">
          {/* Tab: 粗读 */}
          {reportTab === "skim" && (
            <div className="animate-fade-in">
              {skimLoading ? null : savedSkim && !skimReport ? (
                <Card className="border-primary/20 rounded-2xl">
                  <CardHeader
                    title="粗读报告"
                    action={
                      savedSkim.skim_score != null ? (
                        <div className="flex items-center gap-1.5 rounded-full bg-amber-500/10 px-3 py-1">
                          <Star className="h-4 w-4 text-amber-500" />
                          <span className="text-sm font-bold text-amber-600">
                            {savedSkim.skim_score.toFixed(2)}
                          </span>
                        </div>
                      ) : null
                    }
                  />
                  <div className="prose prose-sm text-ink-secondary dark:prose-invert max-w-none">
                    <Suspense fallback={<div className="bg-surface h-20 animate-pulse rounded" />}>
                      <Markdown>{savedSkim.summary_md}</Markdown>
                    </Suspense>
                  </div>
                </Card>
              ) : skimReport ? (
                <Card className="border-primary/20 rounded-2xl">
                  <CardHeader
                    title="粗读报告"
                    action={
                      <div className="flex items-center gap-1.5 rounded-full bg-amber-500/10 px-3 py-1">
                        <Sparkles className="h-4 w-4 text-amber-500" />
                        <span className="text-sm font-bold text-amber-600">
                          {skimReport.relevance_score.toFixed(2)}
                        </span>
                      </div>
                    }
                  />
                  <div className="space-y-4">
                    <div className="bg-primary/5 dark:bg-primary/10 rounded-xl p-4">
                      <div className="flex items-start gap-2">
                        <Sparkles className="text-primary mt-0.5 h-4 w-4 shrink-0" />
                        <p className="text-ink text-sm font-medium">{skimReport.one_liner}</p>
                      </div>
                    </div>
                    <div>
                      <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
                        <Lightbulb className="h-4 w-4 text-amber-500" /> 创新点
                      </h4>
                      <ul className="space-y-1.5">
                        {skimReport.innovations.map((item, i) => (
                          <li
                            key={`${item}-${i}`}
                            className="bg-page text-ink-secondary flex items-start gap-2 rounded-xl px-3 py-2.5 text-sm"
                          >
                            <CheckCircle2 className="text-success mt-0.5 h-3.5 w-3.5 shrink-0" />
                            {item}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </Card>
              ) : (
                <EmptyReport
                  icon={<Eye className="h-8 w-8" />}
                  label="点击「粗读」按钮快速提取论文要点"
                />
              )}
            </div>
          )}

          {/* Tab: 精读 */}
          {reportTab === "deep" && (
            <div className="animate-fade-in">
              {deepLoading ? null : savedDeep && !deepReport ? (
                <Card className="rounded-2xl border-blue-500/20">
                  <CardHeader title="精读报告" />
                  <div className="prose prose-sm text-ink-secondary dark:prose-invert max-w-none">
                    <Suspense fallback={<div className="bg-surface h-20 animate-pulse rounded" />}>
                      <Markdown>{savedDeep.deep_dive_md}</Markdown>
                    </Suspense>
                  </div>
                </Card>
              ) : deepReport ? (
                <Card className="rounded-2xl border-blue-500/20">
                  <CardHeader title="精读报告" />
                  <div className="space-y-4">
                    <ReportSection
                      icon={<FlaskConical className="h-4 w-4 text-blue-500" />}
                      title="方法论"
                      content={deepReport.method_summary}
                    />
                    <ReportSection
                      icon={<Microscope className="text-success h-4 w-4" />}
                      title="实验结果"
                      content={deepReport.experiments_summary}
                    />
                    <ReportSection
                      icon={<Sparkles className="h-4 w-4 text-amber-500" />}
                      title="消融实验"
                      content={deepReport.ablation_summary}
                    />
                    {deepReport.reviewer_risks.length > 0 && (
                      <div>
                        <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
                          <Shield className="h-4 w-4 text-red-500" /> 审稿风险
                        </h4>
                        <ul className="space-y-1.5">
                          {deepReport.reviewer_risks.map((risk) => (
                            <li
                              key={risk}
                              className="text-ink-secondary flex items-start gap-2 rounded-xl bg-red-500/5 px-3 py-2.5 text-sm dark:bg-red-500/10"
                            >
                              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />
                              {risk}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </Card>
              ) : (
                <EmptyReport
                  icon={<BookOpen className="h-8 w-8" />}
                  label={
                    paper.pdf_path
                      ? "点击「精读」按钮进行深度分析"
                      : "该论文没有 PDF 文件，无法精读（仅通过引用同步入库的论文）"
                  }
                />
              )}
            </div>
          )}

          {/* Tab: 图表 */}
          {reportTab === "figures" && (
            <div className="animate-fade-in">
              {figuresAnalyzing ? null : figures.length > 0 ? (
                <Card className="rounded-2xl">
                  <CardHeader title="图表解读" description={`共 ${figures.length} 张图表`} />
                  <div className="space-y-3">
                    {figures.map((fig, i) => (
                      <div
                        key={fig.id || `${fig.page_number}-${i}`}
                        className="animate-fade-in"
                        style={{ animationDelay: `${i * 80}ms` }}
                      >
                        <FigureCard figure={fig} index={i} paperId={id!} />
                      </div>
                    ))}
                  </div>
                </Card>
              ) : (
                <EmptyReport
                  icon={<ImageIcon className="h-8 w-8" />}
                  label={
                    paper.pdf_path
                      ? "点击「图表解读」按钮使用 Vision 模型分析 PDF"
                      : "该论文没有 PDF 文件，无法解读图表"
                  }
                />
              )}
            </div>
          )}

          {/* Tab: 推理链 */}
          {reportTab === "reasoning" && (
            <div className="animate-fade-in">
              {reasoningLoading ? null : reasoning ? (
                <Card className="rounded-2xl border-purple-500/20">
                  <CardHeader
                    title="推理链深度分析"
                    description="问题定义 → 方法推导 → 理论验证 → 实验评估 → 影响预测"
                  />
                  <ReasoningPanel reasoning={reasoning} />
                </Card>
              ) : (
                <EmptyReport
                  icon={<Brain className="h-8 w-8" />}
                  label={
                    paper.pdf_path
                      ? "点击「推理链分析」按钮进行分步推理评估"
                      : "该论文没有 PDF 文件，无法进行推理链分析"
                  }
                />
              )}
            </div>
          )}

          {/* Tab: 相似论文 */}
          {reportTab === "similar" && (
            <div className="animate-fade-in">
              {similarLoading ? null : similarIds.length > 0 ? (
                <Card className="rounded-2xl">
                  <CardHeader
                    title="相似论文"
                    description={`找到 ${similarIds.length} 篇相似论文`}
                  />
                  <div className="space-y-2">
                    {(similarItems.length > 0
                      ? similarItems
                      : similarIds.map((sid) => ({ id: sid, title: sid }))
                    ).map((item) => (
                      <button
                        key={item.id}
                        onClick={() => navigate(`/papers/${item.id}`)}
                        className="bg-page hover:bg-hover flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left transition-colors"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-ink truncate text-sm font-medium">{item.title}</p>
                          {"arxiv_id" in item && (item as { arxiv_id?: string }).arxiv_id ? (
                            <p className="text-ink-tertiary mt-0.5 truncate text-[10px]">
                              {(item as { arxiv_id?: string }).arxiv_id}
                            </p>
                          ) : null}
                        </div>
                        <ExternalLink className="text-ink-tertiary h-3.5 w-3.5 shrink-0" />
                      </button>
                    ))}
                  </div>
                </Card>
              ) : (
                <EmptyReport
                  icon={<Link2 className="h-8 w-8" />}
                  label={
                    embedDone ? "点击「相似论文」按钮查找" : "请先执行「向量嵌入」，再查找相似论文"
                  }
                />
              )}
            </div>
          )}
        </div>
      </div>

      {/* PDF 阅读器 - 支持本地 PDF 或 arXiv 在线链接，懒加载避免首屏加载 pdf.js */}
      {readerOpen && (paper.pdf_path || paper.arxiv_id) && (
        <Suspense
          fallback={
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
              <div className="border-primary h-8 w-8 animate-spin rounded-full border-4 border-t-transparent" />
            </div>
          }
        >
          <PdfReader
            paperId={id!}
            paperTitle={paper.title}
            paperArxivId={paper.arxiv_id}
            paperPdfPath={paper.pdf_path}
            onClose={() => setReaderOpen(false)}
          />
        </Suspense>
      )}

      {/* 新建标签弹窗 */}
      {tagModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-surface w-full max-w-md rounded-2xl border p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-ink text-lg font-semibold">新建标签</h3>
              <button
                onClick={() => {
                  setTagModalOpen(false);
                  setNewTagName("");
                  setNewTagColor("#3b82f6");
                }}
                className="text-ink-tertiary hover:bg-hover rounded-lg p-1 transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="text-ink mb-1.5 block text-sm font-medium">标签名称</label>
                <input
                  type="text"
                  value={newTagName}
                  onChange={(e) => setNewTagName(e.target.value)}
                  placeholder="输入标签名称"
                  className="border-border bg-surface text-ink focus:border-primary h-10 w-full rounded-lg border px-3 text-sm focus:outline-none"
                  autoFocus
                />
              </div>
              <div>
                <label className="text-ink mb-2 block text-sm font-medium">标签颜色</label>
                <div className="flex flex-wrap gap-2">
                  {[
                    "#3b82f6",
                    "#10b981",
                    "#f59e0b",
                    "#ef4444",
                    "#8b5cf6",
                    "#ec4899",
                    "#06b6d4",
                    "#84cc16",
                  ].map((color) => (
                    <button
                      key={color}
                      onClick={() => setNewTagColor(color)}
                      className={`h-8 w-8 rounded-full transition-transform ${
                        newTagColor === color ? "ring-2 ring-offset-2" : "hover:scale-110"
                      }`}
                      style={{
                        backgroundColor: color,
                        boxShadow: newTagColor === color ? `0 0 0 2px ${color}` : "none",
                      }}
                    />
                  ))}
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      value={newTagColor}
                      onChange={(e) => setNewTagColor(e.target.value)}
                      className="h-8 w-8 cursor-pointer rounded border-0"
                    />
                    <span className="text-ink-tertiary text-[11px]">{newTagColor}</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 pt-2">
                <span className="text-ink-tertiary text-sm">预览：</span>
                <span
                  className="inline-flex items-center rounded-md px-3 py-1 text-sm font-medium"
                  style={{
                    backgroundColor: `${newTagColor}20`,
                    color: newTagColor,
                  }}
                >
                  {newTagName || "标签名称"}
                </span>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => {
                  setTagModalOpen(false);
                  setNewTagName("");
                  setNewTagColor("#3b82f6");
                }}
                className="border-border bg-surface text-ink-secondary hover:bg-hover rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleCreateTag}
                disabled={tagsLoading || !newTagName.trim()}
                className="bg-primary text-white hover:bg-primary/90 disabled:opacity-50 inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                {tagsLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                创建
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ================================================================
 * 空状态报告占位
 * ================================================================ */

function EmptyReport({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="border-border bg-page/50 flex flex-col items-center justify-center rounded-2xl border border-dashed py-16 text-center">
      <div className="text-ink-tertiary/50 mb-3">{icon}</div>
      <p className="text-ink-tertiary text-sm">{label}</p>
    </div>
  );
}

/* ================================================================
 * 图表解读卡片
 * ================================================================ */

const TYPE_ICONS: Record<string, React.ReactNode> = {
  figure: <ImageIcon className="h-4 w-4 text-blue-500" />,
  table: <Table2 className="h-4 w-4 text-amber-500" />,
  algorithm: <FileCode2 className="h-4 w-4 text-green-500" />,
  equation: <BarChart3 className="h-4 w-4 text-purple-500" />,
};

const TYPE_LABELS: Record<string, string> = {
  figure: "图表",
  table: "表格",
  algorithm: "算法",
  equation: "公式",
};

function FigureCard({
  figure,
  index,
  paperId,
}: {
  figure: FigureAnalysisItem;
  index: number;
  paperId: string;
}) {
  const [expanded, setExpanded] = useState(index < 3);
  const [lightbox, setLightbox] = useState(false);
  const imgUrl = figure.image_url && figure.id ? paperApi.figureImageUrl(paperId, figure.id) : null;

  return (
    <>
      <div className="border-border bg-surface/50 hover:border-border/80 overflow-hidden rounded-xl border transition-all">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center gap-3 px-4 py-3 text-left"
        >
          <div className="bg-page flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
            {TYPE_ICONS[figure.image_type] || TYPE_ICONS.figure}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-600 dark:text-blue-400">
                {TYPE_LABELS[figure.image_type] || figure.image_type}
              </span>
              <span className="text-ink-tertiary text-[10px]">第 {figure.page_number} 页</span>
            </div>
            {figure.caption && (
              <p className="text-ink mt-0.5 truncate text-xs font-medium">{figure.caption}</p>
            )}
          </div>
          {expanded ? (
            <ChevronDown className="text-ink-tertiary h-4 w-4 shrink-0" />
          ) : (
            <ChevronRight className="text-ink-tertiary h-4 w-4 shrink-0" />
          )}
        </button>

        {expanded && (
          <div className="border-border border-t">
            {/* 原图展示区 */}
            {imgUrl ? (
              <div className="bg-page/50 flex justify-center p-4 dark:bg-black/20">
                <img
                  src={imgUrl}
                  alt={figure.caption || `Figure on page ${figure.page_number}`}
                  className="max-h-[400px] max-w-full cursor-zoom-in rounded-lg object-contain shadow-sm transition-transform hover:scale-[1.02]"
                  onClick={(e) => {
                    e.stopPropagation();
                    setLightbox(true);
                  }}
                  loading="lazy"
                />
              </div>
            ) : (
              <div className="bg-page/30 text-ink-tertiary flex items-center justify-center px-4 py-6 text-xs">
                <ImageIcon className="mr-1.5 h-4 w-4" /> 原图未提取（旧版分析结果）
              </div>
            )}

            {/* AI 解读区 */}
            <div className="border-border/50 border-t px-4 py-3">
              <div className="text-primary/70 mb-1.5 flex items-center gap-1.5 text-[10px] font-medium tracking-wide uppercase">
                <Sparkles className="h-3 w-3" /> AI 解读
              </div>
              <div className="prose prose-sm text-ink-secondary dark:prose-invert max-w-none">
                <Suspense fallback={<div className="bg-surface h-8 animate-pulse rounded" />}>
                  <Markdown>{figure.description}</Markdown>
                </Suspense>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 图片灯箱 */}
      {lightbox && imgUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={() => setLightbox(false)}
        >
          <button
            className="absolute top-4 right-4 rounded-full bg-white/10 p-2 text-white transition-colors hover:bg-white/20"
            onClick={() => setLightbox(false)}
          >
            <X className="h-5 w-5" />
          </button>
          <img
            src={imgUrl}
            alt={figure.caption || ""}
            className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
          {figure.caption && (
            <div className="absolute bottom-6 left-1/2 max-w-xl -translate-x-1/2 rounded-lg bg-black/60 px-4 py-2 text-center text-sm text-white/90">
              {figure.caption}
            </div>
          )}
        </div>
      )}
    </>
  );
}

/* ================================================================
 * 推理链面板
 * ================================================================ */

function ReasoningPanel({ reasoning }: { reasoning: ReasoningChainResult }) {
  const steps = reasoning.reasoning_steps ?? [];
  const mc = reasoning.method_chain ?? ({} as Record<string, string>);
  const ec = reasoning.experiment_chain ?? ({} as Record<string, string>);
  const ia = reasoning.impact_assessment ?? ({} as Record<string, unknown>);

  const novelty = (ia.novelty_score as number) ?? 0;
  const rigor = (ia.rigor_score as number) ?? 0;
  const impact = (ia.impact_score as number) ?? 0;
  const overall = (ia.overall_assessment as string) ?? "";
  const strengths = (ia.strengths as string[]) ?? [];
  const weaknesses = (ia.weaknesses as string[]) ?? [];
  const suggestions = (ia.future_suggestions as string[]) ?? [];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-4">
        <ScoreCard
          label="创新性"
          score={novelty}
          icon={<Zap className="h-4 w-4" />}
          color="text-purple-500"
          bg="bg-purple-500/10"
        />
        <ScoreCard
          label="严谨性"
          score={rigor}
          icon={<Target className="h-4 w-4" />}
          color="text-blue-500"
          bg="bg-blue-500/10"
        />
        <ScoreCard
          label="影响力"
          score={impact}
          icon={<TrendingUp className="h-4 w-4" />}
          color="text-orange-500"
          bg="bg-orange-500/10"
        />
      </div>

      {overall && (
        <div className="bg-page dark:bg-page/50 rounded-xl p-4">
          <p className="text-ink-secondary text-sm leading-relaxed whitespace-pre-wrap">
            {overall}
          </p>
        </div>
      )}

      {steps.length > 0 && (
        <div>
          <h4 className="text-ink mb-3 flex items-center gap-2 text-sm font-semibold">
            <Brain className="h-4 w-4 text-purple-500" /> 推理过程
          </h4>
          <div className="space-y-2">
            {steps.map((step, i) => (
              <ReasoningStepCard key={step.step} step={step} index={i} />
            ))}
          </div>
        </div>
      )}

      {Object.values(mc).some(Boolean) && (
        <div>
          <h4 className="text-ink mb-3 flex items-center gap-2 text-sm font-semibold">
            <FlaskConical className="h-4 w-4 text-blue-500" /> 方法论推导链
          </h4>
          <div className="space-y-3">
            {mc.problem_definition && <ChainItem label="问题定义" text={mc.problem_definition} />}
            {mc.core_hypothesis && <ChainItem label="核心假设" text={mc.core_hypothesis} />}
            {mc.method_derivation && <ChainItem label="方法推导" text={mc.method_derivation} />}
            {mc.theoretical_basis && <ChainItem label="理论基础" text={mc.theoretical_basis} />}
            {mc.innovation_analysis && (
              <ChainItem label="创新性分析" text={mc.innovation_analysis} />
            )}
          </div>
        </div>
      )}

      {Object.values(ec).some(Boolean) && (
        <div>
          <h4 className="text-ink mb-3 flex items-center gap-2 text-sm font-semibold">
            <Microscope className="h-4 w-4 text-green-500" /> 实验验证链
          </h4>
          <div className="space-y-3">
            {ec.experimental_design && <ChainItem label="实验设计" text={ec.experimental_design} />}
            {ec.baseline_fairness && <ChainItem label="基线公平性" text={ec.baseline_fairness} />}
            {ec.result_validation && <ChainItem label="结果验证" text={ec.result_validation} />}
            {ec.ablation_insights && <ChainItem label="消融洞察" text={ec.ablation_insights} />}
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {strengths.length > 0 && (
          <div>
            <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
              <ThumbsUp className="h-4 w-4 text-green-500" /> 优势
            </h4>
            <ul className="space-y-1.5">
              {strengths.map((s, i) => (
                <li
                  key={`strength-${i}`}
                  className="text-ink-secondary flex items-start gap-2 rounded-xl bg-green-500/5 px-3 py-2.5 text-sm dark:bg-green-500/10"
                >
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-500" />
                  {s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {weaknesses.length > 0 && (
          <div>
            <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
              <ThumbsDown className="h-4 w-4 text-red-500" /> 不足
            </h4>
            <ul className="space-y-1.5">
              {weaknesses.map((w, i) => (
                <li
                  key={`weakness-${i}`}
                  className="text-ink-secondary flex items-start gap-2 rounded-xl bg-red-500/5 px-3 py-2.5 text-sm dark:bg-red-500/10"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />
                  {w}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {suggestions.length > 0 && (
        <div>
          <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
            <Lightbulb className="h-4 w-4 text-amber-500" /> 未来研究建议
          </h4>
          <ul className="space-y-1.5">
            {suggestions.map((f, i) => (
              <li
                key={`suggestion-${i}`}
                className="text-ink-secondary flex items-start gap-2 rounded-xl bg-amber-500/5 px-3 py-2.5 text-sm dark:bg-amber-500/10"
              >
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ReasoningStepCard({
  step,
  index,
}: {
  step: { step: string; thinking: string; conclusion: string };
  index: number;
}) {
  const [open, setOpen] = useState(index < 2);
  return (
    <div className="border-border bg-surface/50 rounded-xl border transition-all">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-purple-500/10 text-xs font-bold text-purple-500">
          {index + 1}
        </div>
        <span className="text-ink flex-1 text-sm font-medium">{step.step}</span>
        {open ? (
          <ChevronDown className="text-ink-tertiary h-4 w-4" />
        ) : (
          <ChevronRight className="text-ink-tertiary h-4 w-4" />
        )}
      </button>
      {open && (
        <div className="border-border space-y-3 border-t px-4 py-3">
          {step.thinking && (
            <div className="rounded-xl bg-purple-500/5 px-3 py-2.5 dark:bg-purple-500/10">
              <p className="mb-1 text-[10px] font-semibold tracking-wider text-purple-500 uppercase">
                思考过程
              </p>
              <p className="text-ink-secondary text-sm leading-relaxed whitespace-pre-wrap">
                {step.thinking}
              </p>
            </div>
          )}
          {step.conclusion && (
            <div className="rounded-xl bg-green-500/5 px-3 py-2.5 dark:bg-green-500/10">
              <p className="mb-1 text-[10px] font-semibold tracking-wider text-green-500 uppercase">
                结论
              </p>
              <p className="text-ink-secondary text-sm leading-relaxed">{step.conclusion}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ScoreCard({
  label,
  score,
  icon,
  color,
  bg,
}: {
  label: string;
  score: number;
  icon: React.ReactNode;
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

function ChainItem({ label, text }: { label: string; text: string }) {
  return (
    <div className="border-border bg-surface/50 rounded-xl border px-4 py-3">
      <p className="text-ink-tertiary mb-1 text-xs font-semibold">{label}</p>
      <p className="text-ink-secondary text-sm leading-relaxed whitespace-pre-wrap">{text}</p>
    </div>
  );
}

function ReportSection({
  icon,
  title,
  content,
}: {
  icon: React.ReactNode;
  title: string;
  content: string;
}) {
  return (
    <div>
      <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
        {icon}
        {title}
      </h4>
      <div className="bg-page dark:bg-page/50 rounded-xl px-4 py-3">
        <p className="text-ink-secondary text-sm leading-relaxed whitespace-pre-wrap">{content}</p>
      </div>
    </div>
  );
}
