/**
 * Paper Detail - 论文详情（重构版：进度面板 + Tab 化报告 + 统一布局）
 * @author Color2333
 */
import { useState, lazy, Suspense } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Card, CardHeader, Button, Badge, Empty } from "@/components/ui";
import { Tabs } from "@/components/ui/Tabs";
import { PaperDetailSkeleton } from "@/components/Skeleton";
import {
  PipelineProgress,
  TabLabel,
  EmptyReport,
  FigureCard,
  ReasoningPanel,
  ReportSection,
} from "@/components/paper-detail";
import {
  usePaperCore,
  useSkim,
  useDeepRead,
  useEmbed,
  useSimilarPapers,
  useDuplicates,
  useSimilarViaCitation,
  useFigures,
  useReasoning,
  usePaperTags,
  useAutoAnalyze,
} from "@/hooks/paper-detail";

// 重型依赖懒加载，只在真正需要时加载
const Markdown = lazy(() => import("@/components/Markdown"));
const PdfReader = lazy(() => import("@/components/PdfReader"));
import { useToast } from "@/contexts/ToastContext";
import { paperApi } from "@/services/api";
import type { Paper } from "@/types";
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
  Copy,
  Network,
  Ban,
  Tag,
  Folder,
  Heart,
  Image as ImageIcon,
  Brain,
  Zap,
  FileSearch,
  X,
  Loader2,
  Check,
  Download,
  Plus,
} from "lucide-react";

/* ================================================================
 * 主组件
 * ================================================================ */

