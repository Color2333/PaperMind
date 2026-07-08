import { useState, useCallback, useEffect } from "react";
import { Mail, Plus, Trash2, Pencil, Power, Send, Activity, Play } from "lucide-react";
import { useToast } from "@/contexts/ToastContext";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { emailConfigApi, dailyReportApi } from "@/services/api";
import { getErrorMessage } from "@/lib/errorHandler";
import { cn } from "@/lib/utils";
import type { EmailConfig, EmailConfigForm, DailyReportConfig } from "@/types";

export function EmailSettingsTab() {
  const { toast } = useToast();
  const [emailConfigs, setEmailConfigs] = useState<EmailConfig[]>([]);
  const [dailyReport, setDailyReport] = useState<DailyReportConfig | null>(null);
  const [localConfig, setLocalConfig] = useState<DailyReportConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [showAddEmail, setShowAddEmail] = useState(false);
  const [editEmailConfig, setEditEmailConfig] = useState<EmailConfig | null>(null);
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

  const handleUpdateDailyReport = async (updates: Partial<DailyReportConfig>) => {
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

  const handleInputChange = (field: string, value: string | number | boolean) => {
    setLocalConfig((prev: DailyReportConfig | null) => ({ ...(prev as unknown as Record<string, unknown> | null), [field]: value }) as unknown as DailyReportConfig);
  };

  const handleInputBlur = (field: string) => {
    if (localConfig && (localConfig as unknown as Record<string, unknown>)[field] !== (dailyReport as unknown as Record<string, unknown>)[field]) {
      handleUpdateDailyReport({ [field]: (localConfig as unknown as Record<string, unknown>)[field] } as Partial<DailyReportConfig>);
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
  const [form, setForm] = useState<EmailConfigForm>({
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

  const setField = (key: string, value: string | number | boolean) => setForm((prev) => ({ ...prev, [key]: value }));

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

function EditEmailConfigModal({ config, onSaved, onCancel }: { config: EmailConfig; onSaved: () => void; onCancel: () => void }) {
  const [form, setForm] = useState<EmailConfigForm>({
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

  const setField = (key: string, value: string | number | boolean) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = async () => {
    setSubmitting(true);
    setError("");
    try {
      const payload: Partial<EmailConfigForm> = { ...form };
      if (!form.password) delete payload.password;
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
