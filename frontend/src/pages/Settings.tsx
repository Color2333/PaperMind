/**
 * Claude 风格的设置页面 - 左侧导航 + 右侧内容
 */
import { useState, useCallback, useEffect } from "react";
import {
  Cpu,
  Mail,
  GitBranch,
  Settings,
  ChevronRight,
  Plus,
  Trash2,
  Pencil,
  Power,
  Eye,
  EyeOff,
  Server,
  RefreshCw,
  Play,
  Link2,
  BookOpen,
  Activity,
} from "lucide-react";
import { useToast } from "@/contexts/ToastContext";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import {
  llmConfigApi,
  pipelineApi,
  citationApi,
  jobApi,
  systemApi,
  emailConfigApi,
  dailyReportApi,
} from "@/services/api";
import { cn } from "@/lib/utils";
import { formatDuration, timeAgo } from "@/lib/utils";

type SettingsTab = "llm" | "email" | "pipeline" | "ops";

const NAV_ITEMS: { key: SettingsTab; label: string; icon: typeof Cpu }[] = [
  { key: "llm", label: "LLM 配置", icon: Cpu },
  { key: "email", label: "邮箱与报告", icon: Mail },
  { key: "pipeline", label: "Pipeline", icon: GitBranch },
  { key: "ops", label: "运维", icon: Settings },
];

const PROVIDER_PRESETS: Record<string, { label: string; base_url: string; models: Record<string, string> }> = {
  zhipu: {
    label: "智谱 AI",
    base_url: "https://open.bigmodel.cn/api/paas/v4/",
    models: { model_skim: "glm-4.7", model_deep: "glm-4.7", model_vision: "glm-4.6v", model_embedding: "embedding-3", model_fallback: "glm-4.7" },
  },
};

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("llm");

  return (
    <div className="flex h-full">
      {/* 左侧边栏 */}
      <aside className="w-56 shrink-0 border-r border-border bg-page">
        <div className="p-4">
          <h1 className="mb-4 text-sm font-semibold text-ink">设置</h1>
          <nav className="space-y-0.5">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.key;
              return (
                <button
                  type="button"
                  key={item.key}
                  onClick={() => setActiveTab(item.key)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-ink-secondary hover:bg-hover hover:text-ink"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                  {isActive && <ChevronRight className="ml-auto h-3 w-3" />}
                </button>
              );
            })}
          </nav>
        </div>
      </aside>

      {/* 右侧内容 */}
      <main className="flex-1 overflow-y-auto bg-surface">
        <div className="mx-auto max-w-3xl p-8">
          {activeTab === "llm" && <LLMSettings />}
          {activeTab === "email" && <EmailSettings />}
          {activeTab === "pipeline" && <PipelineSettings />}
          {activeTab === "ops" && <OpsSettings />}
        </div>
      </main>
    </div>
  );
}

