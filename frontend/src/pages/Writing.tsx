/**
 * Writing Assistant - 学术写作助手（支持多轮微调对话）
 * Prompt 模板来源：https://github.com/Leey21/awesome-ai-research-writing
 * @author Color2333
 */
import { useState, useEffect, useCallback, useMemo, useRef, lazy, Suspense } from "react";
import { Button, Spinner } from "@/components/ui";
import { useToast } from "@/contexts/ToastContext";
import { writingApi } from "@/services/api";
import type { WritingTemplate, WritingResult, WritingRefineMessage } from "@/types";
import {
  PenTool,
  Languages,
  BookOpen,
  PenLine,
  Sparkles,
  Minimize2,
  Maximize2,
  ShieldCheck,
  Eraser,
  Image,
  Table,
  BarChart3,
  Eye,
  PieChart,
  Send,
  Copy,
  Check,
  RotateCcw,
  Clock,
  Coins,
  ExternalLink,
  MessageCircle,
  User,
  Bot,
  ScanText,
  ImagePlus,
  Loader2,
  type LucideIcon,
} from "lucide-react";
const ReactMarkdown = lazy(() => import("react-markdown"));
import ImageUploader from "@/components/ImageUploader";

const ICON_MAP: Record<string, LucideIcon> = {
  Languages,
  BookOpen,
  PenLine,
  Sparkles,
  Minimize2,
  Maximize2,
  ShieldCheck,
  Eraser,
  Image,
  Table,
  BarChart3,
  Eye,
  PieChart,
  ScanText,
};

interface HistoryItem {
  id: string;
  action: string;
  label: string;
  inputPreview: string;
  content: string;
  timestamp: Date;
}

