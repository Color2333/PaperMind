/**
 * 邮箱配置和每日报告设置页面
 * @author Color2333
 */
import { useState, useEffect, useCallback } from "react";
import { useToast } from "@/contexts/ToastContext";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { Empty } from "@/components/ui/Empty";
import { Modal } from "@/components/ui/Modal";
import {
  emailConfigApi,
  dailyReportApi,
  type EmailConfig,
  type EmailConfigForm,
  type DailyReportConfig,
} from "@/services/api";
import { getErrorMessage } from "@/lib/errorHandler";
import {
  Mail,
  Plus,
  Trash2,
  Settings2,
  Eye,
  EyeOff,
  Power,
  PowerOff,
  Send,
  TestTube,
  Clock,
  FileText,
  Bell,
  Sparkles,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";

const SMTP_PRESETS: Record<string, { label: string; smtp_server: string; smtp_port: number; smtp_use_tls: boolean }> = {
  gmail: { label: "Gmail", smtp_server: "smtp.gmail.com", smtp_port: 587, smtp_use_tls: true },
  qq: { label: "QQ邮箱", smtp_server: "smtp.qq.com", smtp_port: 587, smtp_use_tls: true },
  "163": { label: "163邮箱", smtp_server: "smtp.163.com", smtp_port: 465, smtp_use_tls: true },
  outlook: { label: "Outlook", smtp_server: "smtp-mail.outlook.com", smtp_port: 587, smtp_use_tls: true },
};

export default function EmailSettings() {
  const { toast } = useToast();
  const [emailConfigs, setEmailConfigs] = useState<EmailConfig[]>([]);
  const [dailyConfig, setDailyConfig] = useState<DailyReportConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [testingEmail, setTestingEmail] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  // 表单状态
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

  useEffect(() => {
    Promise.all([loadEmailConfigs(), loadDailyConfig()]).finally(() => {
      setLoading(false);
    });
  }, [loadEmailConfigs, loadDailyConfig]);

  const handleCreateEmailConfig = async () => {
    try {
      await emailConfigApi.create(emailForm);
      toast("success", "邮箱配置创建成功");
      setEmailModalOpen(false);
      resetEmailForm();
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
      setDailyConfig(data.config);
      toast("success", "每日报告配置已更新");
    } catch (error) {
      toast("error", getErrorMessage(error));
    }
  };

  const handleRunDailyReport = async () => {
    if (!confirm("确定要立即执行每日报告工作流吗？这将自动精读论文并发送邮件报告。")) return;
    try {
      const data = await dailyReportApi.runOnce();
      toast("success", `每日报告工作流已启动！`);
    } catch (error) {
      toast("error", getErrorMessage(error));
    }
  };

  // 应用 SMTP 预设
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

  // 重置邮箱表单
  const resetEmailForm = () => {
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
    setShowPassword(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-6xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
          邮箱与每日报告设置
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          配置邮箱服务，自动精读论文并发送每日研究报告
        </p>
      </div>

      {/* 每日报告配置 */}
      <Card className="mb-8">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
              <Bell className="h-5 w-5 text-purple-600 dark:text-purple-400" />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
                每日报告配置
              </h2>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                自动精读论文并发送邮件报告
              </p>
            </div>
          </div>
          <Button
            onClick={handleRunDailyReport}
            variant="secondary"
            size="sm"
          >
            <Sparkles className="h-4 w-4 mr-2" />
            立即执行
          </Button>
        </div>

        {dailyConfig && (
          <div className="space-y-6">
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
                variant={dailyConfig.enabled ? "danger" : "primary"}
                size="sm"
              >
                {dailyConfig.enabled ? "禁用" : "启用"}
              </Button>
            </div>

            {/* 详细配置 */}
            {dailyConfig.enabled && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* 自动精读设置 */}
                <div className="space-y-4">
                  <h3 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    自动精读设置
                  </h3>
                  <div className="space-y-3">
                    <label className="flex items-center justify-between">
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
                <div className="space-y-4">
                  <h3 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                    <Send className="h-4 w-4" />
                    邮件发送设置
                  </h3>
                  <div className="space-y-3">
                    <label className="flex items-center justify-between">
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
                        onChange={(e) => handleUpdateDailyConfig({ recipient_emails: e.target.value.split(",").map(e => e.trim()).filter(Boolean) })}
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
                <div className="space-y-4">
                  <h3 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    报告内容设置
                  </h3>
                  <div className="space-y-3">
                    <label className="flex items-center justify-between">
                      <span className="text-sm text-gray-700 dark:text-gray-300">包含论文详情</span>
                      <input
                        type="checkbox"
                        checked={dailyConfig.include_paper_details}
                        onChange={(e) => handleUpdateDailyConfig({ include_paper_details: e.target.checked })}
                        className="w-4 h-4 text-purple-600 rounded focus:ring-purple-500"
                      />
                    </label>
                    <label className="flex items-center justify-between">
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
            )}
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
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
                邮箱配置
              </h2>
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
                    <h3 className="font-medium text-gray-900 dark:text-white">
                      {config.name}
                    </h3>
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
                    variant="secondary"
                    size="sm"
                    disabled={testingEmail === config.id}
                    className="flex-1"
                  >
                    {testingEmail === config.id ? (
                      <>
                        <Spinner className="mr-2 h-4 w-4" />
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
        open={emailModalOpen}
        onClose={() => {
          setEmailModalOpen(false);
          resetEmailForm();
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
                  variant="secondary"
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
                placeholder="••••••••"
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
                resetEmailForm();
              }}
              variant="secondary"
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
  );
}
