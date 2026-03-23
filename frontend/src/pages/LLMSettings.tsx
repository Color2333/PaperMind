/**
 * LLM 模型配置管理页面
 */
import { useState, useCallback, useEffect } from "react";
import { Plus, Trash2, Edit, Save, X, Zap, Settings, Check } from "lucide-react";
import { llmConfigApi, type LLMConfigItem, type LLMConfigCreate } from "@/services/llmConfigApi";

// 预设配置模板
const PRESET_CONFIGS = [
  {
    provider: "zhipu",
    name: "智谱 AI - 经济型",
    model_skim: "glm-4-flash",
    model_deep: "glm-4.7",
    model_vision: "glm-4v-flash",
    model_embedding: "embedding-3",
    model_fallback: "glm-4-flash",
  },
  {
    provider: "zhipu",
    name: "智谱 AI - 高级型",
    model_skim: "glm-4.7",
    model_deep: "glm-4-air",
    model_vision: "glm-4v-flash",
    model_embedding: "embedding-3",
    model_fallback: "glm-4.7",
  },
  {
    provider: "siliconflow",
    name: "硅基流动 - 性价比",
    model_skim: "Qwen/Qwen2.5-7B-Instruct",
    model_deep: "deepseek-ai/DeepSeek-V3",
    model_vision: "Pro/Qwen/Qwen2.5-VL-72B-Instruct",
    model_embedding: "BAAI/bge-m3",
    model_fallback: "Qwen/Qwen2.5-7B-Instruct",
  },
];

