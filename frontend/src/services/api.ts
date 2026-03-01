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
  ReasoningAnalysisResponse,
  ResearchGapsResponse,
  CitationDetail,
  TopicCitationNetwork,
  LibraryOverview,
  SimilarityMapData,
  BridgesResponse,
  FrontierResponse,
  CocitationResponse,
} from "@/types";

import { resolveApiBase } from "@/lib/tauri";

function getApiBase(): string {
  return resolveApiBase();

/** 获取认证 token */
function getAuthToken(): string | null {
  return localStorage.getItem("auth_token");
}

/** 检查是否已认证 */
export function isAuthenticated(): boolean {
  return !!getAuthToken();
}

/** 清除认证信息 */
export function clearAuth(): void {
  localStorage.removeItem("auth_token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${getApiBase().replace(/\/+$/, "")}${path}`;
  let resp: Response;
  try {
    resp = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(getAuthToken() ? { "Authorization": `Bearer ${getAuthToken()}` } : {}),
        ...(options.headers as Record<string, string> || {}),
      },
      ...options,
    });
  } catch (e) {
    throw new Error("网络连接失败，请检查后端服务是否启动");
  }
  if (!resp.ok) {
    let msg = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      // 兼容后端 AppError 格式: {error, message, detail}
      msg = body.message || body.detail || body.error || msg;
    } catch {
      const text = await resp.text().catch(() => "");
      if (text) msg = text;
    }
    // 401 未认证，清除 token
    if (resp.status === 401) {
      clearAuth();
    }
    throw new Error(msg);
  }
  return resp.json();
}

function get<T>(path: string, opts?: { signal?: AbortSignal }) {
  return request<T>(path, { signal: opts?.signal });
}

function post<T>(path: string, body?: unknown, opts?: { signal?: AbortSignal }) {
  return request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}), signal: opts?.signal });
}

function patch<T>(path: string, body?: unknown, opts?: { signal?: AbortSignal }) {
  return request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}), signal: opts?.signal });
}

function put<T>(path: string, body?: unknown, opts?: { signal?: AbortSignal }) {
  return request<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}), signal: opts?.signal });
}

function del<T>(path: string, opts?: { signal?: AbortSignal }) {
  return request<T>(path, { method: "DELETE", signal: opts?.signal });
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
  fetch: (id: string) =>
    post<TopicFetchResult>(`/topics/${id}/fetch`),
  fetchStatus: (id: string) =>
    get<TopicFetchResult>(`/topics/${id}/fetch-status`),
  suggestKeywords: (description: string) =>
    post<{ suggestions: KeywordSuggestion[] }>("/topics/suggest-keywords", { description }),
};

export interface TopicFetchResult {
  topic_id: string;
  topic_name?: string;
  status: string;
  inserted: number;
  processed?: number;
  attempts?: number;
  error?: string;
  topic?: Topic;
}

/* ========== 论文 ========== */
export interface FolderStats {
  total: number;
  favorites: number;
  recent_7d: number;
  unclassified: number;
  by_topic: { topic_id: string; topic_name: string; count: number }[];
  by_status: Record<string, number>;
  by_date: { date: string; count: number }[];
}

