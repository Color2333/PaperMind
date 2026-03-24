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
  PowerOff,
  Eye,
  EyeOff,
  Server,
  RefreshCw,
  Play,
  Link2,
  BookOpen,
  Activity,
  Zap,
  Network,
  Calendar,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  Send,
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
import { getErrorMessage } from "@/lib/errorHandler";
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
  openai: {
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    models: { model_skim: "gpt-4o-mini", model_deep: "gpt-4.1", model_vision: "gpt-4o", model_embedding: "text-embedding-3-small", model_fallback: "gpt-4o-mini" },
  },
  anthropic: {
    label: "Anthropic",
    base_url: "",
    models: { model_skim: "claude-3-haiku-20240307", model_deep: "claude-3-5-sonnet-20241022", model_embedding: "text-embedding-3-small", model_fallback: "claude-3-haiku-20240307" },
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
function ProviderBadge({ provider }: { provider: string }) {
  const colors: Record<string, string> = {
    zhipu: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
    openai: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
    anthropic: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
  };
  const labels: Record<string, string> = {
    zhipu: "智谱",
    openai: "OpenAI",
    anthropic: "Anthropic",
  };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium", colors[provider] || "bg-hover text-ink-tertiary")}>
      <Server className="h-2.5 w-2.5" />
      {labels[provider] || provider}
    </span>
  );
}

