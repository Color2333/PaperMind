/**
 * Papers - 论文列表与摄入
 * 覆盖 API: GET /papers/latest, POST /ingest/arxiv, POST /pipelines/skim|embed
 * @author Bamzc
 */
import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardHeader, Button, Badge, Input, Empty, Spinner, Modal } from "@/components/ui";
import { paperApi, ingestApi, topicApi, pipelineApi } from "@/services/api";
import { formatDate, truncate } from "@/lib/utils";
import type { Paper, Topic } from "@/types";
import {
  FileText,
  Download,
  Search,
  RefreshCw,
  ExternalLink,
  BookOpen,
  Eye,
  BookMarked,
  ChevronRight,
  Cpu,
  Zap,
  CheckCircle2,
  Filter,
} from "lucide-react";

const STATUS_TABS = [
  { key: "", label: "全部", icon: Filter },
  { key: "unread", label: "未读", icon: BookOpen },
  { key: "skimmed", label: "已粗读", icon: Eye },
  { key: "deep_read", label: "已精读", icon: BookMarked },
] as const;

const statusConfig: Record<string, { label: string; variant: "default" | "warning" | "success" }> = {
  unread: { label: "未读", variant: "default" },
  skimmed: { label: "已粗读", variant: "warning" },
  deep_read: { label: "已精读", variant: "success" },
};

