/**
 * Wiki - Manus 风格结构化知识百科
 * @author Bamzc
 */
import { useState, useEffect, useCallback } from "react";
import { Card, CardHeader, Button, Tabs, Spinner, Empty } from "@/components/ui";
import { wikiApi, generatedApi, tasksApi } from "@/services/api";
import type { TaskStatus } from "@/services/api";
import type {
  PaperWiki,
  TopicWiki,
  TopicWikiContent,
  PaperWikiContent,
  WikiSection,
  WikiReadingItem,
  TimelineEntry,
  PdfExcerpt,
  ScholarMetadataItem,
  GeneratedContentListItem,
  GeneratedContent,
} from "@/types";
import Markdown from "@/components/Markdown";
import {
  Search,
  BookOpen,
  FileText,
  Clock,
  Trash2,
  ChevronRight,
  Lightbulb,
  TrendingUp,
  BookMarked,
  AlertCircle,
  Layers,
  Star,
  ArrowRight,
  Compass,
  GraduationCap,
  Link2,
  ExternalLink,
  Quote,
} from "lucide-react";

const wikiTabs = [
  { id: "topic", label: "主题 Wiki" },
  { id: "paper", label: "论文 Wiki" },
];

export default function Wiki() {
  const [activeTab, setActiveTab] = useState("topic");
  const [keyword, setKeyword] = useState("");
  const [paperId, setPaperId] = useState("");
  const [topicWiki, setTopicWiki] = useState<TopicWiki | null>(null);
  const [paperWiki, setPaperWiki] = useState<PaperWiki | null>(null);
  const [loading, setLoading] = useState(false);

  /* 后台任务状态 */
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskProgress, setTaskProgress] = useState(0);
  const [taskMessage, setTaskMessage] = useState("");

  /* 历史记录 */
  const [history, setHistory] = useState<GeneratedContentListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedContent, setSelectedContent] = useState<GeneratedContent | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const contentType = activeTab === "topic" ? "topic_wiki" : "paper_wiki";

  const loadHistory = useCallback(async (type: string) => {
    setHistoryLoading(true);
    try {
      const res = await generatedApi.list(type, 50);
      setHistory(res.items);
    } catch { /* */ }
    finally { setHistoryLoading(false); }
  }, []);

  useEffect(() => { loadHistory(contentType); }, [contentType, loadHistory]);

  const pollTask = useCallback(async (tid: string) => {
    const poll = async (): Promise<void> => {
      try {
        const status: TaskStatus = await tasksApi.getStatus(tid);
        setTaskProgress(status.progress);
        setTaskMessage(status.message || "处理中...");

        if (status.status === "completed") {
          const result = await tasksApi.getResult(tid);
          setTopicWiki(result as unknown as TopicWiki);
          setPaperWiki(null);
          setLoading(false);
          setTaskId(null);
          loadHistory(contentType);
          return;
        }
        if (status.status === "failed") {
          setLoading(false);
          setTaskId(null);
          return;
        }
        setTimeout(poll, 2000);
      } catch {
        setTimeout(poll, 5000);
      }
    };
    poll();
  }, [contentType, loadHistory]);

  const handleQuery = async () => {
    setLoading(true);
    setSelectedContent(null);
    setTaskProgress(0);
    setTaskMessage("");
    try {
      if (activeTab === "topic" && keyword.trim()) {
        // 后台任务模式
        const { task_id } = await tasksApi.startTopicWiki(keyword);
        setTaskId(task_id);
        setTaskMessage("任务已提交，正在初始化...");
        pollTask(task_id);
        return;
      } else if (activeTab === "paper" && paperId.trim()) {
        const res = await wikiApi.paper(paperId);
        setPaperWiki(res);
        setTopicWiki(null);
      }
      loadHistory(contentType);
    } catch { /* */ }
    finally {
      if (activeTab !== "topic") setLoading(false);
    }
  };

  const handleViewHistory = async (item: GeneratedContentListItem) => {
    setDetailLoading(true);
    setTopicWiki(null);
    setPaperWiki(null);
    try {
      const detail = await generatedApi.detail(item.id);
      setSelectedContent(detail);
    } catch { /* */ }
    finally { setDetailLoading(false); }
  };

  const handleDeleteHistory = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await generatedApi.delete(id);
      setHistory((prev) => prev.filter((h) => h.id !== id));
      if (selectedContent?.id === id) setSelectedContent(null);
    } catch { /* */ }
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("zh-CN", {
      month: "numeric", day: "numeric",
      hour: "2-digit", minute: "2-digit",
      timeZone: "Asia/Shanghai",
    });
  };

  /* 当前应渲染的结构化数据 */
  const topicContent: TopicWikiContent | null =
    topicWiki?.wiki_content ?? null;
  const paperContent: PaperWikiContent | null =
    paperWiki?.wiki_content ?? null;

  const hasContent = !!(topicContent || paperContent || selectedContent);

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-primary/10 p-2.5"><GraduationCap className="h-5 w-5 text-primary" /></div>
          <div>
            <h1 className="text-2xl font-bold text-ink">Wiki</h1>
            <p className="mt-0.5 text-sm text-ink-secondary">AI 驱动的结构化知识百科，基于真实论文数据生成</p>
          </div>
        </div>
      </div>

      <Tabs tabs={wikiTabs} active={activeTab} onChange={(t) => {
        setActiveTab(t);
        setSelectedContent(null);
        setTopicWiki(null);
        setPaperWiki(null);
      }} />

      {/* 搜索 */}
      <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-tertiary" />
            {activeTab === "topic" ? (
              <input
                placeholder="输入主题关键词，如: attention mechanism, transformer..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleQuery()}
                className="h-11 w-full rounded-xl border border-border bg-page pl-10 pr-4 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            ) : (
              <input
                placeholder="输入论文 ID..."
                value={paperId}
                onChange={(e) => setPaperId(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleQuery()}
                className="h-11 w-full rounded-xl border border-border bg-page pl-10 pr-4 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            )}
          </div>
          <Button icon={<BookOpen className="h-4 w-4" />} onClick={handleQuery} loading={loading}>
            生成 Wiki
          </Button>
        </div>
      </div>

      {/* 生成中 — 深度研究风格进度面板 */}
      {loading && (
        <div className="mx-auto max-w-lg py-16">
          <div className="rounded-2xl border border-border bg-card p-8 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <div className="relative">
                <div className="h-12 w-12 animate-spin rounded-full border-[3px] border-primary/20 border-t-primary" />
                <BookOpen className="absolute left-1/2 top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold text-ink">
                  {taskId ? "深度研究中..." : "正在生成..."}
                </p>
                <p className="text-xs text-ink-tertiary">
                  {taskMessage || "收集论文数据、分析引用图谱、AI 撰写文章"}
                </p>
              </div>
            </div>

            {/* 进度条 */}
            {taskId && (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-ink-secondary">
                  <span>{taskMessage}</span>
                  <span className="tabular-nums">{Math.round(taskProgress * 100)}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-primary/10">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-primary to-primary/70 transition-all duration-700 ease-out"
                    style={{ width: `${Math.max(2, taskProgress * 100)}%` }}
                  />
                </div>
                <p className="text-[11px] text-ink-tertiary">
                  任务在后台运行，可以切换页面稍后回来查看
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 主体：左侧历史 + 右侧内容 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* 左侧历史 */}
        <div className="lg:col-span-1">
          <Card>
            <CardHeader title="历史记录" action={<span className="text-xs text-ink-tertiary">{history.length} 条</span>} />
            {historyLoading ? <Spinner text="加载中..." /> : history.length === 0 ? <Empty title="暂无历史记录" /> : (
              <div className="max-h-[70vh] space-y-1 overflow-y-auto">
                {history.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => handleViewHistory(item)}
                    className={`group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2.5 transition-colors hover:bg-primary/5 ${selectedContent?.id === item.id ? "bg-primary/10 text-primary" : "text-ink"}`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{item.title}</p>
                      <div className="mt-0.5 flex items-center gap-1 text-xs text-ink-tertiary">
                        <Clock className="h-3 w-3" />
                        <span>{formatTime(item.created_at)}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={(e) => handleDeleteHistory(item.id, e)}
                        className="rounded p-1 text-ink-tertiary opacity-0 transition-opacity hover:bg-error/10 hover:text-error group-hover:opacity-100"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                      <ChevronRight className="h-4 w-4 text-ink-tertiary" />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* 右侧内容区 */}
        <div className="space-y-6 lg:col-span-4">
          {detailLoading && <Spinner text="加载内容..." />}

          {/* 历史内容展示（markdown） */}
          {!detailLoading && selectedContent && (
            <MarkdownArticle
              title={selectedContent.title}
              markdown={selectedContent.markdown}
              metadata={selectedContent.metadata_json}
            />
          )}

          {/* === 主题 Wiki 结构化渲染 === */}
          {!loading && !selectedContent && topicContent && topicWiki && (
            <TopicWikiView content={topicContent} keyword={topicWiki.keyword} timeline={topicWiki.timeline} survey={topicWiki.survey} />
          )}

          {/* === 论文 Wiki 结构化渲染 === */}
          {!loading && !selectedContent && paperContent && paperWiki && (
            <PaperWikiView content={paperContent} title={paperWiki.title || ""} graph={paperWiki.graph} />
          )}

          {/* 空状态 */}
          {!detailLoading && !loading && !hasContent && (
            <Card className="flex items-center justify-center py-20">
              <div className="text-center">
                <GraduationCap className="mx-auto h-16 w-16 text-ink-tertiary/30" />
                <p className="mt-4 text-sm text-ink-tertiary">
                  输入关键词生成全面的主题百科，或从左侧选择历史记录
                </p>
                <p className="mt-1 text-xs text-ink-tertiary/60">
                  Wiki 基于知识库中的真实论文数据，结合 AI 生成结构化内容
                </p>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}


/* ===========================================================
 * 主题 Wiki 结构化视图 (Manus 风格)
 * =========================================================== */
function TopicWikiView({
  content,
  keyword,
  timeline,
  survey,
}: {
  content: TopicWikiContent;
  keyword: string;
  timeline: TopicWiki["timeline"];
  survey: TopicWiki["survey"];
}) {
  return (
    <div className="space-y-6 animate-fade-in">
      {/* 标题头 */}
      <div className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/5 to-transparent p-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
            <BookOpen className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-ink">{keyword}</h2>
            <p className="text-sm text-ink-secondary">主题百科 · AI 生成</p>
          </div>
        </div>
      </div>

      {/* 概述 */}
      {content.overview && (
        <Card>
          <CardHeader title="概述" action={<Compass className="h-5 w-5 text-primary" />} />
          <div className="prose-custom">
            <Markdown>{content.overview}</Markdown>
          </div>
        </Card>
      )}

      {/* 章节 */}
      {content.sections?.length > 0 && content.sections.map((sec, idx) => (
        <SectionCard key={idx} section={sec} index={idx} />
      ))}

      {/* 方法论演化 */}
      {content.methodology_evolution && (
        <Card>
          <CardHeader title="方法论演化" action={<TrendingUp className="h-5 w-5 text-accent" />} />
          <div className="prose-custom">
            <Markdown>{content.methodology_evolution}</Markdown>
          </div>
        </Card>
      )}

      {/* 引用上下文 + PDF + Scholar */}
      <CitationContextsCard contexts={content.citation_contexts || []} />
      <PdfExcerptsCard excerpts={content.pdf_excerpts || []} />
      <ScholarMetadataCard items={content.scholar_metadata || []} />

      {/* 关键发现 */}
      {content.key_findings?.length > 0 && (
        <Card>
          <CardHeader title="关键发现" action={<Lightbulb className="h-5 w-5 text-warning" />} />
          <div className="space-y-3">
            {content.key_findings.map((finding, i) => (
              <div key={i} className="flex gap-3 rounded-lg bg-warning/5 p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-warning/10 text-xs font-bold text-warning">
                  {i + 1}
                </span>
                <p className="text-sm text-ink leading-relaxed">{finding}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 里程碑论文时间线 */}
      {timeline?.milestones?.length > 0 && (
        <Card>
          <CardHeader title="里程碑论文" description="按年份排列的领域关键论文" action={<Star className="h-5 w-5 text-primary" />} />
          <TimelineView entries={timeline.milestones} />
        </Card>
      )}

      {/* 最具影响力论文 */}
      {timeline?.seminal?.length > 0 && (
        <Card>
          <CardHeader title="最具影响力论文" description="基于引用图谱 PageRank 和引用度计算" />
          <div className="grid gap-3 sm:grid-cols-2">
            {timeline.seminal.slice(0, 8).map((s, i) => (
              <div key={i} className="flex items-start gap-3 rounded-lg border border-border p-3 transition-colors hover:border-primary/30 hover:bg-primary/3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-xs font-bold text-primary">
                  #{i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-ink leading-tight">{s.title}</p>
                  <div className="mt-1 flex items-center gap-2 text-xs text-ink-tertiary">
                    <span>{s.year}</span>
                    <span>·</span>
                    <span>影响力 {s.seminal_score.toFixed(2)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 综述阶段 */}
      {survey?.summary?.stages?.length > 0 && (
        <Card>
          <CardHeader title="发展阶段" action={<Layers className="h-5 w-5 text-accent" />} />
          <div className="space-y-4">
            {survey.summary.stages.map((stage: { name: string; description: string } | string, i: number) => {
              const name = typeof stage === "string" ? stage : stage.name;
              const desc = typeof stage === "string" ? "" : stage.description;
              return (
                <div key={i} className="relative pl-8">
                  <div className="absolute left-0 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-accent/10">
                    <span className="text-xs font-bold text-accent">{i + 1}</span>
                  </div>
                  {i < (survey?.summary?.stages?.length || 0) - 1 && (
                    <div className="absolute left-3 top-7 h-full w-px bg-accent/20" />
                  )}
                  <div>
                    <h4 className="text-sm font-semibold text-ink">{name}</h4>
                    {desc && <p className="mt-1 text-sm text-ink-secondary leading-relaxed">{desc}</p>}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* 未来方向 */}
      {content.future_directions?.length > 0 && (
        <Card>
          <CardHeader title="未来研究方向" action={<ArrowRight className="h-5 w-5 text-success" />} />
          <div className="space-y-2">
            {content.future_directions.map((dir, i) => (
              <div key={i} className="flex gap-3 rounded-lg bg-success/5 p-3">
                <Compass className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                <p className="text-sm text-ink">{dir}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 开放问题 */}
      {survey?.summary?.open_questions?.length > 0 && (
        <Card>
          <CardHeader title="开放问题" action={<AlertCircle className="h-5 w-5 text-error" />} />
          <div className="space-y-2">
            {survey.summary.open_questions.map((q: string, i: number) => (
              <div key={i} className="flex gap-3 rounded-lg border border-error/10 bg-error/3 p-3">
                <span className="text-sm font-medium text-error/60">Q{i + 1}</span>
                <p className="text-sm text-ink">{q}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 推荐阅读 */}
      {content.reading_list?.length > 0 && (
        <Card>
          <CardHeader title="推荐阅读" action={<BookMarked className="h-5 w-5 text-primary" />} />
          <div className="space-y-3">
            {content.reading_list.map((item, i) => (
              <ReadingListItem key={i} item={item} index={i} />
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}


/* ===========================================================
 * 论文 Wiki 结构化视图
 * =========================================================== */
function PaperWikiView({
  content,
  title,
  graph,
}: {
  content: PaperWikiContent;
  title: string;
  graph?: PaperWiki["graph"];
}) {
  return (
    <div className="space-y-6 animate-fade-in">
      {/* 标题头 */}
      <div className="rounded-xl border border-accent/20 bg-gradient-to-br from-accent/5 to-transparent p-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent/10">
            <FileText className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-ink leading-tight">{title}</h2>
            <p className="text-sm text-ink-secondary">论文百科 · AI 生成</p>
          </div>
        </div>
      </div>

      {/* 核心摘要 */}
      {content.summary && (
        <Card>
          <CardHeader title="核心摘要" action={<BookOpen className="h-5 w-5 text-primary" />} />
          <div className="prose-custom">
            <Markdown>{content.summary}</Markdown>
          </div>
        </Card>
      )}

      {/* 主要贡献 */}
      {content.contributions?.length > 0 && (
        <Card>
          <CardHeader title="主要贡献" action={<Star className="h-5 w-5 text-warning" />} />
          <div className="space-y-2">
            {content.contributions.map((c, i) => (
              <div key={i} className="flex gap-3 rounded-lg bg-warning/5 p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-warning/10 text-xs font-bold text-warning">
                  {i + 1}
                </span>
                <p className="text-sm text-ink">{c}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 方法论 */}
      {content.methodology && (
        <Card>
          <CardHeader title="方法论" action={<Layers className="h-5 w-5 text-accent" />} />
          <div className="prose-custom">
            <Markdown>{content.methodology}</Markdown>
          </div>
        </Card>
      )}

      {/* 学术意义 */}
      {content.significance && (
        <Card>
          <CardHeader title="学术意义与影响" action={<TrendingUp className="h-5 w-5 text-success" />} />
          <div className="prose-custom">
            <Markdown>{content.significance}</Markdown>
          </div>
        </Card>
      )}

      {/* 引用上下文 + PDF + Scholar */}
      <CitationContextsCard contexts={content.citation_contexts || []} />
      <PdfExcerptsCard excerpts={content.pdf_excerpts || []} />
      <ScholarMetadataCard items={content.scholar_metadata || []} />

      {/* 引用图 */}
      {graph && (
        <Card>
          <CardHeader
            title="引用关系"
            description={`${graph.nodes?.length || 0} 个节点 · ${graph.edge_count || 0} 条边`}
          />
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-lg bg-primary/5 p-4 text-center">
              <p className="text-2xl font-bold text-primary">{graph.ancestors?.length || 0}</p>
              <p className="mt-1 text-xs text-ink-tertiary">引用的论文</p>
            </div>
            <div className="rounded-lg bg-accent/5 p-4 text-center">
              <p className="text-2xl font-bold text-accent">{graph.descendants?.length || 0}</p>
              <p className="mt-1 text-xs text-ink-tertiary">被引用次数</p>
            </div>
          </div>
        </Card>
      )}

      {/* 局限性 */}
      {content.limitations?.length > 0 && (
        <Card>
          <CardHeader title="局限性" action={<AlertCircle className="h-5 w-5 text-error" />} />
          <div className="space-y-2">
            {content.limitations.map((lim, i) => (
              <div key={i} className="flex gap-3 rounded-lg border border-error/10 bg-error/3 p-3">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-error/60" />
                <p className="text-sm text-ink">{lim}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 相关工作 */}
      {content.related_work_analysis && (
        <Card>
          <CardHeader title="相关工作分析" />
          <div className="prose-custom">
            <Markdown>{content.related_work_analysis}</Markdown>
          </div>
        </Card>
      )}

      {/* 推荐阅读 */}
      {content.reading_suggestions?.length > 0 && (
        <Card>
          <CardHeader title="推荐阅读" action={<BookMarked className="h-5 w-5 text-primary" />} />
          <div className="space-y-3">
            {content.reading_suggestions.map((item, i) => (
              <ReadingListItem key={i} item={item} index={i} />
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}


/* ===========================================================
 * 通用子组件
 * =========================================================== */

function SectionCard({ section, index }: { section: WikiSection; index: number }) {
  return (
    <Card>
      <div className="mb-3 flex items-center gap-2 border-b border-border pb-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10">
          <span className="text-xs font-bold text-primary">{index + 1}</span>
        </div>
        <h3 className="text-base font-semibold text-ink">{section.title}</h3>
      </div>
      {section.key_insight && (
        <div className="mb-4 flex items-start gap-2 rounded-lg bg-warning/5 px-3 py-2">
          <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <p className="text-sm font-medium text-warning-dark">{section.key_insight}</p>
        </div>
      )}
      <div className="prose-custom">
        <Markdown>{section.content}</Markdown>
      </div>
    </Card>
  );
}

function CitationContextsCard({ contexts }: { contexts: string[] }) {
  if (!contexts?.length) return null;
  return (
    <Card>
      <CardHeader title="引用关系上下文" description="论文之间的引用语境" action={<Link2 className="h-5 w-5 text-accent" />} />
      <div className="space-y-2">
        {contexts.slice(0, 15).map((ctx, i) => (
          <div key={i} className="flex gap-3 rounded-lg border border-border bg-page/50 p-3">
            <Quote className="mt-0.5 h-4 w-4 shrink-0 text-accent/60" />
            <p className="text-sm text-ink-secondary italic">{ctx}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

function PdfExcerptsCard({ excerpts }: { excerpts: PdfExcerpt[] }) {
  if (!excerpts?.length) return null;
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  return (
    <Card>
      <CardHeader title="PDF 全文摘录" description="从论文 PDF 中提取的关键内容" action={<FileText className="h-5 w-5 text-success" />} />
      <div className="space-y-3">
        {excerpts.map((ex, i) => (
          <div key={i} className="rounded-lg border border-border p-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-ink">{ex.title}</p>
              <button
                onClick={() => setExpanded(prev => ({ ...prev, [i]: !prev[i] }))}
                className="text-xs text-primary hover:underline"
              >
                {expanded[i] ? "收起" : "展开"}
              </button>
            </div>
            <p className={`mt-2 text-xs text-ink-secondary leading-relaxed ${expanded[i] ? "" : "line-clamp-3"}`}>
              {ex.excerpt}
            </p>
          </div>
        ))}
      </div>
    </Card>
  );
}

function ScholarMetadataCard({ items }: { items: ScholarMetadataItem[] }) {
  if (!items?.length) return null;
  return (
    <Card>
      <CardHeader title="Semantic Scholar 元数据" description="外部学术数据库补充信息" action={<ExternalLink className="h-5 w-5 text-primary" />} />
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item, i) => (
          <div key={i} className="rounded-lg border border-border p-3 transition-colors hover:border-primary/30">
            <p className="text-sm font-medium text-ink leading-tight">{item.title}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {item.year && (
                <span className="inline-flex items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">{item.year}</span>
              )}
              {item.citationCount != null && (
                <span className="inline-flex items-center rounded-md bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">
                  {item.citationCount.toLocaleString()} 引用
                </span>
              )}
              {item.venue && (
                <span className="inline-flex items-center rounded-md bg-page px-2 py-0.5 text-xs text-ink-tertiary">{item.venue}</span>
              )}
            </div>
            {item.tldr && (
              <p className="mt-2 text-xs text-ink-secondary leading-relaxed">{item.tldr}</p>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function TimelineView({ entries }: { entries: TimelineEntry[] }) {
  return (
    <div className="space-y-3">
      {entries.slice(0, 12).map((entry, i) => (
        <div key={i} className="relative flex gap-4 pl-4">
          <div className="absolute left-0 top-2 h-2 w-2 rounded-full bg-primary" />
          {i < entries.length - 1 && (
            <div className="absolute left-[3px] top-4 h-full w-px bg-primary/20" />
          )}
          <div className="min-w-0 flex-1 pb-4">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                {entry.year}
              </span>
              <span className="text-xs text-ink-tertiary">
                影响力 {entry.seminal_score.toFixed(2)}
              </span>
            </div>
            <p className="mt-1 text-sm font-medium text-ink">{entry.title}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function ReadingListItem({ item, index }: { item: WikiReadingItem; index: number }) {
  return (
    <div className="flex gap-3 rounded-lg border border-border p-3 transition-colors hover:border-primary/30">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
        <BookMarked className="h-4 w-4 text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{item.title}</p>
        <div className="mt-0.5 flex items-center gap-2">
          {item.year && <span className="text-xs text-ink-tertiary">{item.year}</span>}
          {item.reason && (
            <>
              {item.year && <span className="text-xs text-ink-tertiary">·</span>}
              <span className="text-xs text-ink-secondary">{item.reason}</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * 历史内容 markdown 渲染（回退用）
 */
function MarkdownArticle({
  title,
  markdown,
  metadata,
}: {
  title: string;
  markdown: string;
  metadata?: Record<string, unknown>;
}) {
  /* 尝试从 metadata 解析 wiki_content */
  const wikiContent = metadata?.wiki_content as TopicWikiContent | PaperWikiContent | undefined;
  const isTopicWiki = metadata?.keyword !== undefined;

  if (wikiContent && "overview" in wikiContent) {
    return (
      <TopicWikiView
        content={wikiContent as TopicWikiContent}
        keyword={String(metadata?.keyword || title)}
        timeline={metadata?.timeline as TopicWiki["timeline"]}
        survey={metadata?.survey as TopicWiki["survey"]}
      />
    );
  }

  if (wikiContent && "summary" in wikiContent) {
    return (
      <PaperWikiView
        content={wikiContent as PaperWikiContent}
        title={title}
        graph={metadata?.graph as PaperWiki["graph"]}
      />
    );
  }

  /* 纯 markdown 回退 */
  return (
    <Card className="animate-fade-in">
      <CardHeader title={title} action={<BookOpen className="h-5 w-5 text-primary" />} />
      <div className="prose-custom">
        <Markdown>{markdown}</Markdown>
      </div>
    </Card>
  );
}