export interface PaperListResponse {
  items: Paper[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export const paperApi = {
  latest: (opts: {
    page?: number;
    pageSize?: number;
    status?: string;
    topicId?: string;
    folder?: string;
    date?: string;
    search?: string;
  } = {}) => {
    const params = new URLSearchParams();
    params.set("page", String(opts.page || 1));
    params.set("page_size", String(opts.pageSize || 20));
    if (opts.status) params.append("status", opts.status);
    if (opts.topicId) params.append("topic_id", opts.topicId);
    if (opts.folder) params.append("folder", opts.folder);
    if (opts.date) params.append("date", opts.date);
    if (opts.search) params.append("search", opts.search);
    return get<PaperListResponse>(`/papers/latest?${params}`);
  },
  folderStats: () => get<FolderStats>("/papers/folder-stats"),
  detail: (id: string) => get<Paper>(`/papers/${id}`),
  similar: (id: string, topK = 5) =>
    get<{ paper_id: string; similar_ids: string[]; items?: { id: string; title: string; arxiv_id?: string; read_status?: string }[] }>(`/papers/${id}/similar?top_k=${topK}`),
  toggleFavorite: (id: string) =>
    patch<{ id: string; favorited: boolean }>(`/papers/${id}/favorite`),
  getFigures: (id: string) =>
    get<{ items: FigureAnalysisItem[] }>(`/papers/${id}/figures`),
  analyzeFigures: (id: string, maxFigures = 10) =>
    post<{ paper_id: string; count: number; items: FigureAnalysisItem[] }>(
      `/papers/${id}/figures/analyze?max_figures=${maxFigures}`,
    ),
  reasoningAnalysis: (id: string) =>
    post<ReasoningAnalysisResponse>(`/papers/${id}/reasoning`),
  pdfUrl: (id: string, arxivId?: string) =>
    arxivId && !arxivId.startsWith("ss-")
      ? `${getApiBase().replace(/\/+$/, "")}/papers/proxy-arxiv-pdf/${arxivId}`  // 通过后端代理访问 arXiv
      : `${getApiBase().replace(/\/+$/, "")}/papers/${id}/pdf`,  // 本地 PDF
  downloadPdf: (id: string) =>
    post<{ status: string; pdf_path: string }>(`/papers/${id}/download-pdf`),
  figureImageUrl: (paperId: string, figureId: string) =>
    `${getApiBase().replace(/\/+$/, "")}/papers/${paperId}/figures/${figureId}/image`,
  aiExplain: (id: string, text: string, action: "explain" | "translate" | "summarize") =>
    post<{ action: string; result: string }>(`/papers/${id}/ai/explain`, { text, action }),
};

export interface FigureAnalysisItem {
  id?: string;
  page_number: number;
  image_index?: number;
  image_type: string;
  caption: string;
  description: string;
  image_url?: string | null;
  has_image?: boolean;
}

/* ========== 摄入 ========== */
export interface ReferenceImportEntry {
  scholar_id: string | null;
  title: string;
  year: number | null;
  venue: string | null;
  citation_count: number | null;
  arxiv_id: string | null;
  abstract: string | null;
  direction?: string;
}

export interface ImportTaskStatus {
  task_id: string;
  status: "running" | "completed" | "failed";
  total: number;
  completed: number;
  imported: number;
  skipped: number;
  failed: number;
  current: string;
  error?: string;
  results: { title: string; status: string; reason?: string; paper_id?: string; source?: string }[];
}

export const ingestApi = {
  arxiv: (query: string, maxResults = 20, topicId?: string, sortBy = "submittedDate") => {
    const params = new URLSearchParams({ query, max_results: String(maxResults), sort_by: sortBy });
    if (topicId) params.append("topic_id", topicId);
    return post<IngestResult>(`/ingest/arxiv?${params}`);
  },
  importReferences: (data: {
    source_paper_id: string;
    source_paper_title: string;
    entries: ReferenceImportEntry[];
    topic_ids?: string[];
  }) => post<{ task_id: string; total: number }>("/ingest/references", data),
  importStatus: (taskId: string) =>
    get<ImportTaskStatus>(`/ingest/references/status/${taskId}`),
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

/* ========== 行动记录 ========== */
export interface CollectionAction {
  id: string;
  action_type: string;
  title: string;
  query: string | null;
  topic_id: string | null;
  paper_count: number;
  created_at: string;
}

export const actionApi = {
  list: (opts: { actionType?: string; topicId?: string; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.actionType) params.set("action_type", opts.actionType);
    if (opts.topicId) params.set("topic_id", opts.topicId);
    if (opts.limit) params.set("limit", String(opts.limit));
    if (opts.offset) params.set("offset", String(opts.offset));
    return get<{ items: CollectionAction[]; total: number }>(`/actions?${params}`);
  },
  detail: (id: string) => get<CollectionAction>(`/actions/${id}`),
  papers: (id: string, limit = 200) =>
    get<{ action_id: string; items: { id: string; title: string; arxiv_id: string; publication_date: string | null; read_status: string }[] }>(
      `/actions/${id}/papers?limit=${limit}`
    ),
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
  researchGaps: (keyword: string, limit = 120) =>
    get<ResearchGapsResponse>(`/graph/research-gaps?keyword=${encodeURIComponent(keyword)}&limit=${limit}`),
  citationDetail: (paperId: string) =>
    get<CitationDetail>(`/graph/citation-detail/${paperId}`),
  topicNetwork: (topicId: string) =>
    get<TopicCitationNetwork>(`/graph/citation-network/topic/${topicId}`),
  topicDeepTrace: (topicId: string) =>
    post<TopicCitationNetwork>(`/graph/citation-network/topic/${topicId}/deep-trace`),
  overview: () => get<LibraryOverview>('/graph/overview'),
  bridges: () => get<BridgesResponse>('/graph/bridges'),
  frontier: (days = 90) => get<FrontierResponse>(`/graph/frontier?days=${days}`),
  cocitationClusters: (minCocite = 2) =>
    get<CocitationResponse>(`/graph/cocitation-clusters?min_cocite=${minCocite}`),
  autoLink: (paperIds: string[]) =>
    post<{ papers: number; edges_linked: number; errors: number }>('/graph/auto-link', paperIds),
  similarityMap: (topicId?: string, limit = 200) =>
    get<SimilarityMapData>(`/graph/similarity-map?topic_id=${topicId || ""}&limit=${limit}`),
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
  batchProcessUnread: (maxPapers = 50) =>
    post<{ processed: number; failed: number; total: number; message: string }>(
      `/jobs/batch-process-unread?max_papers=${maxPapers}`,
    ),
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

/* ========== 写作助手 ========== */
import type { WritingTemplate, WritingResult, WritingRefineMessage, WritingRefineResult } from "@/types";

export const writingApi = {
  templates: () => get<{ items: WritingTemplate[] }>("/writing/templates"),
  process: (action: string, text: string, maxTokens = 4096) =>
    post<WritingResult>("/writing/process", { action, content: text, max_tokens: maxTokens }),
  processMultimodal: (action: string, content: string, imageBase64: string) =>
    post<WritingResult>("/writing/process-multimodal", { action, content, image_base64: imageBase64 }),
  refine: (messages: WritingRefineMessage[], maxTokens = 4096) =>
    post<WritingRefineResult>("/writing/refine", { messages, max_tokens: maxTokens }),
};

/* ========== Agent ========== */
import type { AgentMessage } from "@/types";

async function fetchSSE(url: string, init?: RequestInit): Promise<Response> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`请求失败 (${resp.status}): ${text || resp.statusText}`);
  }
  return resp;
}

export const agentApi = {
  chat: async (messages: AgentMessage[], confirmedActionId?: string): Promise<Response> => {
    const url = `${getApiBase().replace(/\/+$/, "")}/agent/chat`;
    return fetchSSE(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages,
        confirmed_action_id: confirmedActionId || null,
      }),
    });
  },
  confirm: async (actionId: string): Promise<Response> => {
    const url = `${getApiBase().replace(/\/+$/, "")}/agent/confirm/${actionId}`;
    return fetchSSE(url, { method: "POST" });
  },
  reject: async (actionId: string): Promise<Response> => {
    const url = `${getApiBase().replace(/\/+$/, "")}/agent/reject/${actionId}`;
    return fetchSSE(url, { method: "POST" });
  },
};

