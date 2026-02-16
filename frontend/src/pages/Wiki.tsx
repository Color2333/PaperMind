/**
 * Wiki - 论文/主题 Wiki（含历史记录持久化）
 * 覆盖 API: GET /wiki/paper/{id}, GET /wiki/topic, GET /generated/list, GET /generated/{id}
 * @author Bamzc
 */
import { useState, useEffect, useCallback } from "react";
import { Card, CardHeader, Button, Input, Tabs, Spinner, Empty } from "@/components/ui";
import { wikiApi, generatedApi } from "@/services/api";
import type { PaperWiki, TopicWiki, GeneratedContentListItem, GeneratedContent } from "@/types";
import { Search, BookOpen, FileText, Clock, Trash2, ChevronRight } from "lucide-react";

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
    } catch {
      /* 静默 */
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory(contentType);
  }, [contentType, loadHistory]);

  const handleQuery = async () => {
    setLoading(true);
    setSelectedContent(null);
    try {
      if (activeTab === "topic" && keyword.trim()) {
        const res = await wikiApi.topic(keyword);
        setTopicWiki(res);
        setPaperWiki(null);
      } else if (activeTab === "paper" && paperId.trim()) {
        const res = await wikiApi.paper(paperId);
        setPaperWiki(res);
        setTopicWiki(null);
      }
      loadHistory(contentType);
    } catch {
      /* 静默 */
    } finally {
      setLoading(false);
    }
  };

  const handleViewHistory = async (item: GeneratedContentListItem) => {
    setDetailLoading(true);
    setTopicWiki(null);
    setPaperWiki(null);
    try {
      const detail = await generatedApi.detail(item.id);
      setSelectedContent(detail);
    } catch {
      /* 静默 */
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDeleteHistory = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await generatedApi.delete(id);
      setHistory((prev) => prev.filter((h) => h.id !== id));
      if (selectedContent?.id === id) setSelectedContent(null);
    } catch {
      /* 静默 */
    }
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
  };

  /* 当前展示的 markdown */
  const displayMarkdown =
    selectedContent?.markdown ??
    (activeTab === "topic" ? topicWiki?.markdown : paperWiki?.markdown) ??
    null;

  const displayTitle =
    selectedContent?.title ??
    (activeTab === "topic" && topicWiki ? `主题 Wiki: ${topicWiki.keyword}` : null) ??
    (activeTab === "paper" && paperWiki ? "论文 Wiki" : null);

  return (
    <div className="animate-fade-in space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Wiki</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          自动生成的论文和主题知识百科，历史记录自动保存
        </p>
      </div>

      <Tabs tabs={wikiTabs} active={activeTab} onChange={(t) => { setActiveTab(t); setSelectedContent(null); setTopicWiki(null); setPaperWiki(null); }} />

      {/* 生成输入 */}
      <Card>
        <div className="flex gap-3">
          <div className="flex-1">
            {activeTab === "topic" ? (
              <Input
                placeholder="输入主题关键词，如: attention mechanism..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
            ) : (
              <Input
                placeholder="输入论文 ID..."
                value={paperId}
                onChange={(e) => setPaperId(e.target.value)}
              />
            )}
          </div>
          <Button
            icon={<Search className="h-4 w-4" />}
            onClick={handleQuery}
            loading={loading}
          >
            生成 Wiki
          </Button>
        </div>
      </Card>

      {loading && <Spinner text="正在生成 Wiki..." />}

      {/* 双栏布局：左侧历史列表 + 右侧内容 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* 左侧历史列表 */}
        <div className="lg:col-span-1">
          <Card>
            <CardHeader
              title="历史记录"
              action={
                <span className="text-xs text-ink-tertiary">
                  {history.length} 条
                </span>
              }
            />
            {historyLoading ? (
              <Spinner text="加载中..." />
            ) : history.length === 0 ? (
              <Empty title="暂无历史记录" />
            ) : (
              <div className="max-h-[60vh] space-y-1 overflow-y-auto">
                {history.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => handleViewHistory(item)}
                    className={`group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2.5 transition-colors hover:bg-primary/5 ${
                      selectedContent?.id === item.id
                        ? "bg-primary/10 text-primary"
                        : "text-ink"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {item.title}
                      </p>
                      <div className="mt-0.5 flex items-center gap-1 text-xs text-ink-tertiary">
                        <Clock className="h-3 w-3" />
                        <span>{formatTime(item.created_at)}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={(e) => handleDeleteHistory(item.id, e)}
                        className="rounded p-1 text-ink-tertiary opacity-0 transition-opacity hover:bg-error/10 hover:text-error group-hover:opacity-100"
                        title="删除"
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
        <div className="lg:col-span-3">
          {detailLoading && <Spinner text="加载内容..." />}

          {!detailLoading && displayMarkdown && displayTitle && (
            <Card className="animate-fade-in">
              <CardHeader
                title={displayTitle}
                action={
                  activeTab === "topic" ? (
                    <BookOpen className="h-5 w-5 text-primary" />
                  ) : (
                    <FileText className="h-5 w-5 text-primary" />
                  )
                }
              />
              <div className="markdown-body">
                <div
                  dangerouslySetInnerHTML={{
                    __html: simpleMarkdown(displayMarkdown),
                  }}
                />
              </div>
            </Card>
          )}

          {/* 引用图信息（仅论文 Wiki 且有 graph 时） */}
          {!detailLoading && !selectedContent && paperWiki?.graph && (
            <Card className="mt-4">
              <CardHeader
                title="引用关系"
                description={`${paperWiki.graph.nodes.length} 个节点 · ${paperWiki.graph.edge_count} 条边`}
              />
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-lg bg-page p-3">
                  <p className="text-xs text-ink-tertiary">祖先引用</p>
                  <p className="mt-1 text-lg font-bold text-ink">
                    {paperWiki.graph.ancestors.length}
                  </p>
                </div>
                <div className="rounded-lg bg-page p-3">
                  <p className="text-xs text-ink-tertiary">后裔引用</p>
                  <p className="mt-1 text-lg font-bold text-ink">
                    {paperWiki.graph.descendants.length}
                  </p>
                </div>
              </div>
            </Card>
          )}

          {/* 空状态 */}
          {!detailLoading && !displayMarkdown && !loading && (
            <Card className="flex items-center justify-center py-16">
              <div className="text-center">
                <BookOpen className="mx-auto h-12 w-12 text-ink-tertiary/40" />
                <p className="mt-3 text-sm text-ink-tertiary">
                  输入关键词生成新的 Wiki，或从左侧选择历史记录查看
                </p>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * 简易 Markdown 转 HTML
 */
function simpleMarkdown(md: string): string {
  return md
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>")
    .replace(/^> (.+)$/gm, "<blockquote><p>$1</p></blockquote>")
    .replace(/---/g, "<hr>")
    .replace(/\n\n/g, "</p><p>")
    .replace(/^(?!<[hublop])/gm, (m) => (m ? `<p>${m}` : ""))
    .replace(/\n/g, "<br>");
}
