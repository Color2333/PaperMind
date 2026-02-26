/**
 * 设置页面 - LLM 配置 + 邮箱配置 + 每日报告
 * @author Bamzc
 * @author Color2333
 */
import { useState, useEffect, useCallback } from "react";
import { useToast } from "@/contexts/ToastContext";
import {
  llmConfigApi,
  emailConfigApi,
  dailyReportApi,
  type EmailConfig,
  type EmailConfigForm,
  type DailyReportConfig,
} from "@/services/api";
import { getErrorMessage } from "@/lib/errorHandler";
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
  Mail,
  Bell,
  TestTube,
  FileText,
  Send,
  Sparkles,
  CheckCircle2,
} from "lucide-react";

// ========== LLM 配置相关 ==========

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

// ========== 邮箱配置相关 ==========

const SMTP_PRESETS: Record<string, { label: string; smtp_server: string; smtp_port: number; smtp_use_tls: boolean }> = {
  gmail: { label: "Gmail", smtp_server: "smtp.gmail.com", smtp_port: 587, smtp_use_tls: true },
  qq: { label: "QQ邮箱", smtp_server: "smtp.qq.com", smtp_port: 587, smtp_use_tls: true },
  "163": { label: "163邮箱", smtp_server: "smtp.163.com", smtp_port: 465, smtp_use_tls: true },
  outlook: { label: "Outlook", smtp_server: "smtp-mail.outlook.com", smtp_port: 587, smtp_use_tls: true },
};

// ========== 主组件 ==========

