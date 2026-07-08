import { useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { Button, Input, Modal } from "@/components/ui";
import { useToast } from "@/contexts/ToastContext";
import { ingestApi, topicApi } from "@/services/api";
import type { Topic } from "@/types";

/* ========== 摄入弹窗 ========== */
function IngestModal({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [query, setQuery] = useState("");
  const [maxResults, setMaxResults] = useState(20);
  const [topicId, setTopicId] = useState("");
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<number | null>(null);

  const { toast } = useToast();
  useEffect(() => {
    if (open) {
      topicApi
        .list()
        .then((r) => setTopics(r.items))
        .catch(() => {
          toast("error", "加载主题列表失败");
        });
      setResult(null);
    }
  }, [open, toast]);

  const handleIngest = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const res = await ingestApi.arxiv(query, maxResults, topicId || undefined);
      setResult(res.ingested);
      onDone();
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="ArXiv 论文摄入">
      <div className="space-y-4">
        <Input
          label="搜索查询"
          placeholder="例如: transformer attention mechanism"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="最大数量"
            type="number"
            value={maxResults}
            onChange={(e) => setMaxResults(parseInt(e.target.value) || 20)}
          />
          <div className="space-y-1.5">
            <label className="text-ink block text-sm font-medium">关联主题</label>
            <select
              value={topicId}
              onChange={(e) => setTopicId(e.target.value)}
              className="border-border bg-surface text-ink focus:border-primary h-10 w-full rounded-lg border px-3 text-sm focus:outline-none"
            >
              <option value="">不关联</option>
              {topics.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        {result !== null && (
          <div className="bg-success-light text-success rounded-xl p-3 text-sm font-medium">
            <CheckCircle2 className="mr-2 inline h-4 w-4" />
            成功摄入 {result} 篇论文
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            关闭
          </Button>
          <Button onClick={handleIngest} loading={loading}>
            开始摄入
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default IngestModal;
