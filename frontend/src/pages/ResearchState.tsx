import { useEffect, useState } from "react";
import { BookOpen, Download } from "lucide-react";
import { researchApi, type ClaimItem, type DiffEntry, type EvidenceItem } from "@/services/api";
import { useWorkspace } from "@/contexts/WorkspaceContext";

interface QuestionInfo {
  id: string;
  title: string;
  question: string;
  status: string;
  claim_counts: { by_status: Record<string, number>; by_certainty: Record<string, number> };
}

const STATUS_COLORS: Record<string, string> = {
  confirmed: "bg-green-100 text-green-800",
  pending_verification: "bg-yellow-100 text-yellow-800",
  draft: "bg-hover text-ink-secondary",
  superseded: "bg-orange-100 text-orange-700",
  invalidated: "bg-red-100 text-red-700",
};

const CERTAINTY_LABELS: Record<string, string> = {
  established: "已确立",
  conditional: "条件成立",
  conflicted: "存在冲突",
  insufficient_evidence: "证据不足",
  unknown: "未知",
};

const DIFF_LABELS: Record<string, string> = {
  added: "新增",
  confirmed: "确认",
  revised: "修订",
  invalidated: "失效",
  strengthened: "加强",
  weakened: "削弱",
  conflict: "冲突",
  superseded: "取代",
  retraction: "撤稿",
  context: "背景",
};