/* ======== LLM 设置 ======== */
function LLMSettings() {
  const { toast } = useToast();
  const [configs, setConfigs] = useState<any[]>([]);
  const [activeInfo, setActiveInfo] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editCfg, setEditCfg] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const [listRes, activeRes] = await Promise.all([llmConfigApi.list(), llmConfigApi.active()]);
      setConfigs(listRes.items || []);
      setActiveInfo(activeRes);
    } catch {
      toast("error", "加载 LLM 配置失败");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">LLM 模型配置</h2>
        <p className="mt-1 text-sm text-ink-secondary">配置 AI 模型，管理成本</p>
      </div>

      {/* 当前激活 */}
      {activeInfo && (
        <div className="rounded-xl border border-primary/30 bg-primary/5 p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/20">
                <Cpu className="h-6 w-6 text-primary" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink">{activeInfo.config?.name || "当前配置"}</span>
                  <Badge variant="success">使用中</Badge>
                </div>
                <div className="mt-1 flex gap-3 text-xs text-ink-secondary">
                  <span>文本: {activeInfo.config?.model_skim}</span>
                  <span>视觉: {activeInfo.config?.model_vision || "未设置"}</span>
                </div>
              </div>
            </div>
            <Button variant="secondary" size="sm" onClick={() => setEditCfg(activeInfo.config)}>
              <Pencil className="mr-1.5 h-3.5 w-3.5" />
              编辑
            </Button>
          </div>
        </div>
      )}

      {/* 配置列表 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-ink">所有配置</h3>
          <Button variant="primary" size="sm" onClick={() => setShowAdd(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            添加配置
          </Button>
        </div>

        {configs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-8 text-center">
            <Cpu className="mx-auto h-8 w-8 text-ink-tertiary" />
            <p className="mt-2 text-sm text-ink-secondary">暂无自定义配置</p>
          </div>
        ) : (
          <div className="space-y-2">
            {configs.map((cfg) => (
              <div
                key={cfg.id}
                className={cn(
                  "flex items-center justify-between rounded-xl border p-4 transition-colors",
                  cfg.is_active ? "border-primary/30 bg-primary/5" : "border-border bg-page hover:border-ink-tertiary"
                )}
              >
                <div className="flex items-center gap-4">
                  <div className={cn("flex h-10 w-10 items-center justify-center rounded-lg", cfg.is_active ? "bg-primary/20" : "bg-hover")}>
                    <Server className={cn("h-5 w-5", cfg.is_active ? "text-primary" : "text-ink-tertiary")} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink">{cfg.name}</span>
                      {cfg.is_active && <Badge variant="default">激活</Badge>}
                      <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">{cfg.provider}</span>
                    </div>
                    <div className="mt-1 flex gap-2 text-xs text-ink-tertiary">
                      <span>{cfg.api_key_masked}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {!cfg.is_active && (
                    <Button variant="ghost" size="sm" onClick={async () => { await llmConfigApi.activate(cfg.id); load(); }}>
                    <Power className="mr-1.5 h-3.5 w-3.5" />
                    激活
                  </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => setEditCfg(cfg)}><Pencil className="h-3.5 w-3.5" /></Button>
                  <Button variant="ghost" size="sm" onClick={async () => { if (confirm("确定删除？")) { await llmConfigApi.delete(cfg.id); load(); } }} disabled={cfg.is_active}>
                    <Trash2 className="h-3.5 w-3.5 text-error" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 添加/编辑弹窗 */}
      {(showAdd || editCfg) && (
        <ConfigModal
          config={editCfg}
          onClose={() => { setShowAdd(false); setEditCfg(null); }}
          onSaved={() => { setShowAdd(false); setEditCfg(null); load(); }}
        />
      )}
    </div>
  );
}