/* ========== 邮箱配置 ========== */
export interface EmailConfig {
  id: string;
  name: string;
  smtp_server: string;
  smtp_port: number;
  smtp_use_tls: boolean;
  sender_email: string;
  sender_name: string;
  username: string;
  is_active: boolean;
  created_at: string;
}

export interface EmailConfigForm {
  name: string;
  smtp_server: string;
  smtp_port: number;
  smtp_use_tls: boolean;
  sender_email: string;
  sender_name: string;
  username: string;
  password: string;
}

export const emailConfigApi = {
  list: () => get<EmailConfig[]>("/settings/email-configs"),
  create: (data: EmailConfigForm) => post<EmailConfig>("/settings/email-configs", data),
  update: (id: string, data: Partial<EmailConfigForm>) => patch<EmailConfig>(`/settings/email-configs/${id}`, data),
  delete: (id: string) => del<{ deleted: string }>(`/settings/email-configs/${id}`),
  activate: (id: string) => post<EmailConfig>(`/settings/email-configs/${id}/activate`),
  test: (id: string) => post<{ status: string }>(`/settings/email-configs/${id}/test`),
  smtpPresets: () => get<Record<string, { smtp_server: string; smtp_port: number; smtp_use_tls: boolean }>>("/settings/smtp-presets"),
};

