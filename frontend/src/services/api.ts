/**
 * PaperMind - API 服务层
 * @author Bamzc
 */
import type {
  SystemStatus,
  Topic,
  TopicCreate,
  TopicUpdate,
  Paper,
  PipelineRun,
  SkimReport,
  DeepDiveReport,
  AskRequest,
  AskResponse,
  CitationTree,
  TimelineResponse,
  GraphQuality,
  EvolutionResponse,
  SurveyResponse,
  PaperWiki,
  TopicWiki,
  DailyBriefRequest,
  DailyBriefResponse,
  CostMetrics,
  CitationSyncResult,
  IngestResult,
  KeywordSuggestion,
} from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE.replace(/\/+$/, "")}${path}`;
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers as Record<string, string> || {}) },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return resp.json();
}

function get<T>(path: string) {
  return request<T>(path);
}

function post<T>(path: string, body?: unknown) {
  return request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
}

function patch<T>(path: string, body?: unknown) {
  return request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) });
}

function del<T>(path: string) {
  return request<T>(path, { method: "DELETE" });
}

/* ========== 系统 ========== */
export const systemApi = {
  health: () => get<{ status: string; app: string; env: string }>("/health"),
  status: () => get<SystemStatus>("/system/status"),
};

/* ========== 今日速览 ========== */
export interface TodaySummary {
  today_new: number;
  week_new: number;
  total_papers: number;
  recommendations: {
    id: string;
    title: string;
    arxiv_id: string;
    abstract: string;
    similarity: number;
    title_zh?: string;
    keywords?: string[];
    categories?: string[];
  }[];
  hot_keywords: { keyword: string; count: number }[];
}

export const todayApi = {
  summary: () => get<TodaySummary>("/today"),
};

/* ========== 主题 ========== */
export const topicApi = {
  list: (enabledOnly = false) =>
    get<{ items: Topic[] }>(`/topics?enabled_only=${enabledOnly}`),
  create: (data: TopicCreate) => post<Topic>("/topics", data),
  update: (id: string, data: TopicUpdate) => patch<Topic>(`/topics/${id}`, data),
  delete: (id: string) => del<{ deleted: string }>(`/topics/${id}`),
  suggestKeywords: (description: string) =>
    post<{ suggestions: KeywordSuggestion[] }>("/topics/suggest-keywords", { description }),
};

/* ========== 论文 ========== */
export interface FolderStats {
  total: number;
  favorites: number;
  recent_7d: number;
  unclassified: number;
  by_topic: { topic_id: string; topic_name: string; count: number }[];
  by_status: Record<string, number>;
}

export const paperApi = {
  latest: (limit = 50, status?: string, topicId?: string, folder?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.append("status", status);
    if (topicId) params.append("topic_id", topicId);
    if (folder) params.append("folder", folder);
    return get<{ items: Paper[] }>(`/papers/latest?${params}`);
  },
  folderStats: () => get<FolderStats>("/papers/folder-stats"),
  detail: (id: string) => get<Paper>(`/papers/${id}`),
  similar: (id: string, topK = 5) =>
    get<{ paper_id: string; similar_ids: string[] }>(`/papers/${id}/similar?top_k=${topK}`),
  toggleFavorite: (id: string) =>
    patch<{ id: string; favorited: boolean }>(`/papers/${id}/favorite`),
};

/* ========== 摄入 ========== */
export const ingestApi = {
  arxiv: (query: string, maxResults = 20, topicId?: string) => {
    const params = new URLSearchParams({ query, max_results: String(maxResults) });
    if (topicId) params.append("topic_id", topicId);
    return post<IngestResult>(`/ingest/arxiv?${params}`);
  },
};

/* ========== Pipeline ========== */
export const pipelineApi = {
  skim: (paperId: string) => post<SkimReport>(`/pipelines/skim/${paperId}`),
  deep: (paperId: string) => post<DeepDiveReport>(`/pipelines/deep/${paperId}`),
  embed: (paperId: string) => post<{ status: string; paper_id: string }>(`/pipelines/embed/${paperId}`),
  runs: (limit = 30) => get<{ items: PipelineRun[] }>(`/pipelines/runs?limit=${limit}`),
};

/* ========== RAG ========== */
export const ragApi = {
  ask: (data: AskRequest) => post<AskResponse>("/rag/ask", data),
};

/* ========== 引用 ========== */
export const citationApi = {
  syncPaper: (paperId: string, limit = 8) =>
    post<CitationSyncResult>(`/citations/sync/${paperId}?limit=${limit}`),
  syncTopic: (topicId: string, paperLimit = 30, edgeLimit = 6) =>
    post<CitationSyncResult>(`/citations/sync/topic/${topicId}?paper_limit=${paperLimit}&edge_limit_per_paper=${edgeLimit}`),
  syncIncremental: (paperLimit = 40, edgeLimit = 6) =>
    post<CitationSyncResult>(`/citations/sync/incremental?paper_limit=${paperLimit}&edge_limit_per_paper=${edgeLimit}`),
};

/* ========== 图谱 ========== */
export const graphApi = {
  citationTree: (paperId: string, depth = 2) =>
    get<CitationTree>(`/graph/citation-tree/${paperId}?depth=${depth}`),
  timeline: (keyword: string, limit = 100) =>
    get<TimelineResponse>(`/graph/timeline?keyword=${encodeURIComponent(keyword)}&limit=${limit}`),
  quality: (keyword: string, limit = 120) =>
    get<GraphQuality>(`/graph/quality?keyword=${encodeURIComponent(keyword)}&limit=${limit}`),
  evolution: (keyword: string, limit = 160) =>
    get<EvolutionResponse>(`/graph/evolution/weekly?keyword=${encodeURIComponent(keyword)}&limit=${limit}`),
  survey: (keyword: string, limit = 120) =>
    get<SurveyResponse>(`/graph/survey?keyword=${encodeURIComponent(keyword)}&limit=${limit}`),
};

/* ========== Wiki ========== */
export const wikiApi = {
  paper: (paperId: string) => get<PaperWiki>(`/wiki/paper/${paperId}`),
  topic: (keyword: string, limit = 120) =>
    get<TopicWiki>(`/wiki/topic?keyword=${encodeURIComponent(keyword)}&limit=${limit}`),
};

/* ========== 简报 ========== */
export const briefApi = {
  daily: (data?: DailyBriefRequest) => post<DailyBriefResponse>("/brief/daily", data),
};

/* ========== 生成内容历史 ========== */
import type { GeneratedContent, GeneratedContentListItem } from "@/types";

export const generatedApi = {
  list: (type: string, limit = 50) =>
    get<{ items: GeneratedContentListItem[] }>(`/generated/list?type=${type}&limit=${limit}`),
  detail: (id: string) => get<GeneratedContent>(`/generated/${id}`),
  delete: (id: string) => del<{ deleted: string }>(`/generated/${id}`),
};

/* ========== 任务 ========== */
export const jobApi = {
  dailyRun: () => post<Record<string, unknown>>("/jobs/daily/run-once"),
  weeklyGraphRun: () => post<Record<string, unknown>>("/jobs/graph/weekly-run-once"),
};

/* ========== 指标 ========== */
export const metricsApi = {
  costs: (days = 7) => get<CostMetrics>(`/metrics/costs?days=${days}`),
};

/* ========== LLM 配置 ========== */
import type {
  LLMProviderConfig,
  LLMProviderCreate,
  LLMProviderUpdate,
  ActiveLLMConfig,
} from "@/types";

export const llmConfigApi = {
  list: () => get<{ items: LLMProviderConfig[] }>("/settings/llm-providers"),
  create: (data: LLMProviderCreate) => post<LLMProviderConfig>("/settings/llm-providers", data),
  update: (id: string, data: LLMProviderUpdate) => patch<LLMProviderConfig>(`/settings/llm-providers/${id}`, data),
  delete: (id: string) => del<{ deleted: string }>(`/settings/llm-providers/${id}`),
  activate: (id: string) => post<LLMProviderConfig>(`/settings/llm-providers/${id}/activate`),
  deactivate: () => post<{ status: string }>("/settings/llm-providers/deactivate"),
  active: () => get<ActiveLLMConfig>("/settings/llm-providers/active"),
};

/* ========== Agent ========== */
import type { AgentMessage } from "@/types";

export const agentApi = {
  /**
   * 发起 Agent 对话（SSE 流）
   * 返回 Response 对象，调用方自行读取 body stream
   */
  chat: async (messages: AgentMessage[], confirmedActionId?: string): Promise<Response> => {
    const url = `${API_BASE.replace(/\/+$/, "")}/agent/chat`;
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages,
        confirmed_action_id: confirmedActionId || null,
      }),
    });
  },
  confirm: async (actionId: string): Promise<Response> => {
    const url = `${API_BASE.replace(/\/+$/, "")}/agent/confirm/${actionId}`;
    return fetch(url, { method: "POST" });
  },
  reject: async (actionId: string): Promise<Response> => {
    const url = `${API_BASE.replace(/\/+$/, "")}/agent/reject/${actionId}`;
    return fetch(url, { method: "POST" });
  },
};
