/**
 * LLM 模型配置管理页面
 */
import { useState, useCallback, useEffect } from "react";
import { Plus, Trash2, Edit, Save, X, Zap, Settings, Check, Brain, Eye, Layers, Key } from "lucide-react";
import { llmConfigApi, type LLMConfigItem, type LLMConfigCreate } from "@/services/llmConfigApi";

// 预设配置模板
const PRESET_CONFIGS = [
  {
    provider: "zhipu",
    name: "智谱 AI - GLM-4.7",
    description: "统一配置，文本任务使用 GLM-4.7，视觉任务使用 GLM-4.6V",
    model_skim: "glm-4.7",
    model_deep: "glm-4.7",
    model_vision: "glm-4.6v",
    model_embedding: "embedding-3",
    model_fallback: "glm-4.7",
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

  const activeConfig = configs.find((c) => c.id === activeId);

  return (
    <div className="min-h-screen bg-[#0a0a0f]">
      {/* 顶部导航 */}
      <div className="border-b border-white/10 bg-[#1a1a2e]/50 backdrop-blur-sm">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/20">
              <Brain className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-medium text-white">LLM 模型配置</h1>
              <p className="text-xs text-white/40">管理 AI 模型配置，控制成本</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowCreateForm(!showCreateForm)}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm text-white hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            新建配置
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-6 py-8">
        {/* 当前激活配置概览 */}
        {activeConfig && !showCreateForm && (
          <div className="mb-8 rounded-2xl border border-primary/30 bg-gradient-to-br from-primary/10 to-primary/5 p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary/20">
                  <Check className="h-7 w-7 text-primary" />
                </div>
                <div>
                  <p className="text-xs text-white/40">当前使用</p>
                  <h2 className="text-xl font-medium text-white">{activeConfig.name}</h2>
                  <p className="mt-1 flex items-center gap-3 text-xs text-white/60">
                    <span className="flex items-center gap-1">
                      <Brain className="h-3 w-3" />
                      {activeConfig.model_skim}
                    </span>
                    <span className="flex items-center gap-1">
                      <Eye className="h-3 w-3" />
                      {activeConfig.model_vision || "未设置"}
                    </span>
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => startEdit(activeConfig)}
                className="flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-4 py-2 text-sm text-white/80 hover:bg-white/10"
              >
                <Edit className="h-4 w-4" />
                编辑配置
              </button>
            </div>
          </div>
        )}

        {/* 预设配置推荐 */}
        {!showCreateForm && configs.length === 0 && (
          <div className="mb-8 rounded-2xl border border-white/10 bg-white/[0.02] p-6">
            <h2 className="mb-4 flex items-center gap-2 text-lg text-white">
              <Zap className="h-5 w-5 text-yellow-400" />
              快速开始
            </h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {PRESET_CONFIGS.map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  onClick={() => usePreset(preset)}
                  className="group relative overflow-hidden rounded-xl border border-white/10 bg-white/[0.02] p-5 text-left transition-all hover:border-primary/50 hover:bg-primary/5"
                >
                  <div className="mb-3 flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/20 group-hover:bg-primary/30">
                      <Brain className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="font-medium text-white">{preset.name}</h3>
                      <p className="text-xs text-white/40">智谱 AI</p>
                    </div>
                  </div>
                  <p className="mb-3 text-xs text-white/50">{preset.description}</p>
                  <div className="flex flex-wrap gap-1">
                    <span className="rounded bg-white/10 px-2 py-0.5 text-xs text-white/60">
                      {preset.model_skim}
                    </span>
                    <span className="rounded bg-white/10 px-2 py-0.5 text-xs text-white/60">
                      {preset.model_vision}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 创建/编辑表单 */}
        {showCreateForm && (
          <div className="mb-8 rounded-2xl border border-white/10 bg-white/[0.02] p-6">
            <div className="mb-6 flex items-center justify-between">
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
                className="rounded-lg p-2 text-white/40 hover:bg-white/10 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* 基础信息 */}
            <div className="mb-6">
              <h3 className="mb-3 flex items-center gap-2 text-sm text-white/60">
                <Key className="h-4 w-4" />
                基础信息
              </h3>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label htmlFor="config-name" className="mb-1.5 block text-xs text-white/60">
                    配置名称
                  </label>
                  <input
                    id="config-name"
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-primary/50"
                    placeholder="例如：智谱 AI 配置"
                  />
                </div>

                <div>
                  <label htmlFor="config-provider" className="mb-1.5 block text-xs text-white/60">
                    服务商
                  </label>
                  <select
                    id="config-provider"
                    value={formData.provider}
                    onChange={(e) => setFormData({ ...formData, provider: e.target.value })}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-primary/50"
                  >
                    <option value="zhipu">智谱 AI (Zhipu)</option>
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="siliconflow">硅基流动 (SiliconFlow)</option>
                  </select>
                </div>

                <div className="md:col-span-2">
                  <label htmlFor="config-apikey" className="mb-1.5 block text-xs text-white/60">
                    API Key
                  </label>
                  <input
                    id="config-apikey"
                    type="password"
                    value={formData.api_key}
                    onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-primary/50"
                    placeholder="输入 API Key"
                  />
                </div>
              </div>
            </div>

            {/* 模型配置 */}
            <div>
              <h3 className="mb-3 flex items-center gap-2 text-sm text-white/60">
                <Layers className="h-4 w-4" />
                模型配置
              </h3>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label htmlFor="model-skim" className="mb-1.5 block text-xs text-white/60">
                    <Brain className="mr-1 inline h-3 w-3" />
                    文本模型（粗读/精读/翻译）
                  </label>
                  <input
                    id="model-skim"
                    type="text"
                    value={formData.model_skim}
                    onChange={(e) => {
                      setFormData({ ...formData, model_skim: e.target.value, model_deep: e.target.value, model_fallback: e.target.value });
                    }}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-primary/50"
                    placeholder="glm-4.7"
                  />
                </div>

                <div>
                  <label htmlFor="model-vision" className="mb-1.5 block text-xs text-white/60">
                    <Eye className="mr-1 inline h-3 w-3" />
                    视觉模型（图表分析）
                  </label>
                  <input
                    id="model-vision"
                    type="text"
                    value={formData.model_vision || ""}
                    onChange={(e) => setFormData({ ...formData, model_vision: e.target.value })}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-primary/50"
                    placeholder="glm-4.6v"
                  />
                </div>

                <div>
                  <label htmlFor="model-embedding" className="mb-1.5 block text-xs text-white/60">
                    <Layers className="mr-1 inline h-3 w-3" />
                    嵌入模型（RAG 向量化）
                  </label>
                  <input
                    id="model-embedding"
                    type="text"
                    value={formData.model_embedding}
                    onChange={(e) => setFormData({ ...formData, model_embedding: e.target.value })}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-primary/50"
                    placeholder="embedding-3"
                  />
                </div>

                <div>
                  <label htmlFor="model-fallback" className="mb-1.5 block text-xs text-white/60">
                    <Zap className="mr-1 inline h-3 w-3" />
                    降级备用模型
                  </label>
                  <input
                    id="model-fallback"
                    type="text"
                    value={formData.model_fallback}
                    onChange={(e) => setFormData({ ...formData, model_fallback: e.target.value })}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-primary/50"
                    placeholder="glm-4.7"
                  />
                </div>
              </div>
            </div>

            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={editingId ? () => handleUpdate(editingId) : handleCreate}
                className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm text-white hover:bg-primary/90"
              >
                <Save className="h-4 w-4" />
                {editingId ? "保存修改" : "创建配置"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowCreateForm(false);
                  setEditingId(null);
                  resetForm();
                }}
                className="rounded-lg border border-white/10 bg-white/5 px-5 py-2.5 text-sm text-white/60 hover:bg-white/10"
              >
                取消
              </button>
            </div>
          </div>
        )}

        {/* 配置列表 */}
        {!showCreateForm && configs.length > 0 && (
          <div>
            <h3 className="mb-4 flex items-center gap-2 text-sm text-white/40">
              <Settings className="h-4 w-4" />
              所有配置 ({configs.length})
            </h3>
            <div className="grid gap-3">
              {configs.map((config) => (
                <div
                  key={config.id}
                  className={`group rounded-xl border p-4 transition-all ${
                    config.is_active
                      ? "border-primary/50 bg-primary/5"
                      : "border-white/10 bg-white/[0.02] hover:border-white/20"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div
                        className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                          config.is_active ? "bg-primary/20" : "bg-white/10"
                        }`}
                      >
                        <Brain className={`h-5 w-5 ${config.is_active ? "text-primary" : "text-white/40"}`} />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h4 className="font-medium text-white">{config.name}</h4>
                          {config.is_active && (
                            <span className="flex items-center gap-1 rounded-full bg-primary/20 px-2 py-0.5 text-xs text-primary">
                              <Check className="h-3 w-3" />
                              使用中
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-white/40">{config.provider}</p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {!config.is_active && (
                        <button
                          type="button"
                          onClick={() => handleActivate(config.id)}
                          className="flex items-center gap-1.5 rounded-lg bg-primary/20 px-3 py-1.5 text-xs text-primary hover:bg-primary/30"
                        >
                          <Zap className="h-3 w-3" />
                          激活
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => startEdit(config)}
                        className="rounded-lg p-2 text-white/40 hover:bg-white/10 hover:text-white"
                      >
                        <Edit className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(config.id)}
                        disabled={config.is_active}
                        className="rounded-lg p-2 text-white/40 hover:bg-red-500/20 hover:text-red-400 disabled:opacity-30"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className="flex items-center gap-1 rounded bg-white/10 px-2 py-1 text-xs text-white/60">
                      <Brain className="h-3 w-3" />
                      {config.model_skim}
                    </span>
                    <span className="flex items-center gap-1 rounded bg-white/10 px-2 py-1 text-xs text-white/60">
                      <Eye className="h-3 w-3" />
                      {config.model_vision || "未设置"}
                    </span>
                    <span className="flex items-center gap-1 rounded bg-white/10 px-2 py-1 text-xs text-white/60">
                      <Layers className="h-3 w-3" />
                      {config.model_embedding}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {configs.length === 0 && !showCreateForm && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-white/5">
              <Settings className="h-8 w-8 text-white/20" />
            </div>
            <p className="text-white/40">暂无 LLM 配置</p>
            <p className="mt-1 text-sm text-white/20">点击上方"新建配置"开始</p>
          </div>
        )}
      </div>
    </div>
  );
}