export default function LLMSettings() {
  const [configs, setConfigs] = useState<LLMConfigItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formData, setFormData] = useState<LLMConfigCreate>({
    name: "",
    provider: "zhipu",
    api_key: "",
    api_base_url: "",
    model_skim: "",
    model_deep: "",
    model_vision: "",
    model_embedding: "",
    model_fallback: "",
  });

  const loadConfigs = useCallback(async () => {
    setLoading(true);
    try {
      const result = await llmConfigApi.list();
      setConfigs(result.configs);
      setActiveId(result.active_id);
    } catch (err) {
      console.error("Failed to load configs:", err);
      alert("加载配置失败：" + (err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  const resetForm = useCallback(() => {
    setFormData({
      name: "",
      provider: "zhipu",
      api_key: "",
      api_base_url: "",
      model_skim: "",
      model_deep: "",
      model_vision: "",
      model_embedding: "",
      model_fallback: "",
    });
  }, []);

  const usePreset = useCallback((preset: typeof PRESET_CONFIGS[0]) => {
    setFormData({
      ...preset,
      api_key: "",
      api_base_url: "",
      name: preset.name,
      provider: preset.provider,
    });
    setShowCreateForm(true);
  }, []);

  const handleCreate = useCallback(async () => {
    try {
      await llmConfigApi.create(formData);
      setShowCreateForm(false);
      loadConfigs();
      resetForm();
    } catch (err) {
      alert("创建失败：" + (err as Error).message);
    }
  }, [formData, loadConfigs, resetForm]);

  const handleActivate = useCallback(async (configId: string) => {
    try {
      await llmConfigApi.activate(configId);
      loadConfigs();
    } catch (err) {
      alert("激活失败：" + (err as Error).message);
    }
  }, [loadConfigs]);

  const handleDelete = useCallback(async (configId: string) => {
    if (!confirm("确定要删除此配置吗？")) return;
    try {
      await llmConfigApi.delete(configId);
      loadConfigs();
    } catch (err) {
      alert("删除失败：" + (err as Error).message);
    }
  }, [loadConfigs]);

  const startEdit = useCallback((config: LLMConfigItem) => {
    setEditingId(config.id);
    setFormData({
      name: config.name,
      provider: config.provider,
      api_key: "",
      api_base_url: config.api_base_url || "",
      model_skim: config.model_skim,
      model_deep: config.model_deep,
      model_vision: config.model_vision || "",
      model_embedding: config.model_embedding,
      model_fallback: config.model_fallback,
    });
    setShowCreateForm(false);
  }, []);

  const handleUpdate = useCallback(async (configId: string) => {
    try {
      await llmConfigApi.update(configId, formData);
      setEditingId(null);
      loadConfigs();
      resetForm();
    } catch (err) {
      alert("更新失败：" + (err as Error).message);
    }
  }, [formData, loadConfigs, resetForm]);

  return (
    <div className="min-h-screen bg-[#0a0a0f]">
      {/* 顶部导航 */}
      <div className="border-b border-white/10 bg-[#1a1a2e]/50 backdrop-blur-sm">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <Settings className="h-6 w-6 text-primary" />
            <h1 className="text-xl font-medium text-white">LLM 模型配置</h1>
          </div>
          <button
            type="button"
            onClick={() => setShowCreateForm(!showCreateForm)}
            className="flex items-center gap-2 rounded-lg bg-primary/20 px-4 py-2 text-sm text-primary hover:bg-primary/30"
          >
            <Plus className="h-4 w-4" />
            新建配置
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-6 py-8">
        {/* 预设配置推荐 */}
        {!showCreateForm && configs.length === 0 && (
          <div className="mb-8 rounded-xl border border-white/10 bg-white/5 p-6">
            <h2 className="mb-4 flex items-center gap-2 text-lg text-white">
              <Zap className="h-5 w-5 text-yellow-400" />
              快速开始 - 选择预设配置
            </h2>
            <div className="grid gap-4 md:grid-cols-3">
              {PRESET_CONFIGS.map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  onClick={() => usePreset(preset)}
                  className="rounded-lg border border-white/10 bg-white/[0.02] p-4 text-left hover:border-primary/50 hover:bg-primary/5"
                >
                  <h3 className="font-medium text-white">{preset.name}</h3>
                  <p className="mt-2 text-xs text-white/40">
                    粗读：{preset.model_skim}
                    <br />
                    精读：{preset.model_deep}
                  </p>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 创建/编辑表单 */}
        {showCreateForm && (
          <div className="mb-8 rounded-xl border border-primary/30 bg-primary/5 p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-medium text-white">
                {editingId ? "编辑配置" : "创建新配置"}
              </h2>
              <button
                type="button"
                onClick={() => {
                  setShowCreateForm(false);
                  setEditingId(null);
                  resetForm();
                }}
                className="rounded-lg p-2 text-white/40 hover:bg-white/10"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label htmlFor="config-name" className="mb-1 block text-xs text-white/60">配置名称</label>
                <input
                  id="config-name"
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-primary/50"
                  placeholder="例如：智谱 AI-经济型"
                />
              </div>

              <div>
                <label htmlFor="config-provider" className="mb-1 block text-xs text-white/60">服务商</label>
                <select
                  id="config-provider"
                  value={formData.provider}
                  onChange={(e) => setFormData({ ...formData, provider: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-primary/50"
                >
                  <option value="zhipu">智谱 AI (Zhipu)</option>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="siliconflow">硅基流动 (SiliconFlow)</option>
                </select>
              </div>

              <div className="md:col-span-2">
                <label htmlFor="config-apikey" className="mb-1 block text-xs text-white/60">API Key</label>
                <input
                  id="config-apikey"
                  type="password"
                  value={formData.api_key}
                  onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-primary/50"
                  placeholder="sk-..."
                />
              </div>

              <div className="md:col-span-2">
                <label htmlFor="config-baseurl" className="mb-1 block text-xs text-white/60">API Base URL（可选）</label>
                <input
                  id="config-baseurl"
                  type="text"
                  value={formData.api_base_url || ""}
                  onChange={(e) => setFormData({ ...formData, api_base_url: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-primary/50"
                  placeholder="https://..."
                />
              </div>

              <div>
                <label htmlFor="model-skim" className="mb-1 block text-xs text-white/60">粗读模型（简单任务）</label>
                <input
                  id="model-skim"
                  type="text"
                  value={formData.model_skim}
                  onChange={(e) => setFormData({ ...formData, model_skim: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-primary/50"
                  placeholder="glm-4-flash"
                />
              </div>

              <div>
                <label htmlFor="model-deep" className="mb-1 block text-xs text-white/60">精读模型（复杂任务）</label>
                <input
                  id="model-deep"
                  type="text"
                  value={formData.model_deep}
                  onChange={(e) => setFormData({ ...formData, model_deep: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-primary/50"
                  placeholder="glm-4.7"
                />
              </div>

              <div>
                <label htmlFor="model-vision" className="mb-1 block text-xs text-white/60">视觉模型</label>
                <input
                  id="model-vision"
                  type="text"
                  value={formData.model_vision || ""}
                  onChange={(e) => setFormData({ ...formData, model_vision: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-primary/50"
                  placeholder="glm-4v-flash"
                />
              </div>

              <div>
                <label htmlFor="model-embedding" className="mb-1 block text-xs text-white/60">嵌入模型</label>
                <input
                  id="model-embedding"
                  type="text"
                  value={formData.model_embedding}
                  onChange={(e) => setFormData({ ...formData, model_embedding: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-primary/50"
                  placeholder="embedding-3"
                />
              </div>

              <div className="md:col-span-2">
                <label htmlFor="model-fallback" className="mb-1 block text-xs text-white/60">降级备用模型</label>
                <input
                  id="model-fallback"
                  type="text"
                  value={formData.model_fallback}
                  onChange={(e) => setFormData({ ...formData, model_fallback: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none focus:border-primary/50"
                  placeholder="glm-4-flash"
                />
              </div>
            </div>

            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={editingId ? () => handleUpdate(editingId) : handleCreate}
                className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm text-white hover:bg-primary/90"
              >
                <Save className="h-4 w-4" />
                {editingId ? "更新配置" : "创建配置"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowCreateForm(false);
                  setEditingId(null);
                  resetForm();
                }}
                className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/60 hover:bg-white/10"
              >
                取消
              </button>
            </div>
          </div>
        )}

        {/* 配置列表 */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          </div>
        ) : (
          <div className="grid gap-4">
            {configs.map((config) => (
              <div
                key={config.id}
                className={`rounded-xl border p-5 ${
                  config.is_active
                    ? "border-primary/50 bg-primary/5"
                    : "border-white/10 bg-white/[0.02]"
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <h3 className="text-lg font-medium text-white">{config.name}</h3>
                      {config.is_active && (
                        <span className="flex items-center gap-1 rounded-full bg-primary/20 px-2 py-0.5 text-xs text-primary">
                          <Check className="h-3 w-3" />
                          使用中
                        </span>
                      )}
                      <span className="rounded bg-white/10 px-2 py-0.5 text-xs text-white/60">
                        {config.provider}
                      </span>
                    </div>

                    <div className="mt-3 grid gap-2 md:grid-cols-3">
                      <div className="text-xs">
                        <span className="text-white/40">粗读：</span>
                        <span className="text-white/80">{config.model_skim}</span>
                      </div>
                      <div className="text-xs">
                        <span className="text-white/40">精读：</span>
                        <span className="text-white/80">{config.model_deep}</span>
                      </div>
                      <div className="text-xs">
                        <span className="text-white/40">视觉：</span>
                        <span className="text-white/80">{config.model_vision || "未设置"}</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {!config.is_active && (
                      <button
                        type="button"
                        onClick={() => handleActivate(config.id)}
                        className="flex items-center gap-1 rounded-lg bg-primary/20 px-3 py-1.5 text-xs text-primary hover:bg-primary/30"
                      >
                        <Zap className="h-3.5 w-3.5" />
                        激活
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => startEdit(config)}
                      className="rounded-lg p-2 text-white/40 hover:bg-white/10 hover:text-white"
                      title="编辑"
                    >
                      <Edit className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(config.id)}
                      disabled={config.is_active}
                      className="rounded-lg p-2 text-white/40 hover:bg-red-500/20 hover:text-red-400 disabled:opacity-50"
                      title="删除"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}

            {configs.length === 0 && !showCreateForm && (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <Settings className="mb-4 h-12 w-12 text-white/20" />
                <p className="text-white/40">暂无配置</p>
                <p className="text-sm text-white/20">点击上方"新建配置"或选择预设配置开始</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