export default function Papers() {
  const navigate = useNavigate();
  const [papers, setPapers] = useState<Paper[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [ingestOpen, setIngestOpen] = useState(false);
  const [limit, setLimit] = useState(50);
  const [statusFilter, setStatusFilter] = useState("");
  const [topicFilter, setTopicFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchProgress, setBatchProgress] = useState("");

  const loadPapers = useCallback(async () => {
    setLoading(true);
    try {
      const [res, topicRes] = await Promise.all([
        paperApi.latest(limit, statusFilter || undefined, topicFilter || undefined),
        topicApi.list(),
      ]);
      setPapers(res.items);
      setTopics(topicRes.items);
      setSelected(new Set());
    } catch {
      /* 静默 */
    } finally {
      setLoading(false);
    }
  }, [limit, statusFilter, topicFilter]);

  useEffect(() => {
    loadPapers();
  }, [loadPapers]);

  const filtered = papers.filter(
    (p) =>
      p.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      p.arxiv_id?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((p) => p.id)));
    }
  };

  const handleBatchSkim = async () => {
    const ids = [...selected].filter((id) => {
      const p = papers.find((pp) => pp.id === id);
      return p && p.read_status === "unread";
    });
    if (ids.length === 0) { setBatchProgress("没有可粗读的未读论文"); return; }
    setBatchRunning(true);
    let done = 0;
    for (const id of ids) {
      setBatchProgress(`粗读中 ${++done}/${ids.length}...`);
      try { await pipelineApi.skim(id); } catch { /* 继续 */ }
    }
    setBatchProgress(`完成！成功粗读 ${done} 篇`);
    setBatchRunning(false);
    await loadPapers();
  };

  const handleBatchEmbed = async () => {
    const ids = [...selected].filter((id) => {
      const p = papers.find((pp) => pp.id === id);
      return p && !p.has_embedding;
    });
    if (ids.length === 0) { setBatchProgress("选中论文已全部嵌入"); return; }
    setBatchRunning(true);
    let done = 0;
    for (const id of ids) {
      setBatchProgress(`嵌入中 ${++done}/${ids.length}...`);
      try { await pipelineApi.embed(id); } catch { /* 继续 */ }
    }
    setBatchProgress(`完成！成功嵌入 ${done} 篇`);
    setBatchRunning(false);
    await loadPapers();
  };

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink">Papers</h1>
          <p className="mt-1 text-sm text-ink-secondary">
            浏览和管理已收录的论文
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={loadPapers}
          >
            刷新
          </Button>
          <Button
            size="sm"
            icon={<Download className="h-3.5 w-3.5" />}
            onClick={() => setIngestOpen(true)}
          >
            ArXiv 摄入
          </Button>
        </div>
      </div>

      {/* 阅读状态 Tab */}
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setStatusFilter(tab.key)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-all ${
              statusFilter === tab.key
                ? "bg-primary-light text-primary"
                : "bg-hover text-ink-secondary hover:text-ink"
            }`}
          >
            <tab.icon className="h-3.5 w-3.5" />
            {tab.label}
          </button>
        ))}

        {/* 主题筛选 */}
        {topics.length > 0 && (
          <select
            value={topicFilter}
            onChange={(e) => setTopicFilter(e.target.value)}
            className="ml-auto h-9 rounded-lg border border-border bg-surface px-3 text-xs text-ink focus:border-primary focus:outline-none"
          >
            <option value="">全部主题</option>
            {topics.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        )}
      </div>

      {/* 搜索 + 数量 */}
      <div className="flex gap-3">
        <div className="relative max-w-sm flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-tertiary" />
          <input
            type="text"
            placeholder="搜索论文标题或 ArXiv ID..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="h-10 w-full rounded-lg border border-border bg-surface pl-9 pr-4 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
        </div>
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="h-10 rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-primary focus:outline-none"
        >
          <option value={20}>20 篇</option>
          <option value={50}>50 篇</option>
          <option value={100}>100 篇</option>
          <option value={200}>200 篇</option>
        </select>
      </div>

      {/* 批量操作栏 */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-primary/30 bg-primary-light px-4 py-3">
          <span className="text-sm font-medium text-primary">已选 {selected.size} 篇</span>
          <Button size="sm" variant="secondary" onClick={handleBatchSkim} disabled={batchRunning}>
            <Zap className="mr-1 h-3.5 w-3.5" /> 批量粗读
          </Button>
          <Button size="sm" variant="secondary" onClick={handleBatchEmbed} disabled={batchRunning}>
            <Cpu className="mr-1 h-3.5 w-3.5" /> 批量嵌入
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())} disabled={batchRunning}>
            取消选择
          </Button>
          {batchProgress && <span className="ml-auto text-xs text-ink-secondary">{batchProgress}</span>}
        </div>
      )}

      {loading ? (
        <Spinner text="加载论文..." />
      ) : filtered.length === 0 ? (
        <Empty
          icon={<FileText className="h-12 w-12" />}
          title="暂无论文"
          description="从 ArXiv 摄入论文开始你的研究"
          action={
            <Button size="sm" onClick={() => setIngestOpen(true)}>
              开始摄入
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {/* 全选 */}
          <div className="flex items-center gap-2 px-1">
            <input
              type="checkbox"
              checked={selected.size === filtered.length && filtered.length > 0}
              onChange={toggleSelectAll}
              className="h-4 w-4 rounded border-border text-primary focus:ring-primary/30"
            />
            <span className="text-xs text-ink-tertiary">
              {filtered.length} 篇论文
            </span>
          </div>
          {filtered.map((paper) => {
            const sc = statusConfig[paper.read_status] || statusConfig.unread;
            return (
              <Card
                key={paper.id}
                className={`transition-all hover:border-primary/30 hover:shadow-md ${selected.has(paper.id) ? "ring-2 ring-primary/30" : ""}`}
                padding={false}
              >
                <div className="flex items-start gap-4 p-5">
                  {/* 选择框 */}
                  <input
                    type="checkbox"
                    checked={selected.has(paper.id)}
                    onChange={() => toggleSelect(paper.id)}
                    className="mt-1 h-4 w-4 shrink-0 rounded border-border text-primary focus:ring-primary/30"
                    onClick={(e) => e.stopPropagation()}
                  />
                  <button
                    className="flex min-w-0 flex-1 items-start gap-4 text-left"
                    onClick={() => navigate(`/papers/${paper.id}`)}
                  >
                    <div className="mt-0.5 shrink-0 rounded-lg bg-primary-light p-2.5">
                      {paper.read_status === "deep_read" ? (
                        <BookMarked className="h-5 w-5 text-primary" />
                      ) : paper.read_status === "skimmed" ? (
                        <Eye className="h-5 w-5 text-warning" />
                      ) : (
                        <BookOpen className="h-5 w-5 text-ink-tertiary" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start gap-2">
                        <h3 className="text-sm font-semibold leading-snug text-ink">
                          {paper.title}
                        </h3>
                        <Badge variant={sc.variant} className="shrink-0">
                          {sc.label}
                        </Badge>
                        {paper.has_embedding && (
                          <span className="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-info-light px-2 py-0.5 text-xs text-info">
                            <CheckCircle2 className="h-3 w-3" /> 已嵌入
                          </span>
                        )}
                      </div>
                      {paper.abstract && (
                        <p className="mt-1.5 text-sm leading-relaxed text-ink-secondary">
                          {truncate(paper.abstract, 200)}
                        </p>
                      )}
                      <div className="mt-2 flex items-center gap-3 text-xs text-ink-tertiary">
                        {paper.arxiv_id && (
                          <span className="flex items-center gap-1">
                            <ExternalLink className="h-3 w-3" />
                            {paper.arxiv_id}
                          </span>
                        )}
                        {paper.publication_date && (
                          <span>{formatDate(paper.publication_date)}</span>
                        )}
                      </div>
                    </div>
                    <ChevronRight className="mt-1 h-5 w-5 shrink-0 text-ink-tertiary" />
                  </button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <IngestModal
        open={ingestOpen}
        onClose={() => setIngestOpen(false)}
        onDone={loadPapers}
      />
    </div>
  );
}

function IngestModal({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [query, setQuery] = useState("");
  const [maxResults, setMaxResults] = useState(20);
  const [topicId, setTopicId] = useState("");
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<number | null>(null);

  useEffect(() => {
    if (open) {
      topicApi.list().then((r) => setTopics(r.items)).catch(() => {});
      setResult(null);
    }
  }, [open]);

  const handleIngest = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const res = await ingestApi.arxiv(query, maxResults, topicId || undefined);
      setResult(res.ingested);
      onDone();
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="ArXiv 论文摄入">
      <div className="space-y-4">
        <Input
          label="搜索查询"
          placeholder="例如: transformer attention mechanism"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="最大数量"
            type="number"
            value={maxResults}
            onChange={(e) => setMaxResults(parseInt(e.target.value) || 20)}
          />
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-ink">关联主题</label>
            <select
              value={topicId}
              onChange={(e) => setTopicId(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-primary focus:outline-none"
            >
              <option value="">不关联</option>
              {topics.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        {result !== null && (
          <div className="rounded-lg bg-success-light p-3 text-sm text-success">
            成功摄入 {result} 篇论文
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            关闭
          </Button>
          <Button onClick={handleIngest} loading={loading}>
            开始摄入
          </Button>
        </div>
      </div>
    </Modal>
  );
}
