/**
 * 设置弹窗 - LLM 配置 / 邮箱与报告 / Pipeline 运行 / 运维操作
 * @author Bamzc
 */
import { useState, useEffect, useCallback, type ReactNode } from "react";
import { useToast } from "@/contexts/ToastContext";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { Empty } from "@/components/ui/Empty";
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
import type {
  LLMProviderConfig,
  LLMProviderCreate,
  LLMProviderUpdate,
  ActiveLLMConfig,
  PipelineRun,
} from "@/types";
import { cn } from "@/lib/utils";
import { formatDuration, timeAgo } from "@/lib/utils";
import {
  Cpu,
  GitBranch,
  Settings,
  Plus,
  Trash2,
  Eye,
  EyeOff,
  Power,
  PowerOff,
  Server,
  Pencil,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  Activity,
  Play,
  Network,
  Zap,
  Settings2,
  Link2,
  Calendar,
  AlertTriangle,
  BookOpen,
  Mail,
  Send,
} from "lucide-react";

type Tab = "llm" | "pipeline" | "ops" | "email";

const TABS: { key: Tab; label: string; icon: typeof Cpu }[] = [
  { key: "llm", label: "LLM 配置", icon: Cpu },
  { key: "email", label: "邮箱与报告", icon: Mail },
  { key: "pipeline", label: "Pipeline", icon: GitBranch },
  { key: "ops", label: "运维", icon: Settings },
];

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("llm");

  return (
    <Modal title="系统设置" onClose={onClose} maxWidth="xl">
      <div className="flex flex-col" style={{ height: "600px", maxHeight: "85vh" }}>
        {/* 标签栏 */}
        <div className="mb-4 flex gap-1 rounded-xl bg-page p-1 flex-shrink-0">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                "flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2 text-xs font-medium transition-all",
                tab === t.key
                  ? "bg-surface text-primary shadow-sm"
                  : "text-ink-secondary hover:text-ink",
              )}
            >
              <t.icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          ))}
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto pr-1">
          {tab === "llm" && <LLMTab />}
          {tab === "email" && <EmailTab />}
          {tab === "pipeline" && <PipelineTab />}
          {tab === "ops" && <OpsTab />}
        </div>
      </div>
    </Modal>
  );
}

/* ======== LLM 配置 Tab ======== */

const PROVIDER_PRESETS: Record<
  string,
  { label: string; base_url: string; models: Partial<LLMProviderCreate> }
> = {
  zhipu: {
    label: "智谱 AI",
    base_url: "https://open.bigmodel.cn/api/paas/v4/",
    models: {
      model_skim: "glm-4.7",
      model_deep: "glm-4.7",
      model_vision: "glm-4.6v",
      model_embedding: "embedding-3",
      model_fallback: "glm-4.7",
    },
  },
  openai: {
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    models: {
      model_skim: "gpt-4o-mini",
      model_deep: "gpt-4.1",
      model_vision: "gpt-4o",
      model_embedding: "text-embedding-3-small",
      model_fallback: "gpt-4o-mini",
    },
  },
  anthropic: {
    label: "Anthropic",
    base_url: "",
    models: {
      model_skim: "claude-3-haiku-20240307",
      model_deep: "claude-3-5-sonnet-20241022",
      model_embedding: "text-embedding-3-small",
      model_fallback: "claude-3-haiku-20240307",
    },
  },
};