export default function PaperDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  // paper 状态在主组件中声明，避免 hook 间循环依赖
  const [paper, setPaper] = useState<Paper | null>(null);

  const [readerOpen, setReaderOpen] = useState(false);
  const [reportTab, setReportTab] = useState("skim");

  // 标签 hook
  const {
    allTags,
    setAllTags,
    tagModalOpen,
    setTagModalOpen,
    newTagName,
    setNewTagName,
    newTagColor,
    setNewTagColor,
    tagsLoading,
    handleToggleTag,
    handleCreateTag,
  } = usePaperTags({ paperId: id, toast, paper, setPaper });

  // 图表 hook（提供 setFigures 给 usePaperCore）
  const {
    figures,
    setFigures,
    figuresAnalyzing,
    setFiguresAnalyzing,
    handleAnalyzeFigures,
  } = useFigures({ id, toast, setReportTab });

  // 推理 hook（提供 setReasoning 给 usePaperCore）
  const {
    reasoning,
    setReasoning,
    reasoningLoading,
    setReasoningLoading,
    handleReasoning,
  } = useReasoning({ id, toast, setReportTab });

  // 粗读 hook（提供 setSavedSkim 给 usePaperCore）
  const {
    skimReport,
    setSkimReport,
    savedSkim,
    setSavedSkim,
    skimLoading,
    setSkimLoading,
    skimAbort,
    cancelSkim,
    handleSkim,
  } = useSkim({ id, toast, setReportTab, setPaper });

  // 精读 hook（提供 setSavedDeep 给 usePaperCore）
  const {
    deepReport,
    setDeepReport,
    savedDeep,
    setSavedDeep,
    deepLoading,
    setDeepLoading,
    deepAbort,
    cancelDeep,
    handleDeep,
  } = useDeepRead({ id, toast, setReportTab });

  // 核心数据 hook（拥有 loading/embedDone + 初始加载 effect + 收藏）
  const {
    loading,
    embedDone,
    setEmbedDone,
    handleToggleFavorite,
    handleToggleRejected,
  } = usePaperCore({
    id,
    toast,
    paper,
    setPaper,
    setFigures,
    setAllTags,
    setReasoning,
    setSavedSkim,
    setSavedDeep,
    setReportTab,
  });

  // 嵌入 hook
  const { embedLoading, setEmbedLoading, handleEmbed, cancelEmbed } = useEmbed({
    id,
    toast,
    embedDone,
    setEmbedDone,
  });

  // 相似论文 hook
  const {
    similarIds,
    similarItems,
    similarLoading,
    handleSimilar,
  } = useSimilarPapers({ id, toast, setReportTab });

  // 查重 hook（检测疑似重复论文，相似度 > 0.92）
  const {
    duplicateItems,
    duplicateLoading,
    handleDuplicates,
  } = useDuplicates({ id, toast, setReportTab });

  // 引用图补强 hook（co-citation + 向量相似度排序）
  const {
    citationSimilarItems,
    citationSimilarLoading,
    handleCitationSimilar,
  } = useSimilarViaCitation({ id, toast, setReportTab });

  // 一键深度分析 hook（拥有 autoAnalyzing/autoStage + handleAutoAnalyze）
  const hasSkim = !!(savedSkim || skimReport);
  const hasDeep = !!(savedDeep || deepReport);
  const { autoAnalyzing, autoStage, handleAutoAnalyze } = useAutoAnalyze({
    id,
    toast,
    paper,
    hasSkim,
    hasDeep,
    figures,
    reasoning,
    setReportTab,
    setEmbedLoading,
    setEmbedDone,
    setSkimLoading,
    setSkimReport,
    setDeepLoading,
    setDeepReport,
    setFiguresAnalyzing,
    setFigures,
    setReasoningLoading,
    setReasoning,
  });

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
  // paper 已加载意味着 id 此前一定有值；此处收窄类型，避免下游 paperId={id!} 的非空断言
  if (!id) return null;
  const paperId = id;

  const statusConfig: Record<
    string,
    { label: string; variant: "default" | "warning" | "success" }
  > = {
    unread: { label: "未读", variant: "default" },
    skimmed: { label: "已粗读", variant: "warning" },
    deep_read: { label: "已精读", variant: "success" },
  };
  const sc = statusConfig[paper.read_status] || statusConfig.unread;

  const hasFigures = figures.length > 0;
  const hasReasoning = !!reasoning;
  const hasSimilar = similarIds.length > 0;
  const hasDuplicates = duplicateItems.length > 0;
  const hasCitationSimilar = citationSimilarItems.length > 0;

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
  const duplicateStatus: "idle" | "loading" | "done" = duplicateLoading
    ? "loading"
    : hasDuplicates
      ? "done"
      : "idle";
  const citationSimilarStatus: "idle" | "loading" | "done" = citationSimilarLoading
    ? "loading"
    : hasCitationSimilar
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
        <button
          onClick={handleToggleRejected}
          className="hover:bg-error/10 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors"
          title={paper.rejected ? "取消不感兴趣" : "不感兴趣（推荐系统将不再推荐此类论文）"}
        >
          <Ban
            className={`h-5 w-5 transition-all ${paper.rejected ? "text-error" : "text-ink-tertiary"}`}
          />
          <span className={paper.rejected ? "text-error" : "text-ink-tertiary"}>
            {paper.rejected ? "已屏蔽" : "不感兴趣"}
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
          <button
            onClick={handleDuplicates}
            disabled={duplicateLoading || !paper.has_embedding}
            title={!paper.has_embedding ? "请先执行向量嵌入" : "检测相似度 > 92% 的疑似重复论文"}
            className="border-border bg-surface text-ink-secondary hover:border-primary/30 hover:text-ink inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all disabled:opacity-50"
          >
            {duplicateLoading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            查重
          </button>
          <button
            onClick={handleCitationSimilar}
            disabled={citationSimilarLoading || !paper.has_embedding}
            title={!paper.has_embedding ? "请先执行向量嵌入" : "引用同一篇论文且语义相近的论文"}
            className="border-border bg-surface text-ink-secondary hover:border-primary/30 hover:text-ink inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all disabled:opacity-50"
          >
            {citationSimilarLoading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Network className="h-3.5 w-3.5" />
            )}
            引用补强
          </button>
        </div>
      </div>

      {/* ========== 进度面板（任何 pipeline 运行时展示） ========== */}
      {skimLoading && (
        <PipelineProgress
          type="skim"
          onCancel={() => {
            cancelSkim();
            toast("info", "已取消（后台任务可能仍在处理）");
          }}
        />
      )}
      {deepLoading && (
        <PipelineProgress
          type="deep"
          onCancel={() => {
            cancelDeep();
            toast("info", "已取消（后台任务可能仍在处理）");
          }}
        />
      )}
      {/* figure/reasoning/embed 无后端 cancel 端点，onCancel 仅停 UI + 提示 */}
      {figuresAnalyzing && (
        <PipelineProgress
          type="figure"
          onCancel={() => {
            setFiguresAnalyzing(false);
            toast("info", "已取消（后台可能仍在处理）");
          }}
        />
      )}
      {reasoningLoading && (
        <PipelineProgress
          type="reasoning"
          onCancel={() => {
            setReasoningLoading(false);
            toast("info", "已取消（后台可能仍在处理）");
          }}
        />
      )}
      {embedLoading && (
        <PipelineProgress
          type="embed"
          onCancel={() => {
            cancelEmbed();
            toast("info", "已取消（后台任务可能仍在处理）");
          }}
        />
      )}

      {/* ========== Tab 化报告区域 ========== */}
      <div className="space-y-4">
        <Tabs
          tabs={[
            { id: "skim", label: <TabLabel label="粗读" status={skimStatus} /> },
            { id: "deep", label: <TabLabel label="精读" status={deepStatus} /> },
            { id: "figures", label: <TabLabel label="图表" status={figureStatus} /> },
            { id: "reasoning", label: <TabLabel label="推理链" status={reasoningStatus} /> },
            { id: "similar", label: <TabLabel label="相似" status={similarStatus} /> },
            { id: "duplicates", label: <TabLabel label="查重" status={duplicateStatus} /> },
            { id: "citation-similar", label: <TabLabel label="引用补强" status={citationSimilarStatus} /> },
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
                        <FigureCard figure={fig} index={i} paperId={paperId} />
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
                      : similarIds.map((sid) => ({ id: sid, title: "点击查看详情" }))
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

          {/* Tab: 查重（疑似重复论文，相似度 > 92%） */}
          {reportTab === "duplicates" && (
            <div className="animate-fade-in">
              {duplicateLoading ? null : duplicateItems.length > 0 ? (
                <Card className="rounded-2xl">
                  <CardHeader
                    title="疑似重复论文"
                    description={`检测到 ${duplicateItems.length} 篇相似度 > 92% 的论文（可能是同一工作的多版本）`}
                  />
                  <div className="space-y-2">
                    {duplicateItems.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => navigate(`/papers/${item.id}`)}
                        className="bg-page hover:bg-hover flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left transition-colors"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-ink truncate text-sm font-medium">{item.title}</p>
                          {item.arxiv_id && (
                            <p className="text-ink-tertiary mt-0.5 truncate text-[10px]">{item.arxiv_id}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-primary text-xs font-medium">
                            {(item.similarity * 100).toFixed(1)}%
                          </span>
                          <ExternalLink className="text-ink-tertiary h-3.5 w-3.5" />
                        </div>
                      </button>
                    ))}
                  </div>
                </Card>
              ) : (
                <EmptyReport
                  icon={<Copy className="h-8 w-8" />}
                  label={
                    embedDone ? "点击「查重」按钮检测" : "请先执行「向量嵌入」，再检测重复论文"
                  }
                />
              )}
            </div>
          )}

          {/* Tab: 引用补强（co-citation + 向量相似度排序） */}
          {reportTab === "citation-similar" && (
            <div className="animate-fade-in">
              {citationSimilarLoading ? null : citationSimilarItems.length > 0 ? (
                <Card className="rounded-2xl">
                  <CardHeader
                    title="引用图补强"
                    description={`${citationSimilarItems.length} 篇引用同一论文且语义相近的论文`}
                  />
                  <div className="space-y-2">
                    {citationSimilarItems.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => navigate(`/papers/${item.id}`)}
                        className="bg-page hover:bg-hover flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left transition-colors"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-ink truncate text-sm font-medium">{item.title}</p>
                          {item.arxiv_id && (
                            <p className="text-ink-tertiary mt-0.5 truncate text-[10px]">{item.arxiv_id}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-primary text-xs font-medium">
                            {(item.similarity * 100).toFixed(1)}%
                          </span>
                          <ExternalLink className="text-ink-tertiary h-3.5 w-3.5" />
                        </div>
                      </button>
                    ))}
                  </div>
                </Card>
              ) : (
                <EmptyReport
                  icon={<Network className="h-8 w-8" />}
                  label={
                    embedDone ? "点击「引用补强」按钮查找" : "请先执行「向量嵌入」，再查找引用补强论文"
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
            paperId={paperId}
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
