/**
 * Topics - 主题管理
 * 覆盖 API: GET/POST/PATCH/DELETE /topics
 * @author Bamzc
 */
import { useEffect, useState, useCallback } from "react";
import { Card, CardHeader, Button, Badge, Input, Modal, Empty, Spinner } from "@/components/ui";
import { topicApi } from "@/services/api";
import type { Topic, TopicCreate } from "@/types";
import {
  Plus,
  Pencil,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Search,
  RefreshCw,
  Tags,
} from "lucide-react";

export default function Topics() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTopic, setEditingTopic] = useState<Topic | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const loadTopics = useCallback(async () => {
    setLoading(true);
    try {
      const res = await topicApi.list();
      setTopics(res.items);
    } catch {
      /* 静默 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTopics();
  }, [loadTopics]);

  const handleToggle = async (topic: Topic) => {
    setActionLoading(topic.id);
    try {
      await topicApi.update(topic.id, { enabled: !topic.enabled });
      await loadTopics();
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (topic: Topic) => {
    if (!confirm(`确认删除主题「${topic.name}」？`)) return;
    setActionLoading(topic.id);
    try {
      await topicApi.delete(topic.id);
      await loadTopics();
    } finally {
      setActionLoading(null);
    }
  };

  const openEdit = (topic: Topic) => {
    setEditingTopic(topic);
    setModalOpen(true);
  };

  const openCreate = () => {
    setEditingTopic(null);
    setModalOpen(true);
  };

  const filtered = topics.filter(
    (t) =>
      t.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.query.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink">Topics</h1>
          <p className="mt-1 text-sm text-ink-secondary">
            管理订阅的研究主题，自动从 ArXiv 抓取论文
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={loadTopics}
          >
            刷新
          </Button>
          <Button
            size="sm"
            icon={<Plus className="h-3.5 w-3.5" />}
            onClick={openCreate}
          >
            新建主题
          </Button>
        </div>
      </div>

      {/* 搜索 */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-tertiary" />
        <input
          type="text"
          placeholder="搜索主题..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="h-10 w-full rounded-lg border border-border bg-surface pl-9 pr-4 text-sm text-ink placeholder:text-ink-placeholder focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
        />
      </div>

      {loading ? (
        <Spinner text="加载主题..." />
      ) : filtered.length === 0 ? (
        <Empty
          icon={<Tags className="h-12 w-12" />}
          title="暂无主题"
          description="创建一个研究主题开始追踪论文"
          action={
            <Button size="sm" onClick={openCreate}>
              新建主题
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {filtered.map((topic) => (
            <Card key={topic.id} className="transition-shadow hover:shadow-md">
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate text-base font-semibold text-ink">
                      {topic.name}
                    </h3>
                    <Badge variant={topic.enabled ? "success" : "default"}>
                      {topic.enabled ? "启用" : "禁用"}
                    </Badge>
                  </div>
                  <p className="mt-1.5 text-sm text-ink-secondary">{topic.query}</p>
                  <div className="mt-3 flex gap-4 text-xs text-ink-tertiary">
                    <span>每次抓取: {topic.max_results_per_run} 篇</span>
                    <span>重试上限: {topic.retry_limit} 次</span>
                  </div>
                </div>
              </div>
              <div className="mt-4 flex gap-2 border-t border-border-light pt-3">
                <Button
                  variant="ghost"
                  size="sm"
                  icon={
                    topic.enabled ? (
                      <ToggleRight className="h-3.5 w-3.5" />
                    ) : (
                      <ToggleLeft className="h-3.5 w-3.5" />
                    )
                  }
                  onClick={() => handleToggle(topic)}
                  loading={actionLoading === topic.id}
                >
                  {topic.enabled ? "禁用" : "启用"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Pencil className="h-3.5 w-3.5" />}
                  onClick={() => openEdit(topic)}
                >
                  编辑
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 className="h-3.5 w-3.5 text-error" />}
                  onClick={() => handleDelete(topic)}
                >
                  删除
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* 创建/编辑弹窗 */}
      <TopicModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        topic={editingTopic}
        onSaved={loadTopics}
      />
    </div>
  );
}

function TopicModal({
  open,
  onClose,
  topic,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  topic: Topic | null;
  onSaved: () => void;
}) {
  const isEdit = !!topic;
  const [form, setForm] = useState<TopicCreate>({
    name: "",
    query: "",
    enabled: true,
    max_results_per_run: 20,
    retry_limit: 2,
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (topic) {
      setForm({
        name: topic.name,
        query: topic.query,
        enabled: topic.enabled,
        max_results_per_run: topic.max_results_per_run,
        retry_limit: topic.retry_limit,
      });
    } else {
      setForm({ name: "", query: "", enabled: true, max_results_per_run: 20, retry_limit: 2 });
    }
  }, [topic, open]);

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.query.trim()) return;
    setSaving(true);
    try {
      if (isEdit) {
        await topicApi.update(topic!.id, {
          query: form.query,
          enabled: form.enabled,
          max_results_per_run: form.max_results_per_run,
          retry_limit: form.retry_limit,
        });
      } else {
        await topicApi.create(form);
      }
      onSaved();
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? "编辑主题" : "新建主题"}>
      <div className="space-y-4">
        <Input
          label="主题名称"
          placeholder="例如: Large Language Models"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          disabled={isEdit}
        />
        <Input
          label="搜索查询"
          placeholder="例如: LLM OR large language model"
          value={form.query}
          onChange={(e) => setForm({ ...form, query: e.target.value })}
        />
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="每次抓取数量"
            type="number"
            value={form.max_results_per_run}
            onChange={(e) =>
              setForm({ ...form, max_results_per_run: parseInt(e.target.value) || 20 })
            }
          />
          <Input
            label="重试上限"
            type="number"
            value={form.retry_limit}
            onChange={(e) =>
              setForm({ ...form, retry_limit: parseInt(e.target.value) || 2 })
            }
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
          />
          <span className="text-ink">启用自动抓取</span>
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={handleSubmit} loading={saving}>
            {isEdit ? "保存" : "创建"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