function LLMTab() {
  const { toast } = useToast();
  const [configs, setConfigs] = useState<LLMProviderConfig[]>([]);
  const [activeInfo, setActiveInfo] = useState<ActiveLLMConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editCfg, setEditCfg] = useState<LLMProviderConfig | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [listRes, activeRes] = await Promise.all([
        llmConfigApi.list(),
        llmConfigApi.active(),
      ]);
      setConfigs(listRes.items);
      setActiveInfo(activeRes);
    } catch (err) {
      toast("error", "加载 LLM 配置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleActivate = async (id: string) => {
    setSubmitting(true);
    try {
      await llmConfigApi.activate(id);
      await load();
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除此配置？")) return;
    await llmConfigApi.delete(id);
    await load();
  };

  if (loading)
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );

  return (
    <div className="space-y-4">
      {/* 当前生效 */}
      {activeInfo && (
        <div className="flex items-center justify-between rounded-xl bg-page px-4 py-3">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2 text-xs">
              <Zap className="h-3.5 w-3.5 text-primary" />
              <span className="font-medium text-ink">当前生效</span>
              <ProviderBadge provider={activeInfo.config.provider || ""} />
              <Badge
                variant={
                  activeInfo.source === "database" ? "success" : "info"
                }
              >
                {activeInfo.source === "database" ? "用户配置" : ".env"}
              </Badge>
            </div>
            <div className="flex gap-3 text-[11px] text-ink-tertiary">
              <span>粗读: {activeInfo.config.model_skim}</span>
              <span>精读: {activeInfo.config.model_deep}</span>
              {activeInfo.config.model_vision && (
                <span>视觉: {activeInfo.config.model_vision}</span>
              )}
              <span>嵌入: {activeInfo.config.model_embedding}</span>
            </div>
          </div>
          {activeInfo.source === "database" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={async () => {
                await llmConfigApi.deactivate();
                load();
              }}
              disabled={submitting}
            >
              <PowerOff className="mr-1 h-3 w-3" />
              切回默认
            </Button>
          )}
        </div>
      )}

      {/* 配置列表 */}
      {configs.length === 0 ? (
        <div className="py-6 text-center text-sm text-ink-tertiary">
          暂无自定义配置
        </div>
      ) : (
        <div className="space-y-2">
          {configs.map((cfg) => (
            <div
              key={cfg.id}
              className={cn(
                "flex items-center justify-between rounded-xl border px-4 py-3",
                cfg.is_active
                  ? "border-primary/30 bg-primary-50"
                  : "border-border bg-surface",
              )}
            >
              <div className="min-w-0 space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-ink">
                    {cfg.name}
                  </span>
                  <ProviderBadge provider={cfg.provider} />
                  {cfg.is_active && <Badge variant="default">激活</Badge>}
                </div>
                <div className="text-[11px] font-mono text-ink-tertiary">
                  {cfg.api_key_masked}
                </div>
              </div>
              <div className="flex gap-1">
                <button
                  onClick={() => setEditCfg(cfg)}
                  className="rounded-lg p-1.5 text-ink-tertiary hover:bg-hover hover:text-ink"
                  title="编辑"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                {!cfg.is_active && (
                  <button
                    onClick={() => handleActivate(cfg.id)}
                    disabled={submitting}
                    className="rounded-lg p-1.5 text-ink-tertiary hover:bg-hover hover:text-primary"
                    title="激活"
                  >
                    <Power className="h-3.5 w-3.5" />
                  </button>
                )}
                <button
                  onClick={() => handleDelete(cfg.id)}
                  className="rounded-lg p-1.5 text-ink-tertiary hover:bg-error-light hover:text-error"
                  title="删除"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Button
        variant="secondary"
        size="sm"
        onClick={() => setShowAdd(true)}
        className="w-full"
      >
        <Plus className="mr-1.5 h-3.5 w-3.5" />
        添加 LLM 配置
      </Button>

      {showAdd && (
        <AddConfigInline
          onCreated={() => {
            setShowAdd(false);
            load();
          }}
          onCancel={() => setShowAdd(false)}
        />
      )}
      {editCfg && (
        <EditConfigInline
          config={editCfg}
          onSaved={() => {
            setEditCfg(null);
            load();
          }}
          onCancel={() => setEditCfg(null)}
        />
      )}
    </div>
  );
}

function ProviderBadge({ provider }: { provider: string }) {
  const colors: Record<string, string> = {
    zhipu: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
    openai:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
    anthropic:
      "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
  };
  const labels: Record<string, string> = {
    zhipu: "智谱",
    openai: "OpenAI",
    anthropic: "Anthropic",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${colors[provider] || "bg-hover text-ink-tertiary"}`}
    >
      <Server className="h-2.5 w-2.5" />
      {labels[provider] || provider}
    </span>
  );
}

function AddConfigInline({
  onCreated,
  onCancel,
}: {
  onCreated: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<LLMProviderCreate>({
    name: "",
    provider: "zhipu",
    api_key: "",
    api_base_url: PROVIDER_PRESETS.zhipu.base_url,
    model_skim: PROVIDER_PRESETS.zhipu.models.model_skim || "",
    model_deep: PROVIDER_PRESETS.zhipu.models.model_deep || "",
    model_vision: PROVIDER_PRESETS.zhipu.models.model_vision || "",
    model_embedding: PROVIDER_PRESETS.zhipu.models.model_embedding || "",
    model_fallback: PROVIDER_PRESETS.zhipu.models.model_fallback || "",
  });
  const [showKey, setShowKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const setField = (key: keyof LLMProviderCreate, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleProviderChange = (provider: string) => {
    const preset = PROVIDER_PRESETS[provider];
    if (preset) {
      setForm((prev) => ({
        ...prev,
        provider: provider as LLMProviderCreate["provider"],
        api_base_url: preset.base_url,
        model_skim: preset.models.model_skim || prev.model_skim,
        model_deep: preset.models.model_deep || prev.model_deep,
        model_vision: preset.models.model_vision || "",
        model_embedding: preset.models.model_embedding || prev.model_embedding,
        model_fallback: preset.models.model_fallback || prev.model_fallback,
      }));
    }
  };

  const handleSubmit = async () => {
    if (!form.name.trim()) {
      setError("请输入配置名称");
      return;
    }
    if (!form.api_key.trim()) {
      setError("请输入 API Key");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await llmConfigApi.create(form);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-3 rounded-xl border border-primary/30 bg-primary-50 p-4">
      {error && (
        <div className="rounded-lg bg-error-light px-3 py-2 text-xs text-error">
          {error}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <MiniInput
          label="配置名称"
          value={form.name}
          onChange={(v) => setField("name", v)}
          placeholder="如：我的智谱配置"
        />
        <div>
          <label className="mb-1 block text-[11px] font-medium text-ink-secondary">
            提供者
          </label>
          <select
            className="w-full rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs text-ink outline-none focus:border-primary"
            value={form.provider}
            onChange={(e) => handleProviderChange(e.target.value)}
          >
            {Object.entries(PROVIDER_PRESETS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="relative">
        <MiniInput
          label="API Key"
          value={form.api_key}
          onChange={(v) => setField("api_key", v)}
          placeholder="sk-..."
          type={showKey ? "text" : "password"}
        />
        <button
          type="button"
          className="absolute right-2 top-6 text-ink-tertiary hover:text-ink"
          onClick={() => setShowKey(!showKey)}
        >
          {showKey ? (
            <EyeOff className="h-3.5 w-3.5" />
          ) : (
            <Eye className="h-3.5 w-3.5" />
          )}
        </button>
      </div>
      <MiniInput
        label="Base URL"
        value={form.api_base_url || ""}
        onChange={(v) => setField("api_base_url", v)}
        placeholder="留空则自动"
      />
      <div className="grid grid-cols-3 gap-2">
        <MiniInput
          label="粗读"
          value={form.model_skim}
          onChange={(v) => setField("model_skim", v)}
        />
        <MiniInput
          label="精读"
          value={form.model_deep}
          onChange={(v) => setField("model_deep", v)}
        />
        <MiniInput
          label="视觉"
          value={form.model_vision || ""}
          onChange={(v) => setField("model_vision", v)}
        />
        <MiniInput
          label="嵌入"
          value={form.model_embedding}
          onChange={(v) => setField("model_embedding", v)}
        />
        <MiniInput
          label="降级"
          value={form.model_fallback}
          onChange={(v) => setField("model_fallback", v)}
        />
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          取消
        </Button>
        <Button size="sm" onClick={handleSubmit} disabled={submitting}>
          {submitting ? <Spinner className="mr-1 h-3 w-3" /> : null}
          创建
        </Button>
      </div>
    </div>
  );
}

function EditConfigInline({
  config,
  onSaved,
  onCancel,
}: {
  config: LLMProviderConfig;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<LLMProviderUpdate>({
    name: config.name,
    provider: config.provider,
    api_base_url: config.api_base_url || "",
    model_skim: config.model_skim,
    model_deep: config.model_deep,
    model_vision: config.model_vision || "",
    model_embedding: config.model_embedding,
    model_fallback: config.model_fallback,
  });
  const [newApiKey, setNewApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const setField = (key: keyof LLMProviderUpdate, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleSave = async () => {
    setSubmitting(true);
    setError("");
    try {
      const payload: LLMProviderUpdate = { ...form };
      if (newApiKey.trim()) payload.api_key = newApiKey;
      await llmConfigApi.update(config.id, payload);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-3 rounded-xl border border-primary/30 bg-primary-50 p-4">
      <p className="text-xs font-medium text-ink">
        编辑：{config.name}
      </p>
      {error && (
        <div className="rounded-lg bg-error-light px-3 py-2 text-xs text-error">
          {error}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <MiniInput
          label="名称"
          value={form.name || ""}
          onChange={(v) => setField("name", v)}
        />
        <MiniInput
          label="新 API Key（留空不改）"
          value={newApiKey}
          onChange={setNewApiKey}
          placeholder="留空保持不变"
          type="password"
        />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <MiniInput
          label="粗读"
          value={form.model_skim || ""}
          onChange={(v) => setField("model_skim", v)}
        />
        <MiniInput
          label="精读"
          value={form.model_deep || ""}
          onChange={(v) => setField("model_deep", v)}
        />
        <MiniInput
          label="视觉"
          value={form.model_vision || ""}
          onChange={(v) => setField("model_vision", v)}
        />
        <MiniInput
          label="嵌入"
          value={form.model_embedding || ""}
          onChange={(v) => setField("model_embedding", v)}
        />
        <MiniInput
          label="降级"
          value={form.model_fallback || ""}
          onChange={(v) => setField("model_fallback", v)}
        />
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          取消
        </Button>
        <Button size="sm" onClick={handleSave} disabled={submitting}>
          保存
        </Button>
      </div>
    </div>
  );
}

function MiniInput({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium text-ink-secondary">
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-border bg-surface px-2.5 py-1.5 font-mono text-xs text-ink placeholder:text-ink-placeholder outline-none focus:border-primary"
      />
    </div>
  );
}

/* ======== Pipeline Tab ======== */

function PipelineTab() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const res = await pipelineApi.runs(50);
      setRuns(res.items);
    } catch {
      /* quiet */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const filtered =
    filter === "all" ? runs : runs.filter((r) => r.status === filter);
  const counts = {
    all: runs.length,
    succeeded: runs.filter((r) => r.status === "succeeded").length,
    failed: runs.filter((r) => r.status === "failed").length,
  };

  if (loading)
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          {(
            [
              { key: "all", label: `全部(${counts.all})` },
              { key: "succeeded", label: `成功(${counts.succeeded})` },
              { key: "failed", label: `失败(${counts.failed})` },
            ] as const
          ).map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "rounded-lg px-2.5 py-1 text-[11px] font-medium transition-all",
                filter === f.key
                  ? "bg-primary-light text-primary"
                  : "text-ink-tertiary hover:bg-hover hover:text-ink-secondary",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button
          onClick={loadRuns}
          className="rounded-lg p-1.5 text-ink-tertiary hover:bg-hover hover:text-ink"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="py-8 text-center text-xs text-ink-tertiary">
          暂无运行记录
        </div>
      ) : (
        <div className="max-h-[340px] space-y-1 overflow-y-auto">
          {filtered.map((run) => (
            <div
              key={run.id}
              className="flex items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-hover"
            >
              <StatusDot status={run.status} />
              <span className="text-xs font-medium text-ink">
                {run.pipeline_name}
              </span>
              {run.paper_id && (
                <span className="font-mono text-[10px] text-ink-tertiary">
                  {run.paper_id.slice(0, 8)}
                </span>
              )}
              <span className="ml-auto text-[10px] text-ink-tertiary">
                {run.elapsed_ms != null ? formatDuration(run.elapsed_ms) : ""}
              </span>
              <span className="text-[10px] text-ink-tertiary">
                {timeAgo(run.created_at)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    succeeded: "bg-success",
    failed: "bg-error",
    running: "bg-info animate-pulse",
    pending: "bg-warning",
  };
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        colors[status] || "bg-ink-tertiary",
      )}
    />
  );
}

/* ======== 邮箱与报告 Tab ======== */

function EmailTab() {
  const { toast } = useToast();
  const [emailConfigs, setEmailConfigs] = useState<any[]>([]);
  const [dailyReportConfig, setDailyReportConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [showAddEmail, setShowAddEmail] = useState(false);
  const [editEmailConfig, setEditEmailConfig] = useState<any>(null);
  const [submitting, setSubmitting] = useState(false);
  const [testEmailId, setTestEmailId] = useState<string | null>(null);

  const loadEmailConfigs = useCallback(async () => {
    try {
      const data = await emailConfigApi.list();
      setEmailConfigs(Array.isArray(data) ? data : []);
    } catch (err) {
      toast("error", getErrorMessage(err));
    }
  }, [toast]);

  const loadDailyReportConfig = useCallback(async () => {
    try {
      const data = await dailyReportApi.getConfig();
      setDailyReportConfig(data);
      setLocalConfig(data);
    } catch (err) {
      toast("error", getErrorMessage(err));
    }
  }, [toast]);

  useEffect(() => {
    Promise.all([loadEmailConfigs(), loadDailyReportConfig()]).finally(() => {
      setLoading(false);
    });
  }, [loadEmailConfigs, loadDailyReportConfig]);

  const handleActivateEmail = async (id: string) => {
    setSubmitting(true);
    try {
      await emailConfigApi.activate(id);
      await loadEmailConfigs();
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
      await loadEmailConfigs();
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
        body.recipient_emails = Array.isArray(updates.recipient_emails)
          ? updates.recipient_emails.join(",")
          : updates.recipient_emails;
      }
      const data = await dailyReportApi.updateConfig(body);
      if (data.config) {
        setDailyReportConfig(data.config);
        setLocalConfig(data.config);
        toast("success", "每日报告配置已更新");
      }
    } catch (err) {
      toast("error", getErrorMessage(err));
      await loadDailyReportConfig();
    } finally {
      setSubmitting(false);
    }
  };

  // 本地临时存储的配置值
  const [localConfig, setLocalConfig] = useState<any>(null);

  // 初始化本地配置
  useEffect(() => {
    if (dailyReportConfig) {
      setLocalConfig(dailyReportConfig);
    }
  }, [dailyReportConfig]);

  // 处理输入变化（只更新本地state，不调用API）
  const handleInputChange = (field: string, value: any) => {
    setLocalConfig((prev: any) => ({ ...prev, [field]: value }));
  };

  // 处理失去焦点（提交更新）
  const handleInputBlur = (field: string) => {
    if (localConfig && localConfig[field] !== dailyReportConfig[field]) {
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

  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 邮箱配置 */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <h3 className="mb-3 text-sm font-semibold text-ink">邮箱配置</h3>
        {emailConfigs.length === 0 ? (
          <div className="py-4 text-center text-xs text-ink-tertiary">
            暂无邮箱配置
          </div>
        ) : (
          <div className="space-y-2">
            {emailConfigs.map((cfg) => (
              <div
                key={cfg.id}
                className={`flex items-center justify-between rounded-lg border px-3 py-2 ${
                  cfg.is_active ? "border-primary/30 bg-primary-light" : "border-border bg-page"
                }`}
              >
                <div className="min-w-0 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-ink">{cfg.name}</span>
                    {cfg.is_active && <Badge variant="default">激活</Badge>}
                  </div>
                  <p className="text-[10px] text-ink-tertiary">{cfg.sender_email}</p>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => handleTestEmail(cfg.id)}
                    disabled={testEmailId === cfg.id || submitting}
                    className="rounded-lg p-1.5 text-ink-tertiary hover:bg-hover hover:text-ink"
                    title="发送测试"
                  >
                    {testEmailId === cfg.id ? <Spinner className="h-3 w-3" /> : <Send className="h-3 w-3" />}
                  </button>
                  {!cfg.is_active && (
                    <button
                      onClick={() => handleActivateEmail(cfg.id)}
                      disabled={submitting}
                      className="rounded-lg p-1.5 text-ink-tertiary hover:bg-hover hover:text-primary"
                      title="激活"
                    >
                      <Power className="h-3 w-3" />
                    </button>
                  )}
                  <button
                    onClick={() => setEditEmailConfig(cfg)}
                    className="rounded-lg p-1.5 text-ink-tertiary hover:bg-hover hover:text-ink"
                    title="编辑"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  <button
                    onClick={() => handleDeleteEmail(cfg.id)}
                    className="rounded-lg p-1.5 text-ink-tertiary hover:bg-error-light hover:text-error"
                    title="删除"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setShowAddEmail(true)}
          className="mt-3 w-full"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          添加邮箱
        </Button>
      </div>

      {/* 每日报告配置 */}
      {dailyReportConfig && (
        <div className="rounded-xl border border-border bg-surface p-4">
          <h3 className="mb-3 text-sm font-semibold text-ink">每日报告配置</h3>
          <div className="space-y-3">
            {/* 总开关 */}
            <div className="flex items-center justify-between rounded-lg border border-border bg-page px-3 py-2">
              <div>
                <p className="text-xs font-medium text-ink">启用每日报告</p>
                <p className="text-[10px] text-ink-tertiary">自动精读论文并发送邮件报告</p>
              </div>
              <button
                onClick={() => handleUpdateDailyReport({ enabled: !dailyReportConfig.enabled })}
                disabled={submitting}
                className={`relative h-5 w-9 rounded-full transition-colors ${
                  dailyReportConfig.enabled ? "bg-primary" : "bg-ink-tertiary"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                    dailyReportConfig.enabled ? "translate-x-[1.125rem]" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>

            {/* 详细配置 - 始终显示 */}
            <>
                {/* 自动精读 */}
                <div className="rounded-lg border border-border bg-page px-3 py-2">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-medium text-ink">自动精读新论文</p>
                    <button
                      onClick={() => handleUpdateDailyReport({ auto_deep_read: !dailyReportConfig.auto_deep_read })}
                      disabled={submitting}
                      className={`relative h-4 w-8 rounded-full transition-colors ${
                        dailyReportConfig.auto_deep_read ? "bg-primary" : "bg-ink-tertiary"
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform ${
                          dailyReportConfig.auto_deep_read ? "translate-x-[1.125rem]" : "translate-x-0.5"
                        }`}
                      />
                    </button>
                  </div>
                  {dailyReportConfig.auto_deep_read && (
                    <div className="flex items-center gap-2">
                      <label className="text-[10px] text-ink-secondary">每日精读数量限制</label>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={localConfig?.deep_read_limit ?? dailyReportConfig.deep_read_limit}
                        onChange={(e) => handleInputChange("deep_read_limit", parseInt(e.target.value) || 10)}
                        onBlur={() => handleInputBlur("deep_read_limit")}
                        disabled={submitting}
                        className="w-16 rounded border border-border bg-surface px-2 py-0.5 text-center text-xs text-ink"
                      />
                    </div>
                  )}
                </div>

                {/* 邮件发送 */}
                <div className="rounded-lg border border-border bg-page px-3 py-2">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-medium text-ink">发送邮件报告</p>
                    <button
                      onClick={() => handleUpdateDailyReport({ send_email_report: !dailyReportConfig.send_email_report })}
                      disabled={submitting}
                      className={`relative h-4 w-8 rounded-full transition-colors ${
                        dailyReportConfig.send_email_report ? "bg-primary" : "bg-ink-tertiary"
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform ${
                          dailyReportConfig.send_email_report ? "translate-x-[1.125rem]" : "translate-x-0.5"
                        }`}
                      />
                    </button>
                  </div>
                  {dailyReportConfig.send_email_report && (
                    <div className="space-y-2">
                      <input
                        type="text"
                        placeholder="收件人邮箱（逗号分隔）"
                        value={localConfig?.recipient_emails ?? dailyReportConfig.recipient_emails}
                        onChange={(e) => handleInputChange("recipient_emails", e.target.value)}
                        onBlur={() => handleInputBlur("recipient_emails")}
                        disabled={submitting}
                        className="w-full rounded border border-border bg-surface px-2 py-1.5 text-xs text-ink placeholder:text-ink-placeholder"
                      />
                      <div className="flex items-center gap-2">
                        <label className="text-[10px] text-ink-secondary">发送时间（UTC）</label>
                        <input
                          type="number"
                          min={0}
                          max={23}
                          value={localConfig?.report_time_utc ?? dailyReportConfig.report_time_utc}
                          onChange={(e) => handleInputChange("report_time_utc", parseInt(e.target.value) || 21)}
                          onBlur={() => handleInputBlur("report_time_utc")}
                          disabled={submitting}
                          className="w-16 rounded border border-border bg-surface px-2 py-0.5 text-center text-xs text-ink"
                        />
                        <span className="text-[10px] text-ink-tertiary">（北京时间 = UTC + 8）</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* 报告内容 */}
                <div className="rounded-lg border border-border bg-page px-3 py-2">
                  <p className="mb-2 text-xs font-medium text-ink">报告内容</p>
                  <div className="space-y-1">
                    <label className="flex items-center gap-2 text-xs text-ink-secondary cursor-pointer">
                      <input
                        type="checkbox"
                        checked={dailyReportConfig.include_paper_details}
                        onChange={(e) => handleUpdateDailyReport({ include_paper_details: e.target.checked })}
                        disabled={submitting}
                        className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-1 focus:ring-primary"
                      />
                      <span>包含论文详情</span>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-ink-secondary cursor-pointer">
                      <input
                        type="checkbox"
                        checked={dailyReportConfig.include_graph_insights}
                        onChange={(e) => handleUpdateDailyReport({ include_graph_insights: e.target.checked })}
                        disabled={submitting}
                        className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-1 focus:ring-primary"
                      />
                      <span>包含图谱洞察</span>
                    </label>
                  </div>
                </div>

                {/* 立即执行 */}
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleRunDailyWorkflow}
                  disabled={submitting}
                  className="w-full"
                >
                  {submitting ? (
                    <>
                      <Spinner className="mr-1.5 h-3.5 w-3.5" />
                      执行中...
                    </>
                  ) : (
                    <>
                      <Play className="mr-1.5 h-3.5 w-3.5" />
                      立即执行
                    </>
                  )}
                </Button>
            </>
          </div>
        </div>
      )}

      {/* 添加邮箱弹窗 */}
      {showAddEmail && (
        <AddEmailConfigInline
          onCreated={() => {
            setShowAddEmail(false);
            loadEmailConfigs();
          }}
          onCancel={() => setShowAddEmail(false)}
        />
      )}

      {/* 编辑邮箱弹窗 */}
      {editEmailConfig && (
        <EditEmailConfigInline
          config={editEmailConfig}
          onSaved={() => {
            setEditEmailConfig(null);
            loadEmailConfigs();
          }}
          onCancel={() => setEditEmailConfig(null)}
        />
      )}
    </div>
  );
}

function AddEmailConfigInline({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
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

  const setField = (key: keyof typeof form, value: any) => setForm((prev) => ({ ...prev, [key]: value }));

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
      onCreated();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-3 rounded-xl border border-primary/30 bg-primary-50 p-4">
      <h4 className="text-xs font-medium text-ink">添加邮箱配置</h4>
      {error && (
        <div className="rounded-lg bg-error-light px-3 py-2 text-xs text-error">
          {error}
        </div>
      )}
      <div className="flex gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => handleSelectPreset("qq")}
          className="flex-1"
        >
          QQ 邮箱
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => handleSelectPreset("163")}
          className="flex-1"
        >
          163 邮箱
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => handleSelectPreset("gmail")}
          className="flex-1"
        >
          Gmail
        </Button>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <MiniInput label="配置名称" value={form.name} onChange={(v) => setField("name", v)} placeholder="如：工作邮箱" />
        <MiniInput label="发件人邮箱" value={form.sender_email} onChange={(v) => setField("sender_email", v)} placeholder="your@email.com" />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <MiniInput label="SMTP 服务器" value={form.smtp_server} onChange={(v) => setField("smtp_server", v)} placeholder="smtp.qq.com" />
        <MiniInput label="SMTP 端口" value={form.smtp_port.toString()} onChange={(v) => setField("smtp_port", parseInt(v) || 587)} type="number" />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <MiniInput label="用户名" value={form.username} onChange={(v) => setField("username", v)} placeholder="邮箱地址或用户名" />
        <MiniInput label="密码/授权码" value={form.password} onChange={(v) => setField("password", v)} type="password" placeholder="应用专用密码" />
      </div>
      <label className="flex items-center gap-2 text-xs text-ink-secondary cursor-pointer">
        <input
          type="checkbox"
          checked={form.smtp_use_tls}
          onChange={(e) => setField("smtp_use_tls", e.target.checked)}
          className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-1 focus:ring-primary"
        />
        <span>使用 TLS 加密</span>
      </label>
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          取消
        </Button>
        <Button size="sm" onClick={handleSubmit} disabled={submitting}>
          {submitting && <Spinner className="mr-1 h-3 w-3" />}
          创建
        </Button>
      </div>
    </div>
  );
}

function EditEmailConfigInline({
  config,
  onSaved,
  onCancel,
}: {
  config: any;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { toast } = useToast();
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

  const setField = (key: keyof typeof form, value: any) => setForm((prev) => ({ ...prev, [key]: value }));

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
    <div className="space-y-3 rounded-xl border border-primary/30 bg-primary-50 p-4">
      <h4 className="text-xs font-medium text-ink">编辑邮箱配置</h4>
      {error && (
        <div className="rounded-lg bg-error-light px-3 py-2 text-xs text-error">
          {error}
        </div>
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        <MiniInput label="配置名称" value={form.name} onChange={(v) => setField("name", v)} />
        <MiniInput label="发件人邮箱" value={form.sender_email} onChange={(v) => setField("sender_email", v)} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <MiniInput label="SMTP 服务器" value={form.smtp_server} onChange={(v) => setField("smtp_server", v)} />
        <MiniInput label="SMTP 端口" value={form.smtp_port.toString()} onChange={(v) => setField("smtp_port", parseInt(v) || 587)} type="number" />
      </div>
      <MiniInput label="用户名" value={form.username} onChange={(v) => setField("username", v)} />
      <MiniInput label="新密码（留空不改）" value={form.password} onChange={(v) => setField("password", v)} type="password" />
      <label className="flex items-center gap-2 text-xs text-ink-secondary cursor-pointer">
        <input
          type="checkbox"
          checked={form.smtp_use_tls}
          onChange={(e) => setField("smtp_use_tls", e.target.checked)}
          className="h-3.5 w-3.5 rounded border-border text-primary focus:ring-1 focus:ring-primary"
        />
        <span>使用 TLS 加密</span>
      </label>
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          取消
        </Button>
        <Button size="sm" onClick={handleSubmit} disabled={submitting}>
          {submitting && <Spinner className="mr-1 h-3 w-3" />}
          保存
        </Button>
      </div>
    </div>
  );
}

/* ======== 运维 Tab ======== */

interface OpResult {
  success: boolean;
  message: string;
}

function OpsTab() {
  const [results, setResults] = useState<Record<string, OpResult>>({});
  const [loadings, setLoadings] = useState<Record<string, boolean>>({});

  const setL = (k: string, v: boolean) =>
    setLoadings((p) => ({ ...p, [k]: v }));
  const setR = (k: string, r: OpResult) =>
    setResults((p) => ({ ...p, [k]: r }));

  const ops = [
    {
      key: "batchProcess",
      label: "一键嵌入 & 粗读未读论文",
      icon: BookOpen,
      desc: "对所有未读论文执行向量嵌入 + AI 粗读（并行处理）",
      action: async () => {
        setL("batchProcess", true);
        try {
          const res = await jobApi.batchProcessUnread(50);
          setR("batchProcess", {
            success: res.failed === 0,
            message: res.message,
          });
        } catch (err) {
          setR("batchProcess", {
            success: false,
            message: err instanceof Error ? err.message : "失败",
          });
        } finally {
          setL("batchProcess", false);
        }
      },
    },
    {
      key: "syncIncremental",
      label: "增量引用同步",
      icon: Link2,
      desc: "同步论文之间的引用关系",
      action: async () => {
        setL("syncIncremental", true);
        try {
          const res = await citationApi.syncIncremental();
          setR("syncIncremental", {
            success: true,
            message: `同步完成，处理 ${res.processed_papers ?? 0} 篇，新增 ${res.edges_inserted} 条边`,
          });
        } catch (err) {
          setR("syncIncremental", {
            success: false,
            message: err instanceof Error ? err.message : "失败",
          });
        } finally {
          setL("syncIncremental", false);
        }
      },
    },
    {
      key: "dailyJob",
      label: "执行每日任务",
      icon: Calendar,
      desc: "抓取论文 + 生成简报",
      action: async () => {
        setL("dailyJob", true);
        try {
          await jobApi.dailyRun();
          setR("dailyJob", {
            success: true,
            message: "每日任务执行完成",
          });
        } catch (err) {
          setR("dailyJob", {
            success: false,
            message: err instanceof Error ? err.message : "失败",
          });
        } finally {
          setL("dailyJob", false);
        }
      },
    },
    {
      key: "weeklyJob",
      label: "每周图维护",
      icon: Network,
      desc: "引用同步 + 图谱维护",
      action: async () => {
        setL("weeklyJob", true);
        try {
          await jobApi.weeklyGraphRun();
          setR("weeklyJob", {
            success: true,
            message: "每周维护执行完成",
          });
        } catch (err) {
          setR("weeklyJob", {
            success: false,
            message: err instanceof Error ? err.message : "失败",
          });
        } finally {
          setL("weeklyJob", false);
        }
      },
    },
    {
      key: "health",
      label: "系统健康检查",
      icon: Zap,
      desc: "数据库 + 统计信息",
      action: async () => {
        setL("health", true);
        try {
          const res = await systemApi.status();
          setR("health", {
            success: true,
            message: `${res.health.status === "ok" ? "正常" : "异常"} | ${res.counts.topics} 主题 | ${res.counts.papers_latest_200} 论文`,
          });
        } catch (err) {
          setR("health", {
            success: false,
            message: err instanceof Error ? err.message : "失败",
          });
        } finally {
          setL("health", false);
        }
      },
    },
  ];

  return (
    <div className="grid gap-2">
      {ops.map((op) => (
        <div
          key={op.key}
          className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3"
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-page">
            <op.icon className="h-4 w-4 text-ink-secondary" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-ink">{op.label}</p>
            <p className="text-[10px] text-ink-tertiary">{op.desc}</p>
            {results[op.key] && (
              <p
                className={cn(
                  "mt-1 text-[10px]",
                  results[op.key].success ? "text-success" : "text-error",
                )}
              >
                {results[op.key].success ? (
                  <CheckCircle2 className="mr-0.5 inline h-3 w-3" />
                ) : (
                  <AlertTriangle className="mr-0.5 inline h-3 w-3" />
                )}
                {results[op.key].message}
              </p>
            )}
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={op.action}
            loading={!!loadings[op.key]}
            className="shrink-0"
          >
            <Play className="h-3 w-3" />
          </Button>
        </div>
      ))}
    </div>
  );
}
