/**
 * Paper Detail - 论文详情
 * 覆盖 API: GET /papers/{id}, POST /pipelines/skim|deep|embed/{id}, GET /papers/{id}/similar
 * @author Bamzc
 */
import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Card, CardHeader, Button, Badge, Spinner, Empty } from "@/components/ui";
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
} from "lucide-react";

export default function PaperDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [paper, setPaper] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);
  const [skimReport, setSkimReport] = useState<SkimReport | null>(null);
  const [deepReport, setDeepReport] = useState<DeepDiveReport | null>(null);
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
    } catch {
      /* 静默 */
    } finally {
      setSkimLoading(false);
    }
  };

  const handleDeep = async () => {
    if (!id) return;
    setDeepLoading(true);
    try {
      const report = await pipelineApi.deep(id);
      setDeepReport(report);
    } catch {
      /* 静默 */
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
    } catch {
      /* 静默 */
    } finally {
      setEmbedLoading(false);
    }
  };

  const handleSimilar = async () => {
    if (!id) return;
    setSimilarLoading(true);
    try {
      const res = await paperApi.similar(id);
      setSimilarIds(res.similar_ids);
    } catch {
      /* 静默 */
    } finally {
      setSimilarLoading(false);
    }
  };

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
      {/* 返回按钮 */}
      <button
        onClick={() => navigate("/papers")}
        className="flex items-center gap-1.5 text-sm text-ink-secondary transition-colors hover:text-ink"
      >
        <ArrowLeft className="h-4 w-4" />
        返回论文列表
      </button>

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
        <h1 className="mt-3 text-xl font-bold leading-snug text-ink">
          {paper.title}
        </h1>
        {paper.abstract && (
          <p className="mt-4 leading-relaxed text-ink-secondary">{paper.abstract}</p>
        )}
        {paper.publication_date && (
          <p className="mt-3 text-sm text-ink-tertiary">
            发表日期: {paper.publication_date}
          </p>
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

      {/* Skim 报告 */}
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
            <div className="rounded-lg bg-primary-50 p-4">
              <div className="flex items-start gap-2">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <p className="text-sm font-medium text-ink">
                  {skimReport.one_liner}
                </p>
              </div>
            </div>
            <div>
              <h4 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
                <Lightbulb className="h-4 w-4 text-warning" />
                创新点
              </h4>
              <ul className="space-y-1.5">
                {skimReport.innovations.map((item, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 rounded-lg bg-page px-3 py-2 text-sm text-ink-secondary"
                  >
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      )}

      {/* Deep Dive 报告 */}
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
                    <li
                      key={i}
                      className="flex items-start gap-2 rounded-lg bg-error-light px-3 py-2 text-sm text-ink-secondary"
                    >
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
          <CardHeader
            title="相似论文"
            description={`找到 ${similarIds.length} 篇相似论文`}
          />
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
      <div className="rounded-lg bg-page px-4 py-3">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-secondary">
          {content}
        </p>
      </div>
    </div>
  );
}
