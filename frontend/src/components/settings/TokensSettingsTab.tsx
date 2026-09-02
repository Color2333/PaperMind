/**
 * 设置 - API 令牌管理（pm CLI / MCP 接入凭证）
 * @author Color2333
 */
import { useState, useCallback, useEffect } from "react";
import { KeyRound, Plus, Trash2, Copy, Check } from "lucide-react";
import { useToast } from "@/contexts/ToastContext";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { Modal } from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";
import { tokenApi } from "@/services/api";
import { getErrorMessage } from "@/lib/errorHandler";
import { cn } from "@/lib/utils";
import type { ApiTokenItem } from "@/types";

/** 服务端返回 naive UTC ISO 字符串，补 Z 后按本地时区展示 */
function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const normalized = /[Z+]/.test(iso) ? iso : `${iso}Z`;
  return new Date(normalized).toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const EXPIRY_OPTIONS = [
  { value: 0, label: "永不过期" },
  { value: 7, label: "7 天" },
  { value: 30, label: "30 天" },
  { value: 90, label: "90 天" },
  { value: 365, label: "1 年" },
];

export function TokensSettingsTab() {
  const { toast } = useToast();
  const [tokens, setTokens] = useState<ApiTokenItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [created, setCreated] = useState<{ name: string; token: string } | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiTokenItem | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTokens(await tokenApi.list());
    } catch {
      toast("error", "加载令牌列表失败");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  const handleRevoke = async () => {
    if (!revokeTarget) return;
    setActionId(revokeTarget.id);
    try {
      await tokenApi.revoke(revokeTarget.id);
      await load();
      toast("success", `已吊销「${revokeTarget.name}」`);
    } catch (err) {
      toast("error", getErrorMessage(err));
    } finally {
      setActionId(null);
      setRevokeTarget(null);
    }
  };

  if (loading)
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner />
      </div>
    );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">API 令牌</h2>
        <p className="mt-1 text-sm text-ink-secondary">
          供 pm CLI、MCP 或其他外部工具访问 PaperMind。令牌明文只在创建时显示一次，请妥善保存。
        </p>
      </div>

      {/* 令牌列表 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-ink">全部令牌</h3>
          <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            新建令牌
          </Button>
        </div>

        {tokens.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-8 text-center">
            <KeyRound className="mx-auto h-8 w-8 text-ink-tertiary" />
            <p className="mt-2 text-sm text-ink-secondary">暂无令牌，点击「新建令牌」创建</p>
          </div>
        ) : (
          <div className="space-y-2">
            {tokens.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between rounded-xl border border-border bg-page p-4 transition-colors hover:border-ink-tertiary"
              >
                <div className="flex items-center gap-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-hover">
                    <KeyRound className="h-5 w-5 text-ink-tertiary" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink">{t.name}</span>
                      {t.scopes.map((s) => (
                        <Badge key={s} variant={s === "write" ? "info" : "default"}>
                          {s === "write" ? "读写" : "只读"}
                        </Badge>
                      ))}
                      {t.created_by === "device" && <Badge variant="success">设备授权</Badge>}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-3 text-xs text-ink-tertiary">
                      <span className="font-mono">{t.token_prefix}…</span>
                      <span>创建于 {formatDate(t.created_at)}</span>
                      <span>最近使用 {formatDate(t.last_used_at)}</span>
                      {t.expires_at && <span>过期于 {formatDate(t.expires_at)}</span>}
                    </div>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setRevokeTarget(t)}
                  disabled={actionId !== null}
                >
                  <Trash2 className="h-3.5 w-3.5 text-error" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>

      <CreateTokenModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={(name, token) => {
          setShowCreate(false);
          setCreated({ name, token });
          load();
        }}
      />

      {/* 创建成功：明文仅此一次 */}
      <Modal open={!!created} onClose={() => setCreated(null)} title="令牌已创建" maxWidth="md">
        {created && (
          <div className="space-y-4">
            <div className="rounded-lg bg-primary/10 px-3 py-2 text-xs text-primary">
              请立即复制保存「{created.name}」的令牌，关闭后将无法再次查看。
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 overflow-x-auto rounded-lg border border-border bg-page px-3 py-2.5 font-mono text-xs whitespace-nowrap text-ink">
                {created.token}
              </code>
              <CopyButton text={created.token} />
            </div>
            <div className="flex justify-end">
              <Button variant="secondary" onClick={() => setCreated(null)}>
                我已保存
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!revokeTarget}
        title="吊销令牌"
        description={`确定吊销「${revokeTarget?.name}」？使用该令牌的 CLI / MCP 将立即失去访问权限。`}
        confirmLabel="吊销"
        variant="danger"
        onConfirm={handleRevoke}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          toast("success", "已复制到剪贴板");
          setTimeout(() => setCopied(false), 2000);
        } catch {
          toast("error", "复制失败，请手动选择复制");
        }
      }}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </Button>
  );
}

function CreateTokenModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (name: string, token: string) => void;
}) {
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [readScope, setReadScope] = useState(true);
  const [writeScope, setWriteScope] = useState(true);
  const [expiryDays, setExpiryDays] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const reset = () => {
    setName("");
    setReadScope(true);
    setWriteScope(true);
    setExpiryDays(0);
    setError("");
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      setError("请输入令牌名称");
      return;
    }
    const scopes = [readScope ? "read" : "", writeScope ? "write" : ""].filter(Boolean);
    if (scopes.length === 0) {
      setError("至少选择一种权限");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const result = await tokenApi.create({
        name: name.trim(),
        scopes,
        expires_in_days: expiryDays > 0 ? expiryDays : null,
      });
      reset();
      onCreated(result.name, result.token);
    } catch (err) {
      toast("error", getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="新建 API 令牌" maxWidth="sm">
      <div className="space-y-4">
        {error && <div className="rounded-lg bg-error-light px-3 py-2 text-xs text-error">{error}</div>}
        <div>
          <label htmlFor="token-name" className="mb-1.5 block text-xs font-medium text-ink-secondary">
            令牌名称
          </label>
          <input
            id="token-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-lg border border-border bg-page px-3 py-2 text-sm text-ink outline-none focus:border-primary"
            placeholder="如：我的 MacBook CLI"
            autoFocus
          />
        </div>
        <div>
          <span className="mb-1.5 block text-xs font-medium text-ink-secondary">权限</span>
          <div className="space-y-2">
            <ScopeCheckbox
              checked={readScope}
              onChange={setReadScope}
              title="只读（read）"
              desc="查询论文、订阅、任务状态等 GET 操作"
            />
            <ScopeCheckbox
              checked={writeScope}
              onChange={setWriteScope}
              title="写入（write）"
              desc="创建订阅、触发抓取/粗读等变更操作"
            />
          </div>
        </div>
        <div>
          <label htmlFor="token-expiry" className="mb-1.5 block text-xs font-medium text-ink-secondary">
            有效期
          </label>
          <select
            id="token-expiry"
            value={expiryDays}
            onChange={(e) => setExpiryDays(Number(e.target.value))}
            className="w-full rounded-lg border border-border bg-page px-3 py-2 text-sm text-ink outline-none focus:border-primary"
          >
            {EXPIRY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex justify-end gap-3 pt-2">
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={submitting} className={cn(submitting && "opacity-70")}>
            {submitting ? <Spinner className="mr-1.5 h-3.5 w-3.5" /> : null}
            创建令牌
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function ScopeCheckbox({
  checked,
  onChange,
  title,
  desc,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  title: string;
  desc: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border bg-page p-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-primary mt-0.5"
      />
      <span>
        <span className="block text-sm text-ink">{title}</span>
        <span className="block text-xs text-ink-tertiary">{desc}</span>
      </span>
    </label>
  );
}
