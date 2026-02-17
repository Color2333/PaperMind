/**
 * Paper Detail - 论文详情（含收藏、粗读/精读报告加载）
 * @author Bamzc
 */
import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Card, CardHeader, Button, Badge, Spinner, Empty } from "@/components/ui";
import Markdown from "@/components/Markdown";
import { paperApi, pipelineApi } from "@/services/api";
import type { Paper, SkimReport, DeepDiveReport } from "@/types";
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
} from "lucide-react";

export default function PaperDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
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

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    paperApi
      .detail(id)
      .then((p) => {
        setPaper(p);
        setEmbedDone(p.has_embedding ?? false);
        if (p.skim_report) setSavedSkim(p.skim_report);
        if (p.deep_report) setSavedDeep(p.deep_report);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  const handleSkim = async () => {
    if (!id) return;
    setSkimLoading(true);
    try {
      const report = await pipelineApi.skim(id);
      setSkimReport(report);
    } catch { /* 静默 */ } finally { setSkimLoading(false); }
  };

  const handleDeep = async () => {
    if (!id) return;
    setDeepLoading(true);
    try {
      const report = await pipelineApi.deep(id);
      setDeepReport(report);
    } catch { /* 静默 */ } finally { setDeepLoading(false); }
  };

  const handleEmbed = async () => {
    if (!id) return;
    setEmbedLoading(true);
    try {
      await pipelineApi.embed(id);
      setEmbedDone(true);
    } catch { /* 静默 */ } finally { setEmbedLoading(false); }
  };

  const handleSimilar = async () => {
    if (!id) return;
    setSimilarLoading(true);
    try {
      const res = await paperApi.similar(id);
      setSimilarIds(res.similar_ids);
    } catch { /* 静默 */ } finally { setSimilarLoading(false); }
  };

  const handleToggleFavorite = useCallback(async () => {
    if (!id || !paper) return;
    try {
      const res = await paperApi.toggleFavorite(id);
      setPaper((prev) => prev ? { ...prev, favorited: res.favorited } : prev);
    } catch { /* 静默 */ }
  }, [id, paper]);

  if (loading) return <Spinner text="加载论文详情..." />;
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
        <button
          onClick={() => navigate("/papers")}
          className="flex items-center gap-1.5 text-sm text-ink-secondary transition-colors hover:text-ink"
        >
          <ArrowLeft className="h-4 w-4" />
          返回论文列表
        </button>
        <button
          onClick={handleToggleFavorite}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors hover:bg-error/10"
          title={paper.favorited ? "取消收藏" : "收藏"}
        >
          <Heart
            className={`h-5 w-5 ${
              paper.favorited ? "fill-red-500 text-red-500" : "text-ink-tertiary"
            }`}
          />
          <span className={paper.favorited ? "text-red-500" : "text-ink-tertiary"}>
            {paper.favorited ? "已收藏" : "收藏"}
          </span>
        </button>
      </div>

      {/* 论文信息 */}
      <Card>
        <div className="flex items-start gap-2">
          <Badge variant={sc.variant}>{sc.label}</Badge>
          {paper.arxiv_id && (
            <a
              href={`https://arxiv.org/abs/${paper.arxiv_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              {paper.arxiv_id}
            </a>
          )}
        </div>
        <h1 className="mt-3 text-2xl font-bold leading-snug text-ink">
          {paper.title}
        </h1>
        {paper.title_zh && (
          <p className="mt-1 text-base text-ink-secondary">{paper.title_zh}</p>
        )}
        {paper.abstract && (
          <p className="mt-4 leading-relaxed text-ink-secondary">{paper.abstract}</p>
        )}
        {paper.abstract_zh && (
          <div className="mt-3 rounded-xl border border-border bg-page p-4">
            <p className="mb-1 text-xs font-medium text-ink-tertiary">中文摘要</p>
            <p className="text-sm leading-relaxed text-ink-secondary">{paper.abstract_zh}</p>
          </div>
        )}
        {paper.publication_date && (
          <p className="mt-3 text-sm text-ink-tertiary">
            发表日期: {paper.publication_date}
          </p>
        )}
        {/* 主题 */}
        {paper.topics && paper.topics.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Folder className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium text-ink-secondary">主题:</span>
            {paper.topics.map((t) => (
              <span key={t} className="inline-flex items-center rounded-md bg-primary-light px-2.5 py-1 text-xs font-medium text-primary">
                {t}
              </span>
            ))}
          </div>
        )}
        {/* 关键词 */}
        {paper.keywords && paper.keywords.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Tag className="h-4 w-4 text-ink-tertiary" />
            <span className="text-sm font-medium text-ink-secondary">关键词:</span>
            {paper.keywords.map((kw) => (
              <span key={kw} className="inline-flex items-center rounded-md bg-hover px-2.5 py-1 text-xs text-ink-secondary">
                {kw}
              </span>
            ))}
          </div>
        )}
        {/* ArXiv 分类 */}
        {paper.categories && paper.categories.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ink-secondary">ArXiv 分类:</span>
            {paper.categories.map((c) => (
              <span key={c} className="inline-flex items-center rounded-md border border-border bg-surface px-2 py-0.5 text-xs text-ink-tertiary">
                {c}
              </span>
            ))}
          </div>
        )}
      </Card>

      {/* 操作按钮 */}
      <div className="flex flex-wrap gap-3">
        <Button
          variant="secondary"
          icon={<Eye className="h-4 w-4" />}
          onClick={handleSkim}
          loading={skimLoading}
        >
          粗读 (Skim)
        </Button>
        <Button
          variant="secondary"
          icon={<BookOpen className="h-4 w-4" />}
          onClick={handleDeep}
          loading={deepLoading}
        >
          精读 (Deep Read)
        </Button>
        <Button
          variant="secondary"
          icon={<Cpu className="h-4 w-4" />}
          onClick={handleEmbed}
          loading={embedLoading}
          disabled={embedDone === true}
        >
          {embedDone ? "✓ 已向量化" : "向量嵌入 (Embed)"}
        </Button>
        <Button
          variant="secondary"
          icon={<Link2 className="h-4 w-4" />}
          onClick={handleSimilar}
          loading={similarLoading}
        >
          相似论文
        </Button>
      </div>

      {/* 已保存的粗读报告 */}
      {savedSkim && !skimReport && (
        <Card className="animate-fade-in border-primary/20">
          <CardHeader
            title="粗读报告（已保存）"
            action={
              savedSkim.skim_score != null ? (
                <div className="flex items-center gap-1.5">
                  <Star className="h-4 w-4 text-warning" />
                  <span className="text-sm font-semibold text-ink">
                    {savedSkim.skim_score.toFixed(2)}
                  </span>
                </div>
              ) : null
            }
          />
          <div className="prose prose-sm max-w-none text-ink-secondary dark:prose-invert">
            <Markdown>{savedSkim.summary_md}</Markdown>
          </div>
        </Card>
      )}

      {/* 新执行的 Skim 报告 */}
      {skimReport && (
        <Card className="animate-fade-in border-primary/20">
          <CardHeader
            title="粗读报告"
            action={
              <div className="flex items-center gap-1.5">
                <Star className="h-4 w-4 text-warning" />
                <span className="text-sm font-semibold text-ink">
                  {skimReport.relevance_score.toFixed(2)}
                </span>
              </div>
            }
          />
          <div className="space-y-4">
            <div className="rounded-xl bg-primary/5 p-4">
              <div className="flex items-start gap-2">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <p className="text-sm font-medium text-ink">{skimReport.one_liner}</p>
              </div>
            </div>
            <div>
              <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
                <Lightbulb className="h-4 w-4 text-warning" />
                创新点
              </h4>
              <ul className="space-y-1.5">
                {skimReport.innovations.map((item, i) => (
                  <li key={i} className="flex items-start gap-2 rounded-lg bg-page px-3 py-2 text-sm text-ink-secondary">
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
                    {item}
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
            <ReportSection
              icon={<FlaskConical className="h-4 w-4 text-info" />}
              title="方法论"
              content={deepReport.method_summary}
            />
            <ReportSection
              icon={<Microscope className="h-4 w-4 text-success" />}
              title="实验结果"
              content={deepReport.experiments_summary}
            />
            <ReportSection
              icon={<Sparkles className="h-4 w-4 text-warning" />}
              title="消融实验"
              content={deepReport.ablation_summary}
            />
            {deepReport.reviewer_risks.length > 0 && (
              <div>
                <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
                  <Shield className="h-4 w-4 text-error" />
                  审稿风险
                </h4>
                <ul className="space-y-1.5">
                  {deepReport.reviewer_risks.map((risk, i) => (
                    <li key={i} className="flex items-start gap-2 rounded-lg bg-error-light px-3 py-2 text-sm text-ink-secondary">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-error" />
                      {risk}
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
              <button
                key={sid}
                onClick={() => navigate(`/papers/${sid}`)}
                className="flex w-full items-center justify-between rounded-lg bg-page px-4 py-3 text-left transition-colors hover:bg-hover"
              >
                <span className="text-sm text-ink">{sid}</span>
                <ExternalLink className="h-3.5 w-3.5 text-ink-tertiary" />
              </button>
            ))}
          </div>
        </Card>
      )}
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
      <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
        {icon}
        {title}
      </h4>
      <div className="rounded-xl bg-page px-4 py-3">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-secondary">
          {content}
        </p>
      </div>
    </div>
  );
}