export default function Writing() {
  const { toast } = useToast();
  const [templates, setTemplates] = useState<WritingTemplate[]>([]);
  const [selected, setSelected] = useState<WritingTemplate | null>(null);
  const [inputText, setInputText] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WritingResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);

  const [imageBase64, setImageBase64] = useState<string | null>(null);

  // 多轮微调对话
  const [refineMsgs, setRefineMsgs] = useState<WritingRefineMessage[]>([]);
  const [refineInput, setRefineInput] = useState("");
  const [refining, setRefining] = useState(false);
  const refineEndRef = useRef<HTMLDivElement>(null);

  const supportsImage = selected?.supports_image ?? false;

  useEffect(() => {
    writingApi
      .templates()
      .then((res) => {
        setTemplates(res.items);
        if (res.items.length > 0) setSelected(res.items[0]);
      })
      .catch(() => toast("error", "加载模板列表失败"));
  }, [toast]);

  // 结果出来后自动滚到对话末尾
  useEffect(() => {
    refineEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [refineMsgs]);

  const handleProcess = useCallback(async () => {
    if (!selected) return;
    const hasText = !!inputText.trim();
    const hasImage = !!imageBase64;
    if (!hasText && !hasImage) return;

    setLoading(true);
    setResult(null);
    setRefineMsgs([]);
    try {
      let res: WritingResult;
      if (hasImage) {
        res = await writingApi.processMultimodal(selected.action, inputText.trim(), imageBase64!);
      } else {
        res = await writingApi.process(selected.action, inputText.trim());
      }
      setResult(res);
      const inputSummary = hasImage
        ? `[图片] ${inputText.trim() || "(无附加文字)"}`
        : inputText.trim();
      setRefineMsgs([
        { role: "user", content: `[${res.label}] ${inputSummary}` },
        { role: "assistant", content: res.content },
      ]);
      setHistory((prev) =>
        [
          {
            id: crypto.randomUUID(),
            action: res.action,
            label: res.label,
            inputPreview: inputSummary.slice(0, 60),
            content: res.content,
            timestamp: new Date(),
          },
          ...prev,
        ].slice(0, 20)
      );
      toast("success", `${res.label}处理完成`);
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "处理失败");
    } finally {
      setLoading(false);
    }
  }, [selected, inputText, imageBase64, toast]);

  const handleRefine = useCallback(async () => {
    if (!refineInput.trim() || refineMsgs.length < 2) return;
    const instruction = refineInput.trim();
    setRefineInput("");
    const newMsgs: WritingRefineMessage[] = [...refineMsgs, { role: "user", content: instruction }];
    setRefineMsgs(newMsgs);
    setRefining(true);
    try {
      const res = await writingApi.refine(newMsgs);
      const updatedMsgs: WritingRefineMessage[] = [
        ...newMsgs,
        { role: "assistant", content: res.content },
      ];
      setRefineMsgs(updatedMsgs);
      // 更新 result 为最新版本
      setResult((prev) =>
        prev
          ? {
              ...prev,
              content: res.content,
              input_tokens: res.input_tokens,
              output_tokens: res.output_tokens,
            }
          : prev
      );
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "微调失败");
      // 回滚掉用户消息
      setRefineMsgs(refineMsgs);
    } finally {
      setRefining(false);
    }
  }, [refineMsgs, refineInput, toast]);

  const handleRefineKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleRefine();
      }
    },
    [handleRefine]
  );

  const handleCopy = useCallback(async () => {
    if (!result) return;
    await navigator.clipboard.writeText(result.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [result]);

  const handleCopyMsg = useCallback(
    async (content: string) => {
      await navigator.clipboard.writeText(content);
      toast("success", "已复制到剪贴板");
    },
    [toast]
  );

  const handleReset = useCallback(() => {
    setInputText("");
    setImageBase64(null);
    setResult(null);
    setRefineMsgs([]);
    setRefineInput("");
  }, []);

  const handleHistoryClick = useCallback(
    (item: HistoryItem) => {
      const tpl = templates.find((t) => t.action === item.action);
      if (tpl) setSelected(tpl);
      const res: WritingResult = { action: item.action, label: item.label, content: item.content };
      setResult(res);
      setRefineMsgs([
        { role: "user", content: `[${item.label}] ${item.inputPreview}` },
        { role: "assistant", content: item.content },
      ]);
    },
    [templates]
  );

  const categories = useMemo(() => {
    const trans = templates.filter((t) => ["zh_to_en", "en_to_zh"].includes(t.action));
    const polish = templates.filter((t) =>
      ["zh_polish", "en_polish", "compress", "expand"].includes(t.action)
    );
    const check = templates.filter((t) => ["logic_check", "deai"].includes(t.action));
    const gen = templates.filter((t) =>
      [
        "fig_caption",
        "table_caption",
        "experiment_analysis",
        "reviewer",
        "chart_recommend",
      ].includes(t.action)
    );
    const vision = templates.filter((t) => ["ocr_extract"].includes(t.action));
    return [
      { label: "翻译", items: trans },
      { label: "润色与调整", items: polish },
      { label: "检查与优化", items: check },
      { label: "生成与分析", items: gen },
      { label: "图像工具", items: vision },
    ].filter((c) => c.items.length > 0);
  }, [templates]);

  // 对话链中跳过第一条用户消息和第一条AI消息（已在结果区展示）
  const refineConversation = refineMsgs.slice(2);

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-primary/10 rounded-xl p-2.5">
              <PenTool className="text-primary h-5 w-5" />
            </div>
            <div>
              <h1 className="text-ink text-2xl font-bold">写作助手</h1>
              <p className="text-ink-secondary mt-0.5 text-sm">
                AI 驱动的学术写作工具箱，覆盖翻译、润色、去AI味等全场景
              </p>
            </div>
          </div>
          <a
            href="https://github.com/Leey21/awesome-ai-research-writing"
            target="_blank"
            rel="noopener noreferrer"
            className="border-border text-ink-secondary hover:bg-hover hover:text-ink flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors"
          >
            <ExternalLink className="h-3 w-3" />
            Prompt 来源
          </a>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* 左侧：模板选择 */}
        <div className="lg:col-span-3">
          <div className="border-border bg-surface rounded-2xl border p-4 shadow-sm">
            <h3 className="text-ink mb-3 text-sm font-semibold">写作工具</h3>
            <div className="space-y-4">
              {categories.map((cat) => (
                <div key={cat.label}>
                  <p className="text-ink-tertiary mb-1 px-1 text-[10px] font-semibold tracking-wider uppercase">
                    {cat.label}
                  </p>
                  <div className="space-y-0.5">
                    {cat.items.map((tpl) => {
                      const Icon = ICON_MAP[tpl.icon] || PenTool;
                      const isActive = selected?.action === tpl.action;
                      return (
                        <button
                          key={tpl.action}
                          onClick={() => {
                            setSelected(tpl);
                            setResult(null);
                            setRefineMsgs([]);
                            setImageBase64(null);
                          }}
                          className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left transition-all ${
                            isActive
                              ? "bg-primary/8 text-primary shadow-sm"
                              : "text-ink-secondary hover:bg-hover hover:text-ink"
                          }`}
                        >
                          <Icon className="h-4 w-4 shrink-0" />
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium">{tpl.label}</p>
                          </div>
                          {tpl.supports_image && (
                            <div className="shrink-0" title="支持图片输入">
                              <ImagePlus className="text-ink-tertiary/50 h-3 w-3" />
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>

            {/* 历史记录 */}
            {history.length > 0 && (
              <div className="border-border mt-6 border-t pt-4">
                <p className="text-ink-tertiary mb-2 px-1 text-[10px] font-semibold tracking-wider uppercase">
                  最近使用
                </p>
                <div className="max-h-48 space-y-0.5 overflow-y-auto">
                  {history.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => handleHistoryClick(item)}
                      className="text-ink-secondary hover:bg-hover hover:text-ink flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors"
                    >
                      <Clock className="text-ink-tertiary h-3 w-3 shrink-0" />
                      <span className="flex-1 truncate">
                        {item.label}: {item.inputPreview}...
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 右侧：工作区 */}
        <div className="space-y-4 lg:col-span-9">
          {/* 输入区 */}
          {selected && (
            <div className="border-border bg-surface rounded-2xl border p-5 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {(() => {
                    const Icon = ICON_MAP[selected.icon] || PenTool;
                    return <Icon className="text-primary h-4 w-4" />;
                  })()}
                  <h3 className="text-ink text-sm font-semibold">{selected.label}</h3>
                </div>
                <span className="bg-page text-ink-tertiary rounded-full px-2.5 py-0.5 text-[10px] font-medium">
                  {selected.description}
                </span>
              </div>

              {supportsImage && (
                <div className="mb-3">
                  <ImageUploader
                    value={imageBase64}
                    onChange={setImageBase64}
                    hint={`支持 Ctrl+V 粘贴截图 · 拖拽上传 · ${selected.label}将基于图片 + 文字分析`}
                  />
                </div>
              )}

              <textarea
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder={
                  supportsImage && imageBase64 ? "可补充文字说明（可选）" : selected.placeholder
                }
                rows={supportsImage ? 4 : 8}
                className="border-border bg-page text-ink placeholder:text-ink-tertiary/50 focus:border-primary/30 focus:ring-primary/10 w-full resize-y rounded-xl border p-4 text-sm transition-all focus:ring-2 focus:outline-none"
              />

              <div className="mt-3 flex items-center justify-between">
                <span className="text-ink-tertiary text-[10px]">
                  {inputText.length > 0 && `${inputText.length} 字符`}
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<RotateCcw className="h-3.5 w-3.5" />}
                    onClick={handleReset}
                    disabled={!inputText && !result}
                  >
                    重置
                  </Button>
                  <Button
                    icon={<Send className="h-4 w-4" />}
                    onClick={handleProcess}
                    loading={loading}
                    disabled={!inputText.trim() && !imageBase64}
                  >
                    {loading ? "处理中..." : `执行${selected.label}`}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* 加载中（首次处理） */}
          {loading && <Spinner text="AI 正在处理..." />}

          {/* 结果展示 */}
          {!loading && result && (
            <div className="animate-fade-in border-border bg-surface rounded-2xl border p-5 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Sparkles className="text-warning h-4 w-4" />
                  <h3 className="text-ink text-sm font-semibold">
                    {result.label} 结果
                    {refineConversation.length > 0 && (
                      <span className="text-ink-tertiary ml-2 text-[10px] font-normal">
                        (已微调 {Math.floor(refineConversation.length / 2)} 轮)
                      </span>
                    )}
                  </h3>
                </div>
                <div className="flex items-center gap-2">
                  {result.input_tokens != null && (
                    <span className="text-ink-tertiary flex items-center gap-1 text-[10px]">
                      <Coins className="h-3 w-3" />
                      {result.input_tokens} in / {result.output_tokens} out
                    </span>
                  )}
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={
                      copied ? (
                        <Check className="text-success h-3.5 w-3.5" />
                      ) : (
                        <Copy className="h-3.5 w-3.5" />
                      )
                    }
                    onClick={handleCopy}
                  >
                    {copied ? "已复制" : "复制最新"}
                  </Button>
                </div>
              </div>

              {/* 首次结果 */}
              <div className="border-border bg-page rounded-xl border p-5">
                <div className="prose-custom text-ink max-w-none text-sm leading-relaxed">
                  <Suspense fallback={<div className="flex items-center justify-center py-4"><Loader2 className="h-5 w-5 animate-spin text-ink-tertiary" /></div>}>
                    <ReactMarkdown>
                      {refineMsgs.length >= 2 ? refineMsgs[1].content : result.content}
                    </ReactMarkdown>
                  </Suspense>
                </div>
              </div>

              {/* 微调对话链 */}
              {refineConversation.length > 0 && (
                <div className="mt-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <MessageCircle className="text-primary h-3.5 w-3.5" />
                    <span className="text-ink-secondary text-xs font-medium">微调对话</span>
                  </div>
                  <div className="border-border bg-page max-h-[50vh] space-y-2 overflow-y-auto rounded-xl border p-3">
                    {refineConversation.map((msg, idx) => (
                      <div key={`refine-${msg.role}-${idx}`} className={`flex gap-2.5 ${msg.role === "user" ? "" : ""}`}>
                        <div
                          className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                            msg.role === "user" ? "bg-primary/10" : "bg-warning/10"
                          }`}
                        >
                          {msg.role === "user" ? (
                            <User className="text-primary h-3 w-3" />
                          ) : (
                            <Bot className="text-warning h-3 w-3" />
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="mb-0.5 flex items-center gap-2">
                            <span className="text-ink-tertiary text-[10px] font-medium">
                              {msg.role === "user" ? "你" : "AI"}
                            </span>
                            {msg.role === "assistant" && (
                              <button
                                onClick={() => handleCopyMsg(msg.content)}
                                className="text-ink-tertiary hover:text-primary rounded p-0.5 opacity-0 transition-opacity group-hover:opacity-100 [.space-y-2:hover_&]:opacity-100"
                              >
                                <Copy className="h-2.5 w-2.5" />
                              </button>
                            )}
                          </div>
                          <div
                            className={`rounded-lg px-3 py-2 text-sm ${
                              msg.role === "user" ? "bg-primary/5 text-ink" : "bg-surface text-ink"
                            }`}
                          >
                            <div className="prose-custom max-w-none text-sm leading-relaxed">
                              <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}>
                                <ReactMarkdown>{msg.content}</ReactMarkdown>
                              </Suspense>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                    {refining && (
                      <div className="flex gap-2.5">
                        <div className="bg-warning/10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full">
                          <Bot className="text-warning h-3 w-3" />
                        </div>
                        <div className="flex items-center gap-2 px-3 py-2">
                          <div className="flex gap-1">
                            <span className="bg-ink-tertiary h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:0ms]" />
                            <span className="bg-ink-tertiary h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:150ms]" />
                            <span className="bg-ink-tertiary h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:300ms]" />
                          </div>
                          <span className="text-ink-tertiary text-xs">AI 正在微调...</span>
                        </div>
                      </div>
                    )}
                    <div ref={refineEndRef} />
                  </div>
                </div>
              )}

              {/* 微调输入 */}
              <div className="mt-4 flex items-end gap-2">
                <div className="relative flex-1">
                  <textarea
                    value={refineInput}
                    onChange={(e) => setRefineInput(e.target.value)}
                    onKeyDown={handleRefineKeyDown}
                    placeholder="继续微调：例如「再精简一点」「把语气改得更正式」「第二段重写」..."
                    rows={1}
                    className="border-border bg-page text-ink placeholder:text-ink-tertiary/40 focus:border-primary/30 focus:ring-primary/10 w-full resize-none rounded-xl border px-4 py-2.5 pr-10 text-sm transition-all focus:ring-2 focus:outline-none"
                    style={{ minHeight: "40px", maxHeight: "120px" }}
                    onInput={(e) => {
                      const target = e.target as HTMLTextAreaElement;
                      target.style.height = "auto";
                      target.style.height = Math.min(target.scrollHeight, 120) + "px";
                    }}
                  />
                  <MessageCircle className="text-ink-tertiary/30 absolute top-1/2 right-3 h-3.5 w-3.5 -translate-y-1/2" />
                </div>
                <Button
                  size="sm"
                  icon={<Send className="h-3.5 w-3.5" />}
                  onClick={handleRefine}
                  loading={refining}
                  disabled={!refineInput.trim() || refining}
                >
                  微调
                </Button>
              </div>
            </div>
          )}

          {/* 空状态 */}
          {!loading && !result && selected && (
            <div className="border-border flex flex-col items-center justify-center rounded-2xl border border-dashed py-16">
              <div className="bg-page rounded-2xl p-6">
                <PenTool className="text-ink-tertiary/30 h-10 w-10" />
              </div>
              <p className="text-ink-tertiary mt-4 text-sm">在上方输入文本，点击执行即可开始</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