export default function ResearchState() {
  const [questionId, setQuestionId] = useState("");
  const [question, setQuestion] = useState<QuestionInfo | null>(null);
  const [claims, setClaims] = useState<ClaimItem[]>([]);
  const [selectedClaim, setSelectedClaim] = useState<ClaimItem | null>(null);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [diff, setDiff] = useState<DiffEntry[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showDiff, setShowDiff] = useState(false);

  const { activeQuestionId } = useWorkspace();

  const loadQuestion = async (qid: string) => {
    setLoading(true);
    setError("");
    try {
      const q = await researchApi.getQuestion(qid);
      setQuestion(q);
      const c = await researchApi.listClaims(qid);
      setClaims(c.items);
      const d = await researchApi.diff(qid);
      setDiff(d.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  // agent→主区跟随：agent 联动的 research question 自动加载
  useEffect(() => {
    if (activeQuestionId) loadQuestion(activeQuestionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeQuestionId]);

  const loadEvidence = async (claimId: string) => {
    const selected = claims.find((c) => c.id === claimId);
    setSelectedClaim(selected ?? null);
    if (!selected || selected.evidence_count === 0) {
      setEvidence([]);
      return;
    }
    try {
      const ev = await researchApi.getClaimEvidence(claimId);
      setEvidence(ev.evidence);
    } catch {
      setEvidence([]);
    }
  };

  const exportMd = async () => {
    if (!questionId) return;
    setError("");
    try {
      const resp = await fetch(
        `${import.meta.env.VITE_API_BASE || "/api"}/research/questions/${questionId}/export?format=markdown`,
        { headers: { Authorization: `Bearer ${localStorage.getItem("auth_token")}` } }
      );
      if (!resp.ok) {
        setError(`导出失败: ${resp.status}`);
        return;
      }
      const md = await resp.text();
      const blob = new Blob([md], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `research_object_${questionId}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页头（与全站 page-hero 一致） */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 rounded-xl p-2.5">
            <BookOpen className="text-primary h-5 w-5" />
          </div>
          <div>
            <h1 className="text-ink text-2xl font-bold">Research State</h1>
            <p className="text-ink-secondary mt-0.5 text-sm">研究问题状态、主张与证据链查询</p>
          </div>
        </div>
      </div>

      {/* 问题 ID 输入 */}
      <div className="card-refined flex gap-3 p-4">
        <input
          className="border-border bg-surface text-ink placeholder:text-ink-placeholder focus:border-primary flex-1 rounded-lg border px-3 py-2 text-sm outline-none transition-colors"
          placeholder="输入 Research Question ID"
          value={questionId}
          onChange={(e) => setQuestionId(e.target.value)}
        />
        <button
          className="gradient-primary shadow-warm-xs text-white px-5 py-2 rounded-lg text-sm font-medium transition-all hover:shadow-warm-md disabled:opacity-50"
          disabled={!questionId.trim() || loading}
          onClick={() => loadQuestion(questionId.trim())}
        >
          {loading ? "加载中..." : "查询"}
        </button>
      </div>

      {error && <div className="text-error bg-error-light rounded-lg px-4 py-3 text-sm">{error}</div>}

      {question && (
        <>
          {/* 问题概览 */}
          <div className="bg-white rounded-lg shadow p-4">
            <h2 className="text-lg font-semibold">{question.title}</h2>
            <p className="text-ink-secondary mt-1">{question.question}</p>
            <div className="flex gap-2 mt-3 flex-wrap">
              {Object.entries(question.claim_counts.by_status).map(([s, n]) => (
                <span
                  key={s}
                  className={`px-2 py-1 rounded text-xs font-medium ${
                    STATUS_COLORS[s] ?? "bg-hover text-ink-secondary"
                  }`}
                >
                  {s}: {n}
                </span>
              ))}
            </div>
          </div>

          {/* Claims 列表 */}
          <div className="bg-white rounded-lg shadow p-4">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold">Claims ({claims.length})</h3>
              <button
                className="text-blue-600 text-sm hover:underline"
                onClick={() => setShowDiff(!showDiff)}
              >
                {showDiff ? "隐藏 Diff" : "显示 Diff"}
              </button>
              <button
                className="text-blue-600 text-sm hover:underline"
                onClick={exportMd}
              >
                导出 Markdown
              </button>
            </div>
            <div className="mt-3 space-y-3">
              {claims.map((c) => (
                <div
                  key={c.id}
                  className={`border rounded p-3 cursor-pointer hover:border-blue-400 ${
                    selectedClaim?.id === c.id ? "border-blue-500 bg-blue-50" : ""
                  }`}
                  onClick={() => loadEvidence(c.id)}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${
                        STATUS_COLORS[c.status] ?? "bg-hover"
                      }`}
                    >
                      {c.status}
                    </span>
                    <span className="text-xs text-ink-tertiary">{c.certainty}</span>
                    <span className="text-xs text-ink-tertiary">origin: {c.origin}</span>
                    <span className="text-xs text-ink-tertiary ml-auto">
                      证据: {c.evidence_count}
                    </span>
                  </div>
                  <p className="mt-2 text-sm">{c.statement}</p>
                  {c.statement_zh && (
                    <p className="text-xs text-ink-tertiary mt-1">{c.statement_zh}</p>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Evidence 面板 */}
          {selectedClaim && evidence.length > 0 && (
            <div className="bg-white rounded-lg shadow p-4">
              <h3 className="font-semibold">
                Evidence for: {selectedClaim.statement.slice(0, 60)}...
              </h3>
              <div className="mt-3 space-y-2">
                {evidence.map((ev) => (
                  <div key={ev.id} className="border rounded p-3 text-sm">
                    <div className="flex gap-2 items-center">
                      <span
                        className={`px-2 py-0.5 rounded text-xs ${
                          ev.stance === "supports"
                            ? "bg-green-100 text-green-700"
                            : ev.stance === "contradicts"
                              ? "bg-red-100 text-red-700"
                              : "bg-hover"
                        }`}
                      >
                        {ev.stance}
                      </span>
                      <span className="text-xs text-ink-tertiary">
                        {ev.source_version.paper.title} v{ev.source_version.version_label}
                      </span>
                    </div>
                    {ev.quote && <p className="mt-1 italic text-ink">"{ev.quote}"</p>}
                    <p className="text-xs text-ink-tertiary mt-1">
                      {JSON.stringify(ev.locator)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Diff 时间线 */}
          {showDiff && (
            <div className="bg-white rounded-lg shadow p-4">
              <h3 className="font-semibold">Research Diff</h3>
              <div className="mt-3 space-y-1">
                {diff.map((d) => (
                  <div key={d.id} className="flex items-center gap-2 text-sm">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${
                        d.diff_kind === "added" || d.diff_kind === "confirmed"
                          ? "bg-green-100 text-green-700"
                          : d.diff_kind === "conflict" || d.diff_kind === "invalidated"
                            ? "bg-red-100 text-red-700"
                            : "bg-blue-100 text-blue-700"
                      }`}
                    >
                      {DIFF_LABELS[d.diff_kind] ?? d.diff_kind}
                    </span>
                    <span className="text-ink-secondary">{d.event}</span>
                    <span className="text-ink-tertiary ml-auto text-xs">
                      {d.occurred_at?.slice(0, 19)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
