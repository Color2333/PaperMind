/**
 * LLM 配置管理页面
 * @author Bamzc
 */
import { useState, useEffect, useCallback } from "react";
import { llmConfigApi } from "@/services/api";
import type { LLMProviderConfig, LLMProviderCreate, ActiveLLMConfig } from "@/types";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { Empty } from "@/components/ui/Empty";
import { Modal } from "@/components/ui/Modal";
import type { LLMProviderUpdate } from "@/types";
import {
  Plus,
  Trash2,
  Zap,
  Settings2,
  Eye,
  EyeOff,
  Power,
  PowerOff,
  Server,
  Pencil,
} from "lucide-react";

const PROVIDER_PRESETS: Record<string, { label: string; base_url: string; models: Partial<LLMProviderCreate> }> = {
  zhipu: {
    label: "智谱 AI (ZhipuAI)",
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

function ProviderBadge({ provider }: { provider: string }) {
  const colors: Record<string, string> = {
    zhipu: "bg-blue-100 text-blue-700",
    openai: "bg-emerald-100 text-emerald-700",
    anthropic: "bg-orange-100 text-orange-700",
  };
  const labels: Record<string, string> = {
    zhipu: "智谱",
    openai: "OpenAI",
    anthropic: "Anthropic",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${colors[provider] || "bg-gray-100 text-gray-700"}`}>
      <Server className="h-3 w-3" />
      {labels[provider] || provider}
    </span>
  );
}

export default function Settings() {
  const [configs, setConfigs] = useState<LLMProviderConfig[]>([]);
  const [activeInfo, setActiveInfo] = useState<ActiveLLMConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
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
      console.error("Failed to load LLM configs:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleActivate = async (id: string) => {
    setSubmitting(true);
    try {
      await llmConfigApi.activate(id);
      await load();
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeactivateAll = async () => {
    setSubmitting(true);
    try {
      await llmConfigApi.deactivate();
      await load();
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除这个配置吗？")) return;
    await llmConfigApi.delete(id);
    await load();
  };

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  return (
    <div className="space-y-6">
      {/* 页头 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink">LLM 配置管理</h1>
          <p className="mt-1 text-sm text-ink-secondary">
            管理多个 AI 提供者的 API Key，支持自由切换
          </p>
        </div>
        <Button onClick={() => setShowAdd(true)}>
          <Plus className="mr-1.5 h-4 w-4" />
          添加配置
        </Button>
      </div>

      {/* 当前生效配置 */}
      <Card>
        <div className="flex items-center gap-3 border-b border-border px-5 py-3.5">
          <Zap className="h-4.5 w-4.5 text-primary" />
          <span className="text-sm font-medium text-ink">当前生效配置</span>
        </div>
        <div className="px-5 py-4">
          {activeInfo ? (
            <div className="flex items-center justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <ProviderBadge provider={activeInfo.config.provider || ""} />
                  <Badge variant={activeInfo.source === "database" ? "success" : "info"}>
                    {activeInfo.source === "database" ? "用户配置" : ".env 默认"}
                  </Badge>
                  {activeInfo.source === "database" && "name" in activeInfo.config && (
                    <span className="text-sm font-medium text-ink">{(activeInfo.config as LLMProviderConfig).name}</span>
                  )}
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-tertiary">
                  <span>粗读: {activeInfo.config.model_skim}</span>
                  <span>精读: {activeInfo.config.model_deep}</span>
                  {activeInfo.config.model_vision && <span>视觉: {activeInfo.config.model_vision}</span>}
                  <span>嵌入: {activeInfo.config.model_embedding}</span>
                </div>
              </div>
              {activeInfo.source === "database" && (
                <Button variant="ghost" size="sm" onClick={handleDeactivateAll} disabled={submitting}>
                  <PowerOff className="mr-1.5 h-3.5 w-3.5" />
                  切回默认
                </Button>
              )}
            </div>
          ) : (
            <p className="text-sm text-ink-secondary">加载中...</p>
          )}
        </div>
      </Card>

      {/* 配置列表 */}
      {configs.length === 0 ? (
        <Empty title="暂无自定义配置" description="点击右上角添加你的第一个 LLM 提供者配置" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2">
          {configs.map((cfg) => (
            <ConfigCard
              key={cfg.id}
              config={cfg}
              onActivate={() => handleActivate(cfg.id)}
              onDelete={() => handleDelete(cfg.id)}
              onUpdated={load}
              submitting={submitting}
            />
          ))}
        </div>
      )}

      {/* 新增弹窗 */}
      {showAdd && (
        <AddConfigModal
          onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); load(); }}
        />
      )}
    </div>
  );
}

/* ---------- 配置卡片 ---------- */

function ConfigCard({
  config,
  onActivate,
  onDelete,
  onUpdated,
  submitting,
}: {
  config: LLMProviderConfig;
  onActivate: () => void;
  onDelete: () => void;
  onUpdated: () => void;
  submitting: boolean;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <>
      <Card className={config.is_active ? "ring-2 ring-primary/40" : ""}>
        <div className="p-5">
          {/* 头部 */}
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold text-ink">{config.name}</span>
              <ProviderBadge provider={config.provider} />
              {config.is_active && (
                <Badge variant="default">已激活</Badge>
              )}
            </div>
            <div className="flex gap-1">
              <Button variant="ghost" size="sm" onClick={() => setEditing(true)} title="编辑">
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              {!config.is_active && (
                <Button variant="ghost" size="sm" onClick={onActivate} disabled={submitting} title="激活">
                  <Power className="h-3.5 w-3.5" />
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={onDelete} title="删除">
                <Trash2 className="h-3.5 w-3.5 text-red-500" />
              </Button>
            </div>
          </div>

          {/* API Key */}
          <div className="mt-3 text-xs text-ink-secondary">
            <span className="font-mono">{config.api_key_masked}</span>
            {config.api_base_url && (
              <span className="ml-3 text-ink-tertiary">{config.api_base_url}</span>
            )}
          </div>

          {/* 模型列表 */}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <ModelChip label="粗读" model={config.model_skim} />
            <ModelChip label="精读" model={config.model_deep} />
            {config.model_vision && <ModelChip label="视觉" model={config.model_vision} />}
            <ModelChip label="嵌入" model={config.model_embedding} />
            <ModelChip label="降级" model={config.model_fallback} />
          </div>
        </div>
      </Card>
      {editing && (
        <EditConfigModal
          config={config}
          onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); onUpdated(); }}
        />
      )}
    </>
  );
}

function ModelChip({ label, model }: { label: string; model: string }) {
  return (
    <div className="flex items-center gap-1.5 rounded-md bg-surface px-2.5 py-1.5 text-xs">
      <span className="font-medium text-ink-secondary">{label}</span>
      <span className="truncate font-mono text-ink">{model}</span>
    </div>
  );
}

/* ---------- 新增配置弹窗 ---------- */

function AddConfigModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
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

  const setField = (key: keyof LLMProviderCreate, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

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
    if (!form.name.trim()) { setError("请输入配置名称"); return; }
    if (!form.api_key.trim()) { setError("请输入 API Key"); return; }
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
    <Modal title="添加 LLM 配置" onClose={onClose} maxWidth="lg">
      <div className="space-y-4">
        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-600">{error}</div>
        )}

        {/* 基本信息 */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-ink-secondary">配置名称</label>
            <Input
              placeholder="如：我的智谱配置"
              value={form.name}
              onChange={(e) => setField("name", e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-ink-secondary">提供者</label>
            <select
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-ink outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
              value={form.provider}
              onChange={(e) => handleProviderChange(e.target.value)}
            >
              {Object.entries(PROVIDER_PRESETS).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* API Key */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-ink-secondary">API Key</label>
          <div className="relative">
            <Input
              type={showKey ? "text" : "password"}
              placeholder="sk-..."
              value={form.api_key}
              onChange={(e) => setField("api_key", e.target.value)}
              className="pr-10"
            />
            <button
              type="button"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink"
              onClick={() => setShowKey(!showKey)}
            >
              {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {/* Base URL */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-ink-secondary">API Base URL（可选）</label>
          <Input
            placeholder="https://api.openai.com/v1"
            value={form.api_base_url || ""}
            onChange={(e) => setField("api_base_url", e.target.value)}
          />
        </div>

        {/* 模型配置 */}
        <div>
          <div className="mb-2 flex items-center gap-1.5">
            <Settings2 className="h-3.5 w-3.5 text-ink-tertiary" />
            <span className="text-xs font-medium text-ink-secondary">模型配置</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <ModelInput label="粗读模型" value={form.model_skim} onChange={(v) => setField("model_skim", v)} />
            <ModelInput label="精读模型" value={form.model_deep} onChange={(v) => setField("model_deep", v)} />
            <ModelInput label="视觉模型" value={form.model_vision || ""} onChange={(v) => setField("model_vision", v)} />
            <ModelInput label="嵌入模型" value={form.model_embedding} onChange={(v) => setField("model_embedding", v)} />
            <ModelInput label="降级模型" value={form.model_fallback} onChange={(v) => setField("model_fallback", v)} />
          </div>
        </div>

        {/* 操作 */}
        <div className="flex justify-end gap-3 pt-2">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? <Spinner className="mr-1.5 h-4 w-4" /> : <Plus className="mr-1.5 h-4 w-4" />}
            创建
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function ModelInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="mb-1 block text-xs text-ink-tertiary">{label}</label>
      <Input
        placeholder={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="font-mono text-xs"
      />
    </div>
  );
}

/* ---------- 编辑配置弹窗 ---------- */

function EditConfigModal({
  config,
  onClose,
  onSaved,
}: {
  config: LLMProviderConfig;
  onClose: () => void;
  onSaved: () => void;
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
  const [showKey, setShowKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const setField = (key: keyof LLMProviderUpdate, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

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
    <Modal title={`编辑：${config.name}`} onClose={onClose} maxWidth="lg">
      <div className="space-y-4">
        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-600">{error}</div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-ink-secondary">配置名称</label>
            <Input value={form.name || ""} onChange={(e) => setField("name", e.target.value)} />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-ink-secondary">提供者</label>
            <select
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-ink outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
              value={form.provider || config.provider}
              onChange={(e) => setField("provider", e.target.value)}
            >
              {Object.entries(PROVIDER_PRESETS).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* API Key（可选更新） */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-ink-secondary">
            新 API Key（留空则不修改，当前: {config.api_key_masked}）
          </label>
          <div className="relative">
            <Input
              type={showKey ? "text" : "password"}
              placeholder="留空保持不变"
              value={newApiKey}
              onChange={(e) => setNewApiKey(e.target.value)}
              className="pr-10"
            />
            <button
              type="button"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary hover:text-ink"
              onClick={() => setShowKey(!showKey)}
            >
              {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-ink-secondary">API Base URL</label>
          <Input
            placeholder="https://api.openai.com/v1"
            value={form.api_base_url || ""}
            onChange={(e) => setField("api_base_url", e.target.value)}
          />
        </div>

        {/* 模型配置 */}
        <div>
          <div className="mb-2 flex items-center gap-1.5">
            <Settings2 className="h-3.5 w-3.5 text-ink-tertiary" />
            <span className="text-xs font-medium text-ink-secondary">模型配置</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <ModelInput label="粗读模型" value={form.model_skim || ""} onChange={(v) => setField("model_skim", v)} />
            <ModelInput label="精读模型" value={form.model_deep || ""} onChange={(v) => setField("model_deep", v)} />
            <ModelInput label="视觉模型" value={form.model_vision || ""} onChange={(v) => setField("model_vision", v)} />
            <ModelInput label="嵌入模型" value={form.model_embedding || ""} onChange={(v) => setField("model_embedding", v)} />
            <ModelInput label="降级模型" value={form.model_fallback || ""} onChange={(v) => setField("model_fallback", v)} />
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button onClick={handleSave} disabled={submitting}>
            {submitting ? <Spinner className="mr-1.5 h-4 w-4" /> : <Pencil className="mr-1.5 h-4 w-4" />}
            保存修改
          </Button>
        </div>
      </div>
    </Modal>
  );
}