/* ========== 每日报告配置 ========== */
export interface DailyReportConfig {
  enabled: boolean;
  auto_deep_read: boolean;
  deep_read_limit: number;
  send_email_report: boolean;
  recipient_emails: string[];
  report_time_utc: number;
  include_paper_details: boolean;
  include_graph_insights: boolean;
}

export const dailyReportApi = {
  getConfig: () => get<DailyReportConfig>("/settings/daily-report-config"),
  updateConfig: (data: Record<string, unknown>) =>
    put<{ config: DailyReportConfig }>("/settings/daily-report-config", data),
  runOnce: () => post<Record<string, unknown>>("/jobs/daily-report/run-once"),
  sendOnly: (recipientEmails?: string[]) =>
    post<Record<string, unknown>>("/jobs/daily-report/send-only", recipientEmails ? { recipient_emails: recipientEmails } : {}),
  generateOnly: (useCache = false) =>
    post<{ html: string }>(`/jobs/daily-report/generate-only?use_cache=${useCache}`),
};

/* ========== 后台任务 ========== */
export interface TaskStatus {
  task_id: string;
  task_type: string;
  title: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  error: string | null;
  created_at: number;
  updated_at: number;
  has_result: boolean;
}

export const tasksApi = {
  active: () => get<{ tasks: ActiveTaskInfo[] }>("/tasks/active"),
  startTopicWiki: (keyword: string, limit = 120) =>
    post<{ task_id: string; status: string }>(
      `/tasks/wiki/topic?keyword=${encodeURIComponent(keyword)}&limit=${limit}`
    ),
  getStatus: (taskId: string) =>
    get<TaskStatus>(`/tasks/${taskId}`),
  getResult: (taskId: string) =>
    get<Record<string, unknown>>(`/tasks/${taskId}/result`),
  list: (taskType?: string, limit = 20) =>
    get<{ tasks: TaskStatus[] }>(
      `/tasks?${taskType ? `task_type=${taskType}&` : ""}limit=${limit}`
    ),
  track: (body: { action: string; task_id: string; task_type?: string; title?: string; total?: number; current?: number; message?: string; success?: boolean; error?: string }) =>
    post<{ ok: boolean }>("/tasks/track", body),
};

export interface ActiveTaskInfo {
  task_id: string;
  task_type: string;
  title: string;
  current: number;
  total: number;
  message: string;
  elapsed_seconds: number;
  progress_pct: number;
  finished: boolean;
  success: boolean;
  error: string | null;
}

/* ========== 认证 ========== */
export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface AuthStatusResponse {
  auth_enabled: boolean;
}

export const authApi = {
  login: (password: string) =>
    post<LoginResponse>("/auth/login", { password }),
  status: () => get<AuthStatusResponse>("/auth/status"),
};
