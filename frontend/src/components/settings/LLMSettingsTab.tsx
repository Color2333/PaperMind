import { useState, useCallback, useEffect } from "react";
import { Cpu, Plus, Trash2, Pencil, Power, PowerOff, Eye, EyeOff, Server } from "lucide-react";
import { useToast } from "@/contexts/ToastContext";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { llmConfigApi } from "@/services/api";
import { getErrorMessage } from "@/lib/errorHandler";
import { cn } from "@/lib/utils";
import { ProviderBadge } from "./shared";
import type {
  LLMProviderConfig,
  LLMProviderUpdate,
  ActiveLLMConfig,
  LLMProvider,
} from "@/types";

const PROVIDER_PRESETS: Record<string, { label: string; base_url: string; models: Record<string, string> }> = {
  xiaomi: {
    label: "小米 MiMo",
    base_url: "https://token-plan-cn.xiaomimimo.com/v1",
    models: { model_skim: "mimo-v2-omni", model_deep: "mimo-v2.5-pro", model_vision: "mimo-v2.5", model_embedding: "text-embedding-v4", model_fallback: "mimo-v2.5-pro" },
  },
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

type ConfigForm = {
  name: string;
  provider: LLMProvider;
  api_key: string;
  api_base_url: string;
  model_skim: string;
  model_deep: string;
  model_vision: string;
  model_embedding: string;
  model_fallback: string;
};

export function LLMSettingsTab() {
  const { toast } = useToast();
  const [configs, setConfigs] = useState<LLMProviderConfig[]>([]);
  const [activeInfo, setActiveInfo] = useState<ActiveLLMConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editCfg, setEditCfg] = useState<LLMProviderConfig | null>(null);
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

function ConfigModal({ config, onClose, onSaved }: { config?: LLMProviderConfig | null; onClose: () => void; onSaved: () => void }) {
  const { toast } = useToast();
  const [form, setForm] = useState<ConfigForm>({
    name: config?.name || "",
    provider: config?.provider || "xiaomi",
    api_key: "",
    api_base_url: config?.api_base_url || PROVIDER_PRESETS.xiaomi.base_url,
    model_skim: config?.model_skim || "mimo-v2-omni",
    model_deep: config?.model_deep || "mimo-v2.5-pro",
    model_vision: config?.model_vision || "mimo-v2.5",
    model_embedding: config?.model_embedding || "text-embedding-v4",
    model_fallback: config?.model_fallback || "mimo-v2.5-pro",
  });
  const [showKey, setShowKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const setField = (k: string, v: string) => setForm((p) => ({ ...p, [k]: v }));

  const handleProviderChange = (provider: string) => {
    const preset = PROVIDER_PRESETS[provider];
    if (preset) {
      setForm((p) => ({ ...p, provider: provider as LLMProvider, api_base_url: preset.base_url, ...preset.models }));
    }
  };

  const handleSubmit = async () => {
    if (!form.name.trim()) { setError("请输入配置名称"); return; }
    if (!form.api_key.trim() && !config) { setError("请输入 API Key"); return; }
    setSubmitting(true);
    setError("");
    try {
      if (config) {
        const payload: LLMProviderUpdate = { name: form.name, provider: form.provider, api_base_url: form.api_base_url, model_skim: form.model_skim, model_deep: form.model_deep, model_vision: form.model_vision, model_embedding: form.model_embedding, model_fallback: form.model_fallback };
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