export default function Settings() {
  const { toast } = useToast();

  // 选项卡状态
  const [activeTab, setActiveTab] = useState<"llm" | "email">("llm");

  // LLM 配置状态
  const [configs, setConfigs] = useState<LLMProviderConfig[]>([]);
  const [activeInfo, setActiveInfo] = useState<ActiveLLMConfig | null>(null);
  const [llmLoading, setLlmLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // 邮箱配置状态
  const [emailConfigs, setEmailConfigs] = useState<EmailConfig[]>([]);
  const [dailyConfig, setDailyConfig] = useState<DailyReportConfig | null>(null);
  const [emailLoading, setEmailLoading] = useState(true);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [testingEmail, setTestingEmail] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [emailForm, setEmailForm] = useState<EmailConfigForm>({
    name: "",
    smtp_server: "",
    smtp_port: 587,
    smtp_use_tls: true,
    sender_email: "",
    sender_name: "PaperMind",
    username: "",
    password: "",
  });

  // ========== LLM 配置方法 ==========

  const loadLlmConfigs = useCallback(async () => {
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
      setLlmLoading(false);
    }
  }, []);

  const handleActivate = async (id: string) => {
    setSubmitting(true);
    try {
      await llmConfigApi.activate(id);
      await loadLlmConfigs();
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeactivateAll = async () => {
    setSubmitting(true);
    try {
      await llmConfigApi.deactivate();
      await loadLlmConfigs();
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除这个配置吗？")) return;
    await llmConfigApi.delete(id);
    await loadLlmConfigs();
  };

  // ========== 邮箱配置方法 ==========

  const loadEmailConfigs = useCallback(async () => {
    try {
      const data = await emailConfigApi.list();
      setEmailConfigs(Array.isArray(data) ? data : []);
    } catch (error) {
      toast("error", getErrorMessage(error));
      setEmailConfigs([]);
    }
  }, [toast]);

  const loadDailyConfig = useCallback(async () => {
    try {
      const data = await dailyReportApi.getConfig();
      setDailyConfig(data);
    } catch (error) {
      toast("error", getErrorMessage(error));
    }
  }, [toast]);

  const handleCreateEmailConfig = async () => {
    try {
      await emailConfigApi.create(emailForm);
      toast("success", "邮箱配置创建成功");
      setEmailModalOpen(false);
      setEmailForm({
        name: "", smtp_server: "", smtp_port: 587, smtp_use_tls: true,
        sender_email: "", sender_name: "PaperMind", username: "", password: "",
      });
      await loadEmailConfigs();
    } catch (error) {
      toast("error", getErrorMessage(error));
    }
  };

  const handleDeleteEmailConfig = async (configId: string) => {
    if (!confirm("确定要删除这个邮箱配置吗？")) return;
    try {
      await emailConfigApi.delete(configId);
      toast("success", "邮箱配置删除成功");
      await loadEmailConfigs();
    } catch (error) {
      toast("error", getErrorMessage(error));
    }
  };

  const handleActivateEmailConfig = async (configId: string) => {
    try {
      await emailConfigApi.activate(configId);
      toast("success", "邮箱配置已激活");
      await loadEmailConfigs();
    } catch (error) {
      toast("error", getErrorMessage(error));
    }
  };

  const handleTestEmailConfig = async (configId: string) => {
    setTestingEmail(configId);
    try {
      await emailConfigApi.test(configId);
      toast("success", "测试邮件发送成功，请检查邮箱");
    } catch (error) {
      toast("error", getErrorMessage(error));
    } finally {
      setTestingEmail(null);
    }
  };

  const handleUpdateDailyConfig = async (updates: Partial<DailyReportConfig>) => {
    try {
      const body: Record<string, unknown> = { ...updates };
      if (updates.recipient_emails) {
        body.recipient_emails = updates.recipient_emails.join(",");
      }
      const data = await dailyReportApi.updateConfig(body);
      if (data.config) {
        setDailyConfig(data.config);
        toast("success", "每日报告配置已更新");
      }
    } catch (error) {
      toast("error", getErrorMessage(error));
      await loadDailyConfig();
    }
  };

  const handleRunDailyReport = async () => {
    if (!confirm("确定要立即执行每日报告工作流吗？这将自动精读论文并发送邮件报告。")) return;
    try {
      await dailyReportApi.runOnce();
      toast("success", "每日报告工作流已启动！");
    } catch (error) {
      toast("error", getErrorMessage(error));
    }
  };

  const applySmtpPreset = (provider: string) => {
    const preset = SMTP_PRESETS[provider];
    if (preset) {
      setEmailForm((prev) => ({
        ...prev,
        smtp_server: preset.smtp_server,
        smtp_port: preset.smtp_port,
        smtp_use_tls: preset.smtp_use_tls,
      }));
    }
  };

  // ========== 初始化 ==========

  useEffect(() => {
    loadLlmConfigs();
  }, [loadLlmConfigs]);

  useEffect(() => {
    loadEmailConfigs();
    loadDailyConfig();
  }, [loadEmailConfigs, loadDailyConfig]);

  if (llmLoading || emailLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-6xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
          系统设置
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          管理 LLM 配置、邮箱服务和自动报告
        </p>
      </div>

      {/* 选项卡导航 */}
      <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab("llm")}
            className={`${
              activeTab === "llm"
                ? "border-primary text-primary"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm transition-colors`}
          >
            <Zap className="h-4 w-4 mr-2 inline" />
            LLM 配置
          </button>
          <button
            onClick={() => setActiveTab("email")}
            className={`${
              activeTab === "email"
                ? "border-primary text-primary"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm transition-colors`}
          >
            <Mail className="h-4 w-4 mr-2 inline" />
            邮箱与报告
          </button>
        </nav>
      </div>

      {/* LLM 配置选项卡 */}
      {activeTab === "llm" && (
        <div className="space-y-6">
          {/* 页头 */}
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">LLM 配置管理</h2>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
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
          <Card>
            <div className="flex items-center gap-3 border-b border-border px-5 py-3.5">
              <Settings2 className="h-4.5 w-4.5 text-gray-500" />
              <span className="text-sm font-medium text-ink">所有配置</span>
            </div>
            <div className="px-5 py-4">
              {configs.length === 0 ? (
                <Empty
                  icon={<Server className="h-12 w-12" />}
                  title="还没有配置任何 LLM 提供者"
                  description="添加配置后可以使用不同的 AI 模型"
                />
              ) : (
                <div className="space-y-3">
                  {configs.map((cfg) => (
                    <div
                      key={cfg.id}
                      className="flex items-center justify-between p-3 rounded-lg bg-gray-50 dark:bg-gray-800/50"
                    >
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          {"name" in cfg && <span className="font-medium text-ink">{cfg.name}</span>}
                          <ProviderBadge provider={cfg.provider} />
                          {activeInfo?.config.id === cfg.id && (
                            <Badge variant="success" className="text-xs">当前生效</Badge>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-tertiary">
                          <span>粗读: {cfg.model_skim}</span>
                          <span>精读: {cfg.model_deep}</span>
                          {cfg.model_vision && <span>视觉: {cfg.model_vision}</span>}
                          <span>嵌入: {cfg.model_embedding}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        {activeInfo?.config.id !== cfg.id && (
                          <Button variant="ghost" size="sm" onClick={() => handleActivate(cfg.id)} disabled={submitting}>
                            <Power className="h-3.5 w-3.5" />
                          </Button>
                        )}
                        <Button variant="ghost" size="sm" onClick={() => handleDelete(cfg.id)}>
                          <Trash2 className="h-3.5 w-3.5 text-red-500" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>

          {/* 添加配置模态框 */}
          <Modal
            isOpen={showAdd}
            onClose={() => setShowAdd(false)}
            title="添加 LLM 配置"
          >
            <LLMConfigForm
              onSubmit={async (data) => {
                await llmConfigApi.create(data);
                setShowAdd(false);
                await loadLlmConfigs();
              }}
              onCancel={() => setShowAdd(false)}
            />
          </Modal>
        </div>
      )}

      {/* 邮箱配置选项卡 */}
      {activeTab === "email" && (
        <div className="space-y-6">
          {/* 每日报告配置 */}
          <Card>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
                  <Bell className="h-5 w-5 text-purple-600 dark:text-purple-400" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                    每日报告配置
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    自动精读论文并发送邮件报告
                  </p>
                </div>
              </div>
              <Button
                onClick={handleRunDailyReport}
                variant="outline"
                size="sm"
              >
                <Sparkles className="h-4 w-4 mr-2" />
                立即执行
              </Button>
            </div>

            {dailyConfig ? (
              <div className="space-y-4">
                {/* 总开关 */}
                <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg">
                  <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-lg ${dailyConfig.enabled ? "bg-green-100 dark:bg-green-900/30" : "bg-gray-100 dark:bg-gray-800"}`}>
                      {dailyConfig.enabled ? (
                        <Power className="h-5 w-5 text-green-600 dark:text-green-400" />
                      ) : (
                        <PowerOff className="h-5 w-5 text-gray-400" />
                      )}
                    </div>
                    <div>
                      <div className="font-medium text-gray-900 dark:text-white">
                        {dailyConfig.enabled ? "每日报告已启用" : "每日报告已禁用"}
                      </div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">
                        {dailyConfig.enabled ? "将自动执行精读和发送报告" : "不会自动执行任何操作"}
                      </div>
                    </div>
                  </div>
                  <Button
                    onClick={() => handleUpdateDailyConfig({ enabled: !dailyConfig.enabled })}
                    variant={dailyConfig.enabled ? "destructive" : "default"}
                    size="sm"
                  >
                    {dailyConfig.enabled ? "禁用" : "启用"}
                  </Button>
                </div>

                {/* 详细配置 */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* 自动精读设置 */}
                  <div className="space-y-3 p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
                    <h4 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                      <FileText className="h-4 w-4" />
                      自动精读设置
                    </h4>
                    <div className="space-y-3">
                      <label className="flex items-center justify-between cursor-pointer">
                        <span className="text-sm text-gray-700 dark:text-gray-300">自动精读新论文</span>
                        <input
                          type="checkbox"
                          checked={dailyConfig.auto_deep_read}
                          onChange={(e) => handleUpdateDailyConfig({ auto_deep_read: e.target.checked })}
                          className="w-4 h-4 text-purple-600 rounded focus:ring-purple-500"
                        />
                      </label>
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-gray-700 dark:text-gray-300">每日精读数量限制</span>
                        <Input
                          type="number"
                          min={1}
                          max={50}
                          value={dailyConfig.deep_read_limit}
                          onChange={(e) => handleUpdateDailyConfig({ deep_read_limit: parseInt(e.target.value) || 10 })}
                          className="w-20"
                        />
                      </div>
                    </div>
                  </div>

                  {/* 邮件发送设置 */}
                  <div className="space-y-3 p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
                    <h4 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                      <Send className="h-4 w-4" />
                      邮件发送设置
                    </h4>
                    <div className="space-y-3">
                      <label className="flex items-center justify-between cursor-pointer">
                        <span className="text-sm text-gray-700 dark:text-gray-300">发送邮件报告</span>
                        <input
                          type="checkbox"
                          checked={dailyConfig.send_email_report}
                          onChange={(e) => handleUpdateDailyConfig({ send_email_report: e.target.checked })}
                          className="w-4 h-4 text-purple-600 rounded focus:ring-purple-500"
                        />
                      </label>
                      <div>
                        <span className="text-sm text-gray-700 dark:text-gray-300 block mb-2">收件人邮箱（逗号分隔）</span>
                        <Input
                          type="text"
                          placeholder="user1@example.com, user2@example.com"
                          value={dailyConfig.recipient_emails.join(", ")}
                          onChange={(e) => handleUpdateDailyConfig({ recipient_emails: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })}
                          className="w-full"
                        />
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-gray-700 dark:text-gray-300">发送时间（UTC）</span>
                        <Input
                          type="number"
                          min={0}
                          max={23}
                          value={dailyConfig.report_time_utc}
                          onChange={(e) => handleUpdateDailyConfig({ report_time_utc: parseInt(e.target.value) || 21 })}
                          className="w-20"
                        />
                      </div>
                    </div>
                  </div>

                  {/* 报告内容设置 */}
                  <div className="space-y-3 p-4 border border-gray-200 dark:border-gray-700 rounded-lg">
                    <h4 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                      <FileText className="h-4 w-4" />
                      报告内容设置
                    </h4>
                    <div className="space-y-3">
                      <label className="flex items-center justify-between cursor-pointer">
                        <span className="text-sm text-gray-700 dark:text-gray-300">包含论文详情</span>
                        <input
                          type="checkbox"
                          checked={dailyConfig.include_paper_details}
                          onChange={(e) => handleUpdateDailyConfig({ include_paper_details: e.target.checked })}
                          className="w-4 h-4 text-purple-600 rounded focus:ring-purple-500"
                        />
                      </label>
                      <label className="flex items-center justify-between cursor-pointer">
                        <span className="text-sm text-gray-700 dark:text-gray-300">包含图谱洞察</span>
                        <input
                          type="checkbox"
                          checked={dailyConfig.include_graph_insights}
                          onChange={(e) => handleUpdateDailyConfig({ include_graph_insights: e.target.checked })}
                          className="w-4 h-4 text-purple-600 rounded focus:ring-purple-500"
                        />
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-gray-500">
                加载配置中...
              </div>
            )}
          </Card>

          {/* 邮箱配置列表 */}
          <Card>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
                  <Mail className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                    邮箱配置
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    配置 SMTP 服务器用于发送邮件报告
                  </p>
                </div>
              </div>
              <Button onClick={() => setEmailModalOpen(true)} size="sm">
                <Plus className="h-4 w-4 mr-2" />
                添加邮箱
              </Button>
            </div>

            {emailConfigs.length === 0 ? (
              <Empty
                icon={<Mail className="h-12 w-12" />}
                title="还没有配置邮箱"
                description="添加邮箱配置后才能发送每日报告"
              />
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {emailConfigs.map((config) => (
                  <div
                    key={config.id}
                    className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 hover:shadow-md transition-shadow"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Mail className="h-5 w-5 text-gray-600 dark:text-gray-400" />
                        <h4 className="font-medium text-gray-900 dark:text-white">
                          {config.name}
                        </h4>
                        {config.is_active && (
                          <Badge variant="success" className="text-xs">已激活</Badge>
                        )}
                      </div>
                      <div className="flex items-center gap-1">
                        {!config.is_active && (
                          <Button
                            onClick={() => handleActivateEmailConfig(config.id)}
                            variant="ghost"
                            size="sm"
                          >
                            <Power className="h-4 w-4" />
                          </Button>
                        )}
                        <Button
                          onClick={() => handleDeleteEmailConfig(config.id)}
                          variant="ghost"
                          size="sm"
                        >
                          <Trash2 className="h-4 w-4 text-red-500" />
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-1 text-sm text-gray-600 dark:text-gray-400">
                      <div>发送方: {config.sender_name} &lt;{config.sender_email}&gt;</div>
                      <div>SMTP: {config.smtp_server}:{config.smtp_port}</div>
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                      <Button
                        onClick={() => handleTestEmailConfig(config.id)}
                        variant="outline"
                        size="sm"
                        disabled={testingEmail === config.id}
                        className="flex-1"
                      >
                        {testingEmail === config.id ? (
                          <>
                            <Spinner size="sm" className="mr-2" />
                            发送中...
                          </>
                        ) : (
                          <>
                            <TestTube className="h-3 w-3 mr-2" />
                            发送测试
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* 添加邮箱配置模态框 */}
          <Modal
            isOpen={emailModalOpen}
            onClose={() => {
              setEmailModalOpen(false);
              setEmailForm({
                name: "",
                smtp_server: "",
                smtp_port: 587,
                smtp_use_tls: true,
                sender_email: "",
                sender_name: "PaperMind",
                username: "",
                password: "",
              });
            }}
            title="添加邮箱配置"
          >
            <div className="space-y-4">
              {/* SMTP 预设 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  快速配置（常见邮箱服务商）
                </label>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(SMTP_PRESETS).map(([key, preset]) => (
                    <Button
                      key={key}
                      onClick={() => applySmtpPreset(key)}
                      variant="outline"
                      size="sm"
                    >
                      {preset.label}
                    </Button>
                  ))}
                </div>
              </div>

              {/* 配置名称 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  配置名称
                </label>
                <Input
                  type="text"
                  placeholder="例如: 工作邮箱"
                  value={emailForm.name}
                  onChange={(e) => setEmailForm({ ...emailForm, name: e.target.value })}
                  required
                />
              </div>

              {/* SMTP 服务器 */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    SMTP 服务器
                  </label>
                  <Input
                    type="text"
                    placeholder="smtp.example.com"
                    value={emailForm.smtp_server}
                    onChange={(e) => setEmailForm({ ...emailForm, smtp_server: e.target.value })}
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    端口
                  </label>
                  <Input
                    type="number"
                    placeholder="587"
                    value={emailForm.smtp_port}
                    onChange={(e) => setEmailForm({ ...emailForm, smtp_port: parseInt(e.target.value) || 587 })}
                    required
                  />
                </div>
              </div>

              {/* TLS */}
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={emailForm.smtp_use_tls}
                  onChange={(e) => setEmailForm({ ...emailForm, smtp_use_tls: e.target.checked })}
                  className="w-4 h-4 text-purple-600 rounded focus:ring-purple-500"
                />
                <span className="text-sm text-gray-700 dark:text-gray-300">使用 TLS 加密</span>
              </label>

              {/* 发件人信息 */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    发件人邮箱
                  </label>
                  <Input
                    type="email"
                    placeholder="your-email@example.com"
                    value={emailForm.sender_email}
                    onChange={(e) => setEmailForm({ ...emailForm, sender_email: e.target.value })}
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    发件人名称
                  </label>
                  <Input
                    type="text"
                    placeholder="PaperMind"
                    value={emailForm.sender_name}
                    onChange={(e) => setEmailForm({ ...emailForm, sender_name: e.target.value })}
                  />
                </div>
              </div>

              {/* 用户名和密码 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  用户名（通常是邮箱地址）
                </label>
                <Input
                  type="text"
                  placeholder="your-email@example.com"
                  value={emailForm.username}
                  onChange={(e) => setEmailForm({ ...emailForm, username: e.target.value })}
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  密码 / 应用专用密码
                </label>
                <div className="relative">
                  <Input
                    type={showPassword ? "text" : "password"}
                    placeholder="•••••••••"
                    value={emailForm.password}
                    onChange={(e) => setEmailForm({ ...emailForm, password: e.target.value })}
                    required
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  注意：对于 Gmail、QQ 等服务，请使用应用专用密码而非账户密码
                </p>
              </div>

              {/* 按钮 */}
              <div className="flex justify-end gap-3 pt-4">
                <Button
                  onClick={() => {
                    setEmailModalOpen(false);
                    setEmailForm({
                      name: "",
                      smtp_server: "",
                      smtp_port: 587,
                      smtp_use_tls: true,
                      sender_email: "",
                      sender_name: "PaperMind",
                      username: "",
                      password: "",
                    });
                  }}
                  variant="outline"
                >
                  取消
                </Button>
                <Button onClick={handleCreateEmailConfig}>
                  创建配置
                </Button>
              </div>
            </div>
          </Modal>
        </div>
      )}
    </div>
  );
}

// ========== LLM 配置表单组件 ==========

interface LLMConfigFormProps {
  onSubmit: (data: LLMProviderCreate) => Promise<void>;
  onCancel: () => void;
}

function LLMConfigForm({ onSubmit, onCancel }: LLMConfigFormProps) {
  const [provider, setProvider] = useState<string>("zhipu");
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelSkim, setModelSkim] = useState("");
  const [modelDeep, setModelDeep] = useState("");
  const [modelVision, setModelVision] = useState("");
  const [modelEmbedding, setModelEmbedding] = useState("");
  const [modelFallback, setModelFallback] = useState("");
  const [name, setName] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSubmit({
      provider,
      api_base: apiBase || undefined,
      api_key: apiKey,
      model_skim: modelSkim,
      model_deep: modelDeep,
      model_vision: modelVision || undefined,
      model_embedding: modelEmbedding,
      model_fallback: modelFallback,
      name: name || undefined,
    });
  };

  const applyPreset = (p: string) => {
    const preset = PROVIDER_PRESETS[p];
    if (preset) {
      setProvider(p);
      setApiBase(preset.base_url);
      const models = preset.models;
      setModelSkim(models.model_skim);
      setModelDeep(models.model_deep);
      setModelVision(models.model_vision || "");
      setModelEmbedding(models.model_embedding);
      setModelFallback(models.model_fallback);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* 提供商选择 */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          AI 提供商
        </label>
        <div className="grid grid-cols-3 gap-2">
          {(["zhipu", "openai", "anthropic"] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => applyPreset(p)}
              className={`px-4 py-2 rounded-lg border text-sm font-medium transition-colors ${
                provider === p
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800"
              }`}
            >
              {PROVIDER_PRESETS[p].label}
            </button>
          ))}
        </div>
      </div>

      {/* API Base URL */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          API Base URL
        </label>
        <Input
          type="text"
          placeholder="https://api.openai.com/v1"
          value={apiBase}
          onChange={(e) => setApiBase(e.target.value)}
          required={provider === "openai"}
        />
      </div>

      {/* API Key */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          API Key
        </label>
        <Input
          type="password"
          placeholder="sk-..."
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          required
        />
      </div>

      {/* 配置名称 */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          配置名称（可选）
        </label>
        <Input
          type="text"
          placeholder="例如: 工作账号"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {/* 模型配置 */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            粗读模型
          </label>
          <Input
            type="text"
            placeholder="gpt-4o-mini"
            value={modelSkim}
            onChange={(e) => setModelSkim(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            精读模型
          </label>
          <Input
            type="text"
            placeholder="gpt-4.1"
            value={modelDeep}
            onChange={(e) => setModelDeep(e.target.value)}
            required
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            视觉模型
          </label>
          <Input
            type="text"
            placeholder="gpt-4o"
            value={modelVision}
            onChange={(e) => setModelVision(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            嵌入模型
          </label>
          <Input
            type="text"
            placeholder="text-embedding-3-small"
            value={modelEmbedding}
            onChange={(e) => setModelEmbedding(e.target.value)}
            required
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          备用模型
        </label>
        <Input
          type="text"
          placeholder="gpt-4o-mini"
          value={modelFallback}
          onChange={(e) => setModelFallback(e.target.value)}
          required
        />
      </div>

      {/* 按钮 */}
      <div className="flex justify-end gap-3 pt-4">
        <Button type="button" onClick={onCancel} variant="outline">
          取消
        </Button>
        <Button type="submit">
          创建配置
        </Button>
      </div>
    </form>
  );
}
