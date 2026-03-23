import { useState, useEffect, useCallback } from 'react';
import { ArrowRight, BookOpen, Zap, Brain, Loader2 } from 'lucide-react';
import { DeltaCard } from '@/components/SensemakingCanvas/DeltaCard';

interface Act1Data {
  summary: string;
  key_findings: string[];
}

interface Act2Data {
  conflicts: string[];
  questions: string[];
}

interface Act3Data {
  before: string;
  after: string;
  delta: string;
  one_change: string;
}

interface SessionData {
  id: string;
  act1_comprehension: { comprehension?: Act1Data } | null;
  act2_collision: { collision?: Act2Data } | null;
  act3_reconstruction: Act3Data | null;
  status: string;
}

interface CanvasPanelProps {
  paperId: string;
  paperTitle: string;
}

type Stage = 'list' | 'act1' | 'act2' | 'act3' | 'result';

export function CanvasPanel({ paperId, paperTitle }: CanvasPanelProps) {
  const [stage, setStage] = useState<Stage>('list');
  const [sessions, setSessions] = useState<SessionData[]>([]);
  const [currentSession, setCurrentSession] = useState<SessionData | null>(null);
  const [loading, setLoading] = useState(false);

  const [act1Form, setAct1Form] = useState<Act1Data>({ summary: '', key_findings: [''] });
  const [act2Form, setAct2Form] = useState<Act2Data>({ conflicts: [''], questions: [''] });
  const [act3Form, setAct3Form] = useState<Act3Data>({ before: '', after: '', delta: '', one_change: '' });

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
      const res = await fetch(`${base}/sensemaking/sessions?paper_id=${paperId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setSessions(data);
        if (data.length > 0) {
          setCurrentSession(data[data.length - 1]);
        }
      }
    } catch (err) {
      console.error('Failed to load sessions:', err);
    } finally {
      setLoading(false);
    }
  }, [paperId]);

  const startNewSession = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
      const schemaRes = await fetch(`${base}/sensemaking/schemas`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!schemaRes.ok) return;
      const schemas = await schemaRes.json();
      const defaultSchema = schemas.find((s: { user_id: string }) => s.user_id === 'default') || schemas[0];
      if (!defaultSchema) return;

      const createRes = await fetch(`${base}/sensemaking/sessions`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ paper_id: paperId, user_schema_id: defaultSchema.id }),
      });
      if (createRes.ok) {
        const session = await createRes.json();
        setCurrentSession(session);
        setStage('act1');
      }
    } catch (err) {
      console.error('Failed to start session:', err);
    } finally {
      setLoading(false);
    }
  };

  const submitAct1 = async () => {
    if (!currentSession) return;
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
      const res = await fetch(`${base}/sensemaking/sessions/${currentSession.id}/act1`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ comprehension: act1Form }),
      });
      if (res.ok) {
        const updated = await res.json();
        setCurrentSession(updated);
        setStage('act2');
      }
    } catch (err) {
      console.error('Failed to submit act1:', err);
    } finally {
      setLoading(false);
    }
  };

  const submitAct2 = async () => {
    if (!currentSession) return;
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
      const res = await fetch(`${base}/sensemaking/sessions/${currentSession.id}/act2`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ collision: act2Form }),
      });
      if (res.ok) {
        const updated = await res.json();
        setCurrentSession(updated);
        setStage('act3');
      }
    } catch (err) {
      console.error('Failed to submit act2:', err);
    } finally {
      setLoading(false);
    }
  };

  const submitAct3 = async () => {
    if (!currentSession) return;
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
      const res = await fetch(`${base}/sensemaking/sessions/${currentSession.id}/act3`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(act3Form),
      });
      if (res.ok) {
        const updated = await res.json();
        setCurrentSession(updated);
        setStage('result');
      }
    } catch (err) {
      console.error('Failed to submit act3:', err);
    } finally {
      setLoading(false);
    }
  };

  const renderList = () => (
    <div className="flex h-full flex-col p-4">
      <div className="mb-4 text-center">
        <h3 className="text-lg font-medium text-white/90">{paperTitle}</h3>
        <p className="text-xs text-white/40">认知重构工作台</p>
      </div>

      {loading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      ) : sessions.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-4">
          <Brain className="h-12 w-12 text-white/10" />
          <p className="text-sm text-white/60">开始你的认知重构之旅</p>
          <button
            type="button"
            onClick={startNewSession}
            className="rounded-full bg-primary/20 px-6 py-2 text-sm text-primary hover:bg-primary/30"
          >
            开始阅读理解
          </button>
        </div>
      ) : (
        <div className="flex flex-1 flex-col gap-3 overflow-auto">
          <p className="text-xs text-white/40">历史会话 ({sessions.length})</p>
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                setCurrentSession(s);
                if (s.act3_reconstruction) {
                  setAct3Form(s.act3_reconstruction);
                  setStage('result');
                } else if (s.act2_collision) {
                  setStage('act3');
                } else if (s.act1_comprehension) {
                  setStage('act2');
                } else {
                  setStage('act1');
                }
              }}
              className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-3 text-left hover:bg-white/10"
            >
              <div>
                <p className="text-sm text-white/80">{paperTitle}</p>
                <p className="text-xs text-white/40">
                  {s.status === 'completed' ? '已完成' : '进行中'}
                </p>
              </div>
              <ArrowRight className="h-4 w-4 text-white/30" />
            </button>
          ))}
          <button
            type="button"
            onClick={startNewSession}
            className="mt-2 flex items-center justify-center gap-2 rounded-lg border border-dashed border-white/20 py-2 text-sm text-white/40 hover:border-primary/40 hover:text-primary"
          >
            + 新建会话
          </button>
        </div>
      )}
    </div>
  );

  const renderAct1 = () => (
    <div className="flex h-full flex-col p-4">
      <div className="mb-4 flex items-center gap-2">
        <button type="button" onClick={() => setStage('list')} className="text-white/40 hover:text-white">
          ← 返回
        </button>
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-primary" />
          <span className="text-sm text-primary">Act 1: 理解</span>
        </div>
      </div>

      <div className="mb-3">
        <p className="mb-1 text-xs text-white/60">论文摘要</p>
        <textarea
          value={act1Form.summary}
          onChange={(e) => setAct1Form({ ...act1Form, summary: e.target.value })}
          placeholder="用自己的话总结这篇论文的核心内容..."
          className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-white/80 placeholder-white/30 outline-none focus:border-primary/50"
          rows={4}
        />
      </div>

      <div className="mb-4 flex-1 overflow-auto">
        <p className="mb-2 text-xs text-white/60">关键发现 (每行一个)</p>
        {act1Form.key_findings.map((finding, idx) => (
          <input
            key={idx} // eslint-disable-line react/no-array-index-key
            type="text"
            value={finding}
            onChange={(e) => {
              const newFindings = [...act1Form.key_findings];
              newFindings[idx] = e.target.value;
              setAct1Form({ ...act1Form, key_findings: newFindings });
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && idx === act1Form.key_findings.length - 1) {
                setAct1Form({ ...act1Form, key_findings: [...act1Form.key_findings, ''] });
              }
            }}
            placeholder={`发现 ${idx + 1}...`}
            className="mb-2 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/80 placeholder-white/30 outline-none focus:border-primary/50"
          />
        ))}
      </div>

      <button
        type="button"
        onClick={submitAct1}
        disabled={loading || !act1Form.summary.trim()}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary/20 py-2 text-sm text-primary hover:bg-primary/30 disabled:opacity-50"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        进入 Act 2 →
      </button>
    </div>
  );

  const renderAct2 = () => (
    <div className="flex h-full flex-col p-4">
      <div className="mb-4 flex items-center gap-2">
        <button type="button" onClick={() => setStage('act1')} className="text-white/40 hover:text-white">
          ← 返回
        </button>
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-amber-400" />
          <span className="text-sm text-amber-400">Act 2: 碰撞</span>
        </div>
      </div>

      <div className="mb-3">
        <p className="mb-1 text-xs text-white/60">与已有知识的冲突</p>
        <textarea
          value={act2Form.conflicts.join('\n')}
          onChange={(e) => setAct2Form({ ...act2Form, conflicts: e.target.value.split('\n').filter(Boolean) })}
          placeholder="这篇论文的观点与你已知的有哪些冲突..."
          className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-white/80 placeholder-white/30 outline-none focus:border-amber-500/50"
          rows={4}
        />
      </div>

      <div className="mb-4 flex-1 overflow-auto">
        <p className="mb-1 text-xs text-white/60">产生的疑问</p>
        <textarea
          value={act2Form.questions.join('\n')}
          onChange={(e) => setAct2Form({ ...act2Form, questions: e.target.value.split('\n').filter(Boolean) })}
          placeholder="阅读后你还有哪些疑问..."
          className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-white/80 placeholder-white/30 outline-none focus:border-amber-500/50"
          rows={3}
        />
      </div>

      <button
        type="button"
        onClick={submitAct2}
        disabled={loading}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-500/20 py-2 text-sm text-amber-400 hover:bg-amber-500/30 disabled:opacity-50"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        进入 Act 3 →
      </button>
    </div>
  );

  const renderAct3 = () => (
    <div className="flex h-full flex-col p-4">
      <div className="mb-4 flex items-center gap-2">
        <button type="button" onClick={() => setStage('act2')} className="text-white/40 hover:text-white">
          ← 返回
        </button>
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-emerald-400" />
          <span className="text-sm text-emerald-400">Act 3: 重构</span>
        </div>
      </div>

      <div className="mb-3">
        <p className="mb-1 text-xs text-white/60">阅读前的理解</p>
        <textarea
          value={act3Form.before}
          onChange={(e) => setAct3Form({ ...act3Form, before: e.target.value })}
          placeholder="在读这篇论文之前，你对这个主题的理解是..."
          className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-white/80 placeholder-white/30 outline-none focus:border-emerald-500/50"
          rows={3}
        />
      </div>

      <div className="mb-3">
        <p className="mb-1 text-xs text-white/60">阅读后的理解</p>
        <textarea
          value={act3Form.after}
          onChange={(e) => setAct3Form({ ...act3Form, after: e.target.value })}
          placeholder="读完这篇论文后，你的理解是..."
          className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-white/80 placeholder-white/30 outline-none focus:border-emerald-500/50"
          rows={3}
        />
      </div>

      <div className="mb-3">
        <p className="mb-1 text-xs text-white/60">认知变化</p>
        <textarea
          value={act3Form.delta}
          onChange={(e) => setAct3Form({ ...act3Form, delta: e.target.value })}
          placeholder="从阅读前到阅读后，你的认知有哪些变化..."
          className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-sm text-white/80 placeholder-white/30 outline-none focus:border-emerald-500/50"
          rows={2}
        />
      </div>

      <div className="mb-4">
        <p className="mb-1 text-xs text-emerald-400">我的承诺</p>
        <textarea
          value={act3Form.one_change}
          onChange={(e) => setAct3Form({ ...act3Form, one_change: e.target.value })}
          placeholder="读完这篇论文后，你决定做出什么改变..."
          className="w-full rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm text-emerald-300 placeholder-emerald-400/30 outline-none focus:border-emerald-500/50"
          rows={2}
        />
      </div>

      <button
        type="button"
        onClick={submitAct3}
        disabled={loading || !act3Form.before.trim() || !act3Form.after.trim()}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-500/20 py-2 text-sm text-emerald-400 hover:bg-emerald-500/30 disabled:opacity-50"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        完成重构
      </button>
    </div>
  );

  const renderResult = () => (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-white/80">认知重构结果</h3>
        <button
          type="button"
          onClick={() => setStage('list')}
          className="text-xs text-white/40 hover:text-white"
        >
          返回列表
        </button>
      </div>

      {currentSession?.act1_comprehension?.comprehension && (
        <DeltaCard
          label="Act 1: 理解"
          content={currentSession.act1_comprehension.comprehension.summary}
          variant="before"
        />
      )}

      {currentSession?.act2_collision?.collision && (
        <DeltaCard
          label="Act 2: 碰撞"
          content={currentSession.act2_collision.collision.conflicts?.join(' • ') || ''}
          variant="delta"
        />
      )}

      {act3Form.before && <DeltaCard label="阅读前" content={act3Form.before} variant="before" />}

      <div className="flex items-center justify-center">
        <ArrowRight className="h-5 w-5 text-primary" />
      </div>

      {act3Form.after && <DeltaCard label="阅读后" content={act3Form.after} variant="after" />}

      {act3Form.delta && <DeltaCard label="认知变化" content={act3Form.delta} variant="delta" />}

      {act3Form.one_change && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <p className="mb-2 text-xs font-medium text-emerald-400">我的承诺</p>
          <p className="text-sm text-emerald-300">{act3Form.one_change}</p>
        </div>
      )}
    </div>
  );

  switch (stage) {
    case 'list':
      return renderList();
    case 'act1':
      return renderAct1();
    case 'act2':
      return renderAct2();
    case 'act3':
      return renderAct3();
    case 'result':
      return renderResult();
    default:
      return renderList();
  }
}