function ConfigModal({ config, onClose, onSaved }: { config?: any; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: config?.name || "",
    provider: config?.provider || "zhipu",
    api_key: "",
    api_base_url: config?.api_base_url || PROVIDER_PRESETS.zhipu.base_url,
    model_skim: config?.model_skim || "glm-4.7",
    model_deep: config?.model_deep || "glm-4.7",
    model_vision: config?.model_vision || "glm-4.6v",
    model_embedding: config?.model_embedding || "embedding-3",
    model_fallback: config?.model_fallback || "glm-4.7",
  });
  const [showKey, setShowKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const setField = (k: string, v: string) => setForm((p) => ({ ...p, [k]: v }));

  const handleProviderChange = (provider: string) => {
    const preset = PROVIDER_PRESETS[provider];
    if (preset) {
      setForm((p) => ({ ...p, provider, api_base_url: preset.base_url, ...preset.models }));
    }
  };

  const handleSubmit = async () => {
    if (!form.name.trim()) { setError("请输入配置名称"); return; }
    if (!form.api_key.trim() && !config) { setError("请输入 API Key"); return; }
    setSubmitting(true);
    setError("");
    try {
      if (config) {
        const payload: any = { name: form.name, provider: form.provider, api_base_url: form.api_base_url, model_skim: form.model_skim, model_deep: form.model_deep, model_vision: form.model_vision, model_embedding: form.model_embedding, model_fallback: form.model_fallback };
        if (form.api_key) payload.api_key = form.api_key;
        await llmConfigApi.update(config.id, payload);
      } else {
        await llmConfigApi.create(form);
      }
      onSaved();
    } catch (err: any) {
      setError(err.message || "操作失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-lg rounded-2xl border border-border bg-surface p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-ink">{config ? "编辑配置" : "添加配置"}</h3>
        {error && <div className="mt-3 rounded-lg bg-error-light px-3 py-2 text-xs text-error">{error}</div>}
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="cfg-name" className="mb-1.5 block text-xs font-medium text-ink-secondary">配置名称</label>
              <input id="cfg-name" value={form.name} onChange={(e) => setField("name", e.target.value)} className="w-full rounded-lg border border-border bg-page px-3 py-2 text-sm text-ink outline-none focus:border-primary" placeholder="如：智谱 AI" />
            </div>
            <div>
              <label htmlFor="cfg-provider" className="mb-1.5 block text-xs font-medium text-ink-secondary">服务商</label>
              <select id="cfg-provider" value={form.provider} onChange={(e) => handleProviderChange(e.target.value)} className="w-full rounded-lg border border-border bg-page px-3 py-2 text-sm text-ink outline-none focus:border-primary">
                {Object.entries(PROVIDER_PRESETS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label htmlFor="cfg-apikey" className="mb-1.5 block text-xs font-medium text-ink-secondary">API Key</label>
            <div className="relative">
              <input id="cfg-apikey" type={showKey ? "text" : "password"} value={form.api_key} onChange={(e) => setField("api_key", e.target.value)} className="w-full rounded-lg border border-border bg-page px-3 py-2 pr-10 text-sm text-ink outline-none focus:border-primary" placeholder={config ? "留空保持不变" : "输入 API Key"} />
              <button type="button" onClick={() => setShowKey(!showKey)} className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink">
                {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <div>
            <label htmlFor="cfg-baseurl" className="mb-1.5 block text-xs font-medium text-ink-secondary">Base URL（可选）</label>
            <input id="cfg-baseurl" value={form.api_base_url} onChange={(e) => setField("api_base_url", e.target.value)} className="w-full rounded-lg border border-border bg-page px-3 py-2 text-sm text-ink outline-none focus:border-primary" placeholder="留空使用默认" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="cfg-model-skim" className="mb-1.5 block text-xs font-medium text-ink-secondary">文本模型</label>
              <input id="cfg-model-skim" value={form.model_skim} onChange={(e) => setField("model_skim", e.target.value)} className="w-full rounded-lg border border-border bg-page px-3 py-2 text-sm text-ink outline-none focus:border-primary" />
            </div>
            <div>
              <label htmlFor="cfg-model-vision" className="mb-1.5 block text-xs font-medium text-ink-secondary">视觉模型</label>
              <input id="cfg-model-vision" value={form.model_vision} onChange={(e) => setField("model_vision", e.target.value)} className="w-full rounded-lg border border-border bg-page px-3 py-2 text-sm text-ink outline-none focus:border-primary" />
            </div>
            <div>
              <label htmlFor="cfg-model-embedding" className="mb-1.5 block text-xs font-medium text-ink-secondary">嵌入模型</label>
              <input id="cfg-model-embedding" value={form.model_embedding} onChange={(e) => setField("model_embedding", e.target.value)} className="w-full rounded-lg border border-border bg-page px-3 py-2 text-sm text-ink outline-none focus:border-primary" />
            </div>
            <div>
              <label htmlFor="cfg-model-fallback" className="mb-1.5 block text-xs font-medium text-ink-secondary">备用模型</label>
              <input id="cfg-model-fallback" value={form.model_fallback} onChange={(e) => setField("model_fallback", e.target.value)} className="w-full rounded-lg border border-border bg-page px-3 py-2 text-sm text-ink outline-none focus:border-primary" />
            </div>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting}>{submitting ? <Spinner className="mr-1.5 h-3.5 w-3.5" /> : null}{config ? "保存" : "创建"}</Button>
        </div>
      </div>
    </div>
  );
}

/* ======== 邮箱设置 ======== */
function EmailSettings() {
  const { toast } = useToast();
  const [emailConfigs, setEmailConfigs] = useState<any[]>([]);
  const [dailyReport, setDailyReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const loadEmails = useCallback(async () => {
    try { setEmailConfigs(await emailConfigApi.list() || []); } catch { toast("error", "加载邮箱配置失败"); }
  }, [toast]);

  const loadDaily = useCallback(async () => {
    try { setDailyReport(await dailyReportApi.getConfig()); } catch { toast("error", "加载报告配置失败"); }
  }, [toast]);

  useEffect(() => { Promise.all([loadEmails(), loadDaily()]).finally(() => setLoading(false)); }, [loadEmails, loadDaily]);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-semibold text-ink">邮箱与报告</h2>
        <p className="mt-1 text-sm text-ink-secondary">配置邮件发送和每日报告</p>
      </div>

      {/* 邮箱配置 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-ink">邮箱配置</h3>
          <Button variant="secondary" size="sm" onClick={async () => {
            const name = prompt("配置名称：");
            if (!name) return;
            const email = prompt("邮箱地址：");
            if (!email) return;
            const smtp = prompt("SMTP 服务器：");
            if (!smtp) return;
            try {
              await emailConfigApi.create({ name, sender_email: email, smtp_server: smtp, smtp_port: 587, smtp_use_tls: true, username: email, password: "" });
              loadEmails();
              toast("success", "邮箱配置已添加");
            } catch (e: any) { toast("error", e.message); }
          }}>
            <Plus className="mr-1.5 h-3.5 w-3.5" /> 添加邮箱
          </Button>
        </div>
        {emailConfigs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-6 text-center">
            <Mail className="mx-auto h-6 w-6 text-ink-tertiary" />
            <p className="mt-2 text-sm text-ink-secondary">暂无邮箱配置</p>
          </div>
        ) : (
          emailConfigs.map((cfg) => (
            <div key={cfg.id} className={cn("flex items-center justify-between rounded-xl border p-4", cfg.is_active ? "border-primary/30 bg-primary/5" : "border-border bg-page")}>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-hover">
                  <Mail className="h-5 w-5 text-ink-tertiary" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-ink">{cfg.name}</span>
                    {cfg.is_active && <Badge variant="default">激活</Badge>}
                  </div>
                  <p className="text-xs text-ink-tertiary">{cfg.sender_email}</p>
                </div>
              </div>
              <div className="flex items-center gap-1">
                {!cfg.is_active && <Button variant="ghost" size="sm" onClick={async () => { await emailConfigApi.activate(cfg.id); loadEmails(); toast("success", "已激活"); }}><Power className="h-3.5 w-3.5" /></Button>}
                <Button variant="ghost" size="sm" onClick={async () => { if (confirm("删除此配置？")) { await emailConfigApi.delete(cfg.id); loadEmails(); } }}><Trash2 className="h-3.5 w-3.5 text-error" /></Button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* 每日报告 */}
      {dailyReport && (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-ink">每日报告</h3>
          <div className="rounded-xl border border-border bg-page p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                  <Activity className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <p className="font-medium text-ink">每日报告</p>
                  <p className="text-xs text-ink-secondary">{dailyReport.enabled ? "已启用" : "已禁用"}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={async () => { await dailyReportApi.updateConfig({ enabled: !dailyReport.enabled }); loadDaily(); }}
                className={cn("relative h-6 w-11 rounded-full transition-colors", dailyReport.enabled ? "bg-primary" : "bg-ink-tertiary")}
              >
                <span className={cn("absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform", dailyReport.enabled ? "translate-x-6" : "translate-x-0.5")} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ======== Pipeline 设置 ======== */
function PipelineSettings() {
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "succeeded" | "failed">("all");

  const loadRuns = useCallback(async () => {
    try { setRuns((await pipelineApi.runs(50)).items || []); } catch { /* quiet */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  const filtered = filter === "all" ? runs : runs.filter((r) => r.status === filter);
  const counts = { all: runs.length, succeeded: runs.filter((r) => r.status === "succeeded").length, failed: runs.filter((r) => r.status === "failed").length };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">Pipeline 运行记录</h2>
        <p className="mt-1 text-sm text-ink-secondary">查看和管理 Pipeline 执行历史</p>
      </div>

      <div className="flex items-center gap-2">
        {(["all", "succeeded", "failed"] as const).map((f) => (
          <button type="button" key={f} onClick={() => setFilter(f)} className={cn("rounded-lg px-3 py-1.5 text-xs font-medium transition-colors", filter === f ? "bg-primary text-white" : "bg-hover text-ink-secondary hover:text-ink")}>
            {f === "all" ? `全部 (${counts.all})` : f === "succeeded" ? `成功 (${counts.succeeded})` : `失败 (${counts.failed})`}
          </button>
        ))}
        <Button variant="ghost" size="sm" onClick={loadRuns} className="ml-auto"><RefreshCw className="h-3.5 w-3.5" /></Button>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-8 text-center">
          <GitBranch className="mx-auto h-8 w-8 text-ink-tertiary" />
          <p className="mt-2 text-sm text-ink-secondary">暂无运行记录</p>
        </div>
      ) : (
        <div className="space-y-1">
          {filtered.map((run) => (
            <div key={run.id} className="flex items-center gap-3 rounded-lg px-3 py-2.5 hover:bg-hover">
              <span className={cn("h-2 w-2 shrink-0 rounded-full", run.status === "succeeded" ? "bg-success" : run.status === "failed" ? "bg-error" : "bg-info")} />
              <span className="font-medium text-ink">{run.pipeline_name}</span>
              <span className="ml-auto text-xs text-ink-tertiary">{run.elapsed_ms != null ? formatDuration(run.elapsed_ms) : ""}</span>
              <span className="text-xs text-ink-tertiary">{timeAgo(run.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ======== 运维设置 ======== */
function OpsSettings() {
  const [results, setResults] = useState<Record<string, any>>({});

  const ops = [
    { key: "batchProcess", label: "一键嵌入 & 粗读", desc: "对所有未读论文执行向量嵌入 + AI 粗读", icon: BookOpen, action: async () => { const r = await jobApi.batchProcessUnread(50); return r.message; } },
    { key: "syncIncremental", label: "增量引用同步", desc: "同步论文之间的引用关系", icon: Link2, action: async () => { const r = await citationApi.syncIncremental(); return `处理 ${r.processed_papers ?? 0} 篇，新增 ${r.edges_inserted} 条边`; } },
    { key: "health", label: "系统健康检查", desc: "查看数据库和统计信息", icon: Activity, action: async () => { const r = await systemApi.status(); return `${r.health.status === "ok" ? "正常" : "异常"} | ${r.counts.topics} 主题 | ${r.counts.papers_latest_200} 论文`; } },
  ];

  const runOp = async (key: string, fn: () => Promise<string>) => {
    try {
      const msg = await fn();
      setResults((p) => ({ ...p, [key]: { success: true, msg } }));
    } catch (e: any) {
      setResults((p) => ({ ...p, [key]: { success: false, msg: e.message || "失败" } }));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">运维操作</h2>
        <p className="mt-1 text-sm text-ink-secondary">执行系统维护和管理任务</p>
      </div>

      <div className="space-y-3">
        {ops.map((op) => {
          const Icon = op.icon;
          const result = results[op.key];
          return (
            <div key={op.key} className="rounded-xl border border-border bg-page p-5">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-hover">
                    <Icon className="h-5 w-5 text-ink-tertiary" />
                  </div>
                  <div>
                    <p className="font-medium text-ink">{op.label}</p>
                    <p className="text-xs text-ink-secondary">{op.desc}</p>
                  </div>
                </div>
                <Button variant="secondary" size="sm" onClick={() => runOp(op.key, op.action)}>
                  <Play className="mr-1.5 h-3.5 w-3.5" />
                  执行
                </Button>
              </div>
              {result && (
                <div className={cn("mt-3 rounded-lg px-3 py-2 text-xs", result.success ? "bg-success/10 text-success" : "bg-error/10 text-error")}>
                  {result.msg}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