function LLMSettings() {
  const { toast } = useToast();
  const [configs, setConfigs] = useState<any[]>([]);
  const [activeInfo, setActiveInfo] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editCfg, setEditCfg] = useState<any>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionId, setActionId] = useState<string | null>(null);

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

  const handleDeactivate = async () => {
    setSubmitting(true);
    try {
      await llmConfigApi.deactivate();
      await load();
      toast("success", "已切回默认配置");
    } catch (err) {
      toast("error", getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleActivate = async (id: string) => {
    setActionId(id);
    try {
      await llmConfigApi.activate(id);
      await load();
      toast("success", "配置已激活");
    } catch (err) {
      toast("error", getErrorMessage(err));
    } finally {
      setActionId(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除此配置？")) return;
    setActionId(id);
    try {
      await llmConfigApi.delete(id);
      await load();
      toast("success", "配置已删除");
    } catch (err) {
      toast("error", getErrorMessage(err));
    } finally {
      setActionId(null);
    }
  };

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
                  <ProviderBadge provider={activeInfo.config?.provider || ""} />
                  <Badge variant={activeInfo.source === "database" ? "info" : "default"}>
                    {activeInfo.source === "database" ? "用户配置" : ".env"}
                  </Badge>
                </div>
                <div className="mt-1 flex gap-3 text-xs text-ink-secondary">
                  <span>粗读: {activeInfo.config?.model_skim}</span>
                  <span>精读: {activeInfo.config?.model_deep}</span>
                  {activeInfo.config?.model_vision && <span>视觉: {activeInfo.config?.model_vision}</span>}
                  <span>嵌入: {activeInfo.config?.model_embedding}</span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={() => setEditCfg(activeInfo.config)}>
                <Pencil className="mr-1.5 h-3.5 w-3.5" />
                编辑
              </Button>
              {activeInfo.source === "database" && (
                <Button variant="ghost" size="sm" onClick={handleDeactivate} disabled={submitting}>
                  <PowerOff className="mr-1.5 h-3.5 w-3.5" />
                  切回默认
                </Button>
              )}
            </div>
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
                      <ProviderBadge provider={cfg.provider} />
                    </div>
                    <div className="mt-1 flex gap-2 text-xs text-ink-tertiary">
                      <span>{cfg.api_key_masked}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {!cfg.is_active && (
                    <Button variant="ghost" size="sm" onClick={() => handleActivate(cfg.id)} disabled={actionId !== null}>
                    <Power className="mr-1.5 h-3.5 w-3.5" />
                    激活
                  </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => setEditCfg(cfg)} disabled={actionId !== null}><Pencil className="h-3.5 w-3.5" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => handleDelete(cfg.id)} disabled={cfg.is_active || actionId !== null}>
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
  const { toast } = useToast();
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
        toast("success", "配置已保存");
      } else {
        await llmConfigApi.create(form);
        toast("success", "配置已创建");
      }
      onSaved();
    } catch (err: any) {
      setError(getErrorMessage(err));
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
  const [localConfig, setLocalConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [showAddEmail, setShowAddEmail] = useState(false);
  const [editEmailConfig, setEditEmailConfig] = useState<any>(null);
  const [testEmailId, setTestEmailId] = useState<string | null>(null);

  const loadEmails = useCallback(async () => {
    try { setEmailConfigs(await emailConfigApi.list() || []); } catch { toast("error", "加载邮箱配置失败"); }
  }, [toast]);

  const loadDaily = useCallback(async () => {
    try {
      const data = await dailyReportApi.getConfig();
      setDailyReport(data);
      setLocalConfig(data);
    } catch { toast("error", "加载报告配置失败"); }
  }, [toast]);

  useEffect(() => { Promise.all([loadEmails(), loadDaily()]).finally(() => setLoading(false)); }, [loadEmails, loadDaily]);

  const handleActivateEmail = async (id: string) => {
    setSubmitting(true);
    try {
      await emailConfigApi.activate(id);
      await loadEmails();
      toast("success", "邮箱已激活");
    } catch (err) {
      toast("error", getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteEmail = async (id: string) => {
    if (!confirm("确定要删除此邮箱配置？")) return;
    try {
      await emailConfigApi.delete(id);
      await loadEmails();
      toast("success", "邮箱配置已删除");
    } catch (err) {
      toast("error", getErrorMessage(err));
    }
  };

  const handleTestEmail = async (id: string) => {
    setTestEmailId(id);
    try {
      await emailConfigApi.test(id);
      toast("success", "测试邮件已发送，请检查邮箱");
    } catch (err) {
      toast("error", getErrorMessage(err));
    } finally {
      setTestEmailId(null);
    }
  };

  const handleUpdateDailyReport = async (updates: any) => {
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = { ...updates };
      if (updates.recipient_emails !== undefined) {
        body.recipient_emails = Array.isArray(updates.recipient_emails) ? updates.recipient_emails.join(",") : updates.recipient_emails;
      }
      const data = await dailyReportApi.updateConfig(body);
      if (data.config) {
        setDailyReport(data.config);
        setLocalConfig(data.config);
        toast("success", "每日报告配置已更新");
      }
    } catch (err) {
      toast("error", getErrorMessage(err));
      await loadDaily();
    } finally {
      setSubmitting(false);
    }
  };

  const handleInputChange = (field: string, value: any) => {
    setLocalConfig((prev: any) => ({ ...prev, [field]: value }));
  };

  const handleInputBlur = (field: string) => {
    if (localConfig && localConfig[field] !== dailyReport[field]) {
      handleUpdateDailyReport({ [field]: localConfig[field] });
    }
  };

  const handleRunDailyWorkflow = async () => {
    if (!confirm("确定要立即执行每日工作流吗？这将使用AI推荐系统找出高价值论文进行精读，生成每日简报并发送邮件报告。\n\n注意：精读论文需要几分钟时间，任务将在后台执行，请稍后查看结果。")) return;
    setSubmitting(true);
    try {
      await dailyReportApi.runOnce();
      toast("success", "每日报告工作流已启动，正在后台执行");
    } catch (err) {
      toast("error", getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

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
          <Button variant="secondary" size="sm" onClick={() => setShowAddEmail(true)}>
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
                {!cfg.is_active && <Button variant="ghost" size="sm" onClick={() => handleActivateEmail(cfg.id)} disabled={submitting}><Power className="h-3.5 w-3.5" /></Button>}
                <Button variant="ghost" size="sm" onClick={() => handleTestEmail(cfg.id)} disabled={testEmailId === cfg.id}>
                  {testEmailId === cfg.id ? <Spinner className="h-3.5 w-3.5" /> : <Send className="h-3.5 w-3.5" />}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setEditEmailConfig(cfg)}><Pencil className="h-3.5 w-3.5" /></Button>
                <Button variant="ghost" size="sm" onClick={() => handleDeleteEmail(cfg.id)} disabled={cfg.is_active}><Trash2 className="h-3.5 w-3.5 text-error" /></Button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* 每日报告 */}
      {dailyReport && (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-ink">每日报告</h3>
          <div className="rounded-xl border border-border bg-page p-5 space-y-4">
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
                onClick={() => handleUpdateDailyReport({ enabled: !dailyReport.enabled })}
                disabled={submitting}
                className={cn("relative h-6 w-11 rounded-full transition-colors", dailyReport.enabled ? "bg-primary" : "bg-ink-tertiary")}
              >
                <span className={cn("absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform", dailyReport.enabled ? "translate-x-6" : "translate-x-0.5")} />
              </button>
            </div>

            {dailyReport.enabled && (
              <>
                <div className="space-y-2">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-medium text-ink">发送邮件报告</p>
                    <button
                      type="button"
                      onClick={() => handleUpdateDailyReport({ send_email_report: !dailyReport.send_email_report })}
                      disabled={submitting}
                      className={cn("relative h-4 w-8 rounded-full transition-colors", dailyReport.send_email_report ? "bg-primary" : "bg-ink-tertiary")}
                    >
                      <span className={cn("absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform", dailyReport.send_email_report ? "translate-x-[1.125rem]" : "translate-x-0.5")} />
                    </button>
                  </div>
                  {dailyReport.send_email_report && (
                    <div className="space-y-2">
                      <input
                        type="text"
                        placeholder="收件人邮箱（逗号分隔）"
                        value={localConfig?.recipient_emails ?? dailyReport.recipient_emails}
                        onChange={(e) => handleInputChange("recipient_emails", e.target.value)}
                        onBlur={() => handleInputBlur("recipient_emails")}
                        disabled={submitting}
                        className="w-full rounded border border-border bg-surface px-2 py-1.5 text-xs text-ink placeholder:text-ink-placeholder"
                      />
                      <div className="space-y-1">
                        <label htmlFor="cron-expression" className="text-[10px] font-medium text-ink-secondary">定时任务 Cron 表达式</label>
                        <input
                          id="cron-expression"
                          type="text"
                          placeholder="0 4 * * *"
                          value={localConfig?.cron_expression ?? dailyReport.cron_expression ?? "0 4 * * *"}
                          onChange={(e) => handleInputChange("cron_expression", e.target.value)}
                          onBlur={() => handleInputBlur("cron_expression")}
                          disabled={submitting}
                          className="w-full rounded border border-border bg-surface px-2 py-1.5 text-xs font-mono text-ink placeholder:text-ink-placeholder"
                        />
                        <p className="text-[9px] text-ink-tertiary">
                          默认：<code className="font-mono">0 4 * * *</code>（UTC 4 点 = 北京时间 12 点）
                          <br />
                          格式：<code className="font-mono">分 时 日 月 周</code>
                        </p>
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between rounded-lg border border-border bg-surface px-3 py-2">
                  <div>
                    <p className="text-xs font-medium text-ink">自动精读新论文</p>
                    <p className="text-[10px] text-ink-tertiary">每日自动精选高价值论文进行深度阅读</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleUpdateDailyReport({ auto_deep_read: !dailyReport.auto_deep_read })}
                    disabled={submitting}
                    className={cn("relative h-5 w-9 rounded-full transition-colors", dailyReport.auto_deep_read ? "bg-primary" : "bg-ink-tertiary")}
                  >
                    <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform", dailyReport.auto_deep_read ? "translate-x-5" : "translate-x-0.5")} />
                  </button>
                </div>
                {dailyReport.auto_deep_read && (
                  <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                    <span className="text-xs text-ink-secondary">每日精读上限</span>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={localConfig?.deep_read_limit ?? dailyReport.deep_read_limit ?? 10}
                      onChange={(e) => handleInputChange("deep_read_limit", parseInt(e.target.value) || 10)}
                      onBlur={() => handleInputBlur("deep_read_limit")}
                      disabled={submitting}
                      className="w-20 rounded border border-border bg-page px-2 py-1 text-xs text-ink outline-none focus:border-primary"
                    />
                    <span className="text-xs text-ink-tertiary">篇</span>
                  </div>
                )}

                <div className="rounded-lg border border-border bg-surface px-3 py-2">
                  <p className="mb-2 text-xs font-medium text-ink">报告内容</p>
                  <div className="space-y-1">
                    <label className="flex items-center gap-2 text-xs text-ink-secondary cursor-pointer">
                      <input
                        type="checkbox"
                        checked={dailyReport.include_paper_details}
                        onChange={(e) => handleUpdateDailyReport({ include_paper_details: e.target.checked })}
                        disabled={submitting}
                        className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-1 focus:ring-primary"
                      />
                      <span>包含论文详情</span>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-ink-secondary cursor-pointer">
                      <input
                        type="checkbox"
                        checked={dailyReport.include_graph_insights}
                        onChange={(e) => handleUpdateDailyReport({ include_graph_insights: e.target.checked })}
                        disabled={submitting}
                        className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-1 focus:ring-primary"
                      />
                      <span>包含图谱洞察</span>
                    </label>
                  </div>
                </div>

                <Button variant="secondary" size="sm" onClick={handleRunDailyWorkflow} disabled={submitting} className="w-full">
                  {submitting ? <><Spinner className="mr-1.5 h-3.5 w-3.5" />执行中...</> : <><Play className="mr-1.5 h-3.5 w-3.5" />立即执行</>}
                </Button>
              </>
            )}
          </div>
        </div>
      )}

      {/* 添加邮箱弹窗 */}
      {showAddEmail && (
        <AddEmailConfigModal
          onCreated={() => { setShowAddEmail(false); loadEmails(); }}
          onCancel={() => setShowAddEmail(false)}
        />
      )}

      {/* 编辑邮箱弹窗 */}
      {editEmailConfig && (
        <EditEmailConfigModal
          config={editEmailConfig}
          onSaved={() => { setEditEmailConfig(null); loadEmails(); }}
          onCancel={() => setEditEmailConfig(null)}
        />
      )}
    </div>
  );
}

function AddEmailConfigModal({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const { toast } = useToast();
  const [form, setForm] = useState({
    name: "",
    smtp_server: "",
    smtp_port: 587,
    smtp_use_tls: true,
    sender_email: "",
    sender_name: "PaperMind",
    username: "",
    password: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const setField = (key: string, value: any) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSelectPreset = async (provider: string) => {
    try {
      const data = await emailConfigApi.smtpPresets();
      const preset = data[provider];
      if (!preset) {
        toast("error", `未找到 ${provider} 邮箱的预设配置`);
        return;
      }
      setForm((prev) => ({
        ...prev,
        smtp_server: preset.smtp_server || prev.smtp_server,
        smtp_port: preset.smtp_port || 587,
        smtp_use_tls: preset.smtp_use_tls !== false,
      }));
    } catch (err) {
      toast("error", getErrorMessage(err));
    }
  };

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.smtp_server || !form.sender_email || !form.username || !form.password) {
      setError("请填写所有必填字段");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await emailConfigApi.create(form);
      toast("success", "邮箱配置已添加");
      onCreated();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-md rounded-2xl border border-border bg-surface p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-ink">添加邮箱配置</h3>
        {error && <div className="mt-3 rounded-lg bg-error-light px-3 py-2 text-xs text-error">{error}</div>}
        <div className="mt-4 space-y-3">
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => handleSelectPreset("qq")} className="flex-1">QQ 邮箱</Button>
            <Button variant="ghost" size="sm" onClick={() => handleSelectPreset("gmail")} className="flex-1">Gmail</Button>
            <Button variant="ghost" size="sm" onClick={() => handleSelectPreset("163")} className="flex-1">163 邮箱</Button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="email-name" className="mb-1 block text-[11px] font-medium text-ink-secondary">配置名称</label>
              <input id="email-name" value={form.name} onChange={(e) => setField("name", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" placeholder="如：我的QQ邮箱" />
            </div>
            <div>
              <label htmlFor="email-sender" className="mb-1 block text-[11px] font-medium text-ink-secondary">发件人邮箱</label>
              <input id="email-sender" value={form.sender_email} onChange={(e) => setField("sender_email", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" placeholder="example@qq.com" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="email-smtp" className="mb-1 block text-[11px] font-medium text-ink-secondary">SMTP 服务器</label>
              <input id="email-smtp" value={form.smtp_server} onChange={(e) => setField("smtp_server", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" placeholder="smtp.qq.com" />
            </div>
            <div>
              <label htmlFor="email-port" className="mb-1 block text-[11px] font-medium text-ink-secondary">SMTP 端口</label>
              <input id="email-port" type="number" value={form.smtp_port} onChange={(e) => setField("smtp_port", parseInt(e.target.value) || 587)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" />
            </div>
          </div>
            <div>
              <label htmlFor="email-username" className="mb-1 block text-[11px] font-medium text-ink-secondary">用户名</label>
              <input id="email-username" value={form.username} onChange={(e) => setField("username", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" placeholder="同发件人邮箱" />
          </div>
            <div>
              <label htmlFor="email-password" className="mb-1 block text-[11px] font-medium text-ink-secondary">密码/授权码</label>
              <input id="email-password" type="password" value={form.password} onChange={(e) => setField("password", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" placeholder="邮箱授权码" />
          </div>
          <label className="flex items-center gap-2 text-xs text-ink-secondary cursor-pointer">
            <input type="checkbox" checked={form.smtp_use_tls} onChange={(e) => setField("smtp_use_tls", e.target.checked)} className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-1 focus:ring-primary" />
            <span>使用 TLS 加密</span>
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onCancel}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting}>{submitting ? <Spinner className="mr-1.5 h-3.5 w-3.5" /> : null}添加</Button>
        </div>
      </div>
    </div>
  );
}

function EditEmailConfigModal({ config, onSaved, onCancel }: { config: any; onSaved: () => void; onCancel: () => void }) {
  const [form, setForm] = useState({
    name: config.name,
    smtp_server: config.smtp_server,
    smtp_port: config.smtp_port,
    smtp_use_tls: config.smtp_use_tls,
    sender_email: config.sender_email,
    sender_name: config.sender_name || "PaperMind",
    username: config.username,
    password: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const setField = (key: string, value: any) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = async () => {
    setSubmitting(true);
    setError("");
    try {
      const payload = { ...form };
      if (!form.password) delete (payload as any).password;
      await emailConfigApi.update(config.id, payload);
      onSaved();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-md rounded-2xl border border-border bg-surface p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-ink">编辑邮箱配置</h3>
        {error && <div className="mt-3 rounded-lg bg-error-light px-3 py-2 text-xs text-error">{error}</div>}
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="edit-email-name" className="mb-1 block text-[11px] font-medium text-ink-secondary">配置名称</label>
              <input id="edit-email-name" value={form.name} onChange={(e) => setField("name", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" />
            </div>
            <div>
              <label htmlFor="edit-email-sender" className="mb-1 block text-[11px] font-medium text-ink-secondary">发件人邮箱</label>
              <input id="edit-email-sender" value={form.sender_email} onChange={(e) => setField("sender_email", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="edit-email-smtp" className="mb-1 block text-[11px] font-medium text-ink-secondary">SMTP 服务器</label>
              <input id="edit-email-smtp" value={form.smtp_server} onChange={(e) => setField("smtp_server", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" />
            </div>
            <div>
              <label htmlFor="edit-email-port" className="mb-1 block text-[11px] font-medium text-ink-secondary">SMTP 端口</label>
              <input id="edit-email-port" type="number" value={form.smtp_port} onChange={(e) => setField("smtp_port", parseInt(e.target.value) || 587)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" />
            </div>
          </div>
          <div>
            <label htmlFor="edit-email-username" className="mb-1 block text-[11px] font-medium text-ink-secondary">用户名</label>
            <input id="edit-email-username" value={form.username} onChange={(e) => setField("username", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" />
          </div>
          <div>
            <label htmlFor="edit-email-password" className="mb-1 block text-[11px] font-medium text-ink-secondary">新密码（留空不改）</label>
            <input id="edit-email-password" type="password" value={form.password} onChange={(e) => setField("password", e.target.value)} className="w-full rounded-lg border border-border bg-page px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary" placeholder="留空保持不变" />
          </div>
          <label className="flex items-center gap-2 text-xs text-ink-secondary cursor-pointer">
            <input type="checkbox" checked={form.smtp_use_tls} onChange={(e) => setField("smtp_use_tls", e.target.checked)} className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-1 focus:ring-primary" />
            <span>使用 TLS 加密</span>
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onCancel}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting}>{submitting ? <Spinner className="mr-1.5 h-3.5 w-3.5" /> : null}保存</Button>
        </div>
      </div>
    </div>
  );
}

/* ======== Pipeline 设置 ======== */
function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    succeeded: "bg-success",
    failed: "bg-error",
    running: "bg-info animate-pulse",
    pending: "bg-warning",
  };
  return <span className={cn("inline-block h-2 w-2 shrink-0 rounded-full", colors[status] || "bg-ink-tertiary")} />;
}

function PipelineSettings() {
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "succeeded" | "failed" | "running">("all");

  const loadRuns = useCallback(async () => {
    try { setRuns((await pipelineApi.runs(50)).items || []); } catch { /* quiet */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  const filtered = filter === "all" ? runs : runs.filter((r) => r.status === filter);
  const counts = { all: runs.length, succeeded: runs.filter((r) => r.status === "succeeded").length, failed: runs.filter((r) => r.status === "failed").length, running: runs.filter((r) => r.status === "running" || r.status === "pending").length };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">Pipeline 运行记录</h2>
        <p className="mt-1 text-sm text-ink-secondary">查看和管理 Pipeline 执行历史</p>
      </div>

      <div className="flex items-center gap-2">
        {(["all", "succeeded", "failed", "running"] as const).map((f) => (
          <button type="button" key={f} onClick={() => setFilter(f)} className={cn("rounded-lg px-3 py-1.5 text-xs font-medium transition-colors", filter === f ? "bg-primary text-white" : "bg-hover text-ink-secondary hover:text-ink")}>
            {f === "all" ? `全部 (${counts.all})` : f === "succeeded" ? `成功 (${counts.succeeded})` : f === "failed" ? `失败 (${counts.failed})` : `进行中 (${counts.running})`}
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
        <div className="max-h-[400px] space-y-1 overflow-y-auto">
          {filtered.map((run) => (
            <div key={run.id} className="flex items-center gap-3 rounded-lg px-3 py-2.5 hover:bg-hover">
              <StatusDot status={run.status} />
              <span className="font-medium text-ink">{run.pipeline_name}</span>
              {run.paper_id && <span className="font-mono text-[10px] text-ink-tertiary">{run.paper_id.slice(0, 8)}</span>}
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
interface OpResult { success: boolean; message: string; }

function OpsSettings() {
  const { toast } = useToast();
  const [results, setResults] = useState<Record<string, OpResult>>({});
  const [loadings, setLoadings] = useState<Record<string, boolean>>({});

  const setL = (k: string, v: boolean) => setLoadings((p) => ({ ...p, [k]: v }));
  const setR = (k: string, r: OpResult) => setResults((p) => ({ ...p, [k]: r }));

  const ops = [
    { key: "batchProcess", label: "一键嵌入 & 粗读未读论文", desc: "对所有未读论文执行向量嵌入 + AI 粗读（并行处理）", icon: BookOpen, action: async () => { setL("batchProcess", true); try { const r = await jobApi.batchProcessUnread(50); setR("batchProcess", { success: r.failed === 0, message: r.message }); } catch (err) { setR("batchProcess", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("batchProcess", false); } } },
    { key: "syncIncremental", label: "增量引用同步", desc: "同步论文之间的引用关系", icon: Link2, action: async () => { setL("syncIncremental", true); try { const r = await citationApi.syncIncremental(); setR("syncIncremental", { success: true, message: `同步完成，处理 ${r.processed_papers ?? 0} 篇，新增 ${r.edges_inserted} 条边` }); } catch (err) { setR("syncIncremental", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("syncIncremental", false); } } },
    { key: "dailyJob", label: "执行每日任务", desc: "抓取论文 + 生成简报", icon: Calendar, action: async () => { setL("dailyJob", true); try { await jobApi.dailyRun(); setR("dailyJob", { success: true, message: "每日任务执行完成" }); } catch (err) { setR("dailyJob", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("dailyJob", false); } } },
    { key: "weeklyJob", label: "每周图维护", desc: "引用同步 + 图谱维护", icon: Network, action: async () => { setL("weeklyJob", true); try { await jobApi.weeklyGraphRun(); setR("weeklyJob", { success: true, message: "每周维护执行完成" }); } catch (err) { setR("weeklyJob", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("weeklyJob", false); } } },
    { key: "health", label: "系统健康检查", desc: "数据库 + 统计信息", icon: Zap, action: async () => { setL("health", true); try { const r = await systemApi.status(); setR("health", { success: r.health.status === "ok", message: `${r.health.status === "ok" ? "正常" : "异常"} | ${r.counts.topics} 主题 | ${r.counts.papers_latest_200} 论文` }); } catch (err) { setR("health", { success: false, message: err instanceof Error ? err.message : "失败" }); } finally { setL("health", false); } } },
  ];

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
          const loading = loadings[op.key];
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
                <Button variant="secondary" size="sm" onClick={() => op.action()} disabled={loading}>
                  {loading ? <><Spinner className="mr-1.5 h-3.5 w-3.5" />执行中</> : <><Play className="mr-1.5 h-3.5 w-3.5" />执行</>}
                </Button>
              </div>
              {result && (
                <div className={cn("mt-3 rounded-lg px-3 py-2 text-xs", result.success ? "bg-success/10 text-success" : "bg-error/10 text-error")}>
                  {result.message}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
