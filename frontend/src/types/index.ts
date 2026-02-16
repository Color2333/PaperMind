/**
 * PaperMind - TypeScript 类型定义
 * @author Bamzc
 */

/* ========== 系统 ========== */
export interface HealthResponse {
  status: string;
  app: string;
  env: string;
}

export interface SystemStatus {
  health: HealthResponse;
  counts: {
    topics: number;
    enabled_topics: number;
    papers_latest_200: number;
    runs_latest_50: number;
    failed_runs_latest_50: number;
  };
  latest_run: PipelineRun | null;
}

/* ========== 主题 ========== */
export interface Topic {
  id: string;
  name: string;
  query: string;
  enabled: boolean;
  max_results_per_run: number;
  retry_limit: number;
}

export interface TopicCreate {
  name: string;
  query: string;
  enabled?: boolean;
  max_results_per_run?: number;
  retry_limit?: number;
}

export interface TopicUpdate {
  query?: string;
  enabled?: boolean;
  max_results_per_run?: number;
  retry_limit?: number;
}

/* ========== 论文 ========== */
export type ReadStatus = "unread" | "skimmed" | "deep_read";

export interface Paper {
  id: string;
  title: string;
  arxiv_id: string;
  abstract: string;
  publication_date?: string;
  read_status: ReadStatus;
  pdf_path?: string;
  metadata?: Record<string, unknown>;
  has_embedding?: boolean;
}

/* ========== Pipeline ========== */
export type PipelineStatus = "pending" | "running" | "succeeded" | "failed";

export interface PipelineRun {
  id: string;
  pipeline_name: string;
  paper_id: string;
  status: PipelineStatus;
  decision_note?: string;
  elapsed_ms?: number;
  error_message?: string;
  created_at: string;
}

export interface SkimReport {
  one_liner: string;
  innovations: string[];
  relevance_score: number;
}

export interface DeepDiveReport {
  method_summary: string;
  experiments_summary: string;
  ablation_summary: string;
  reviewer_risks: string[];
}

/* ========== RAG ========== */
export interface AskRequest {
  question: string;
  top_k?: number;
}

export interface AskResponse {
  answer: string;
  cited_paper_ids: string[];
  evidence: Record<string, unknown>[];
}

/* ========== 图谱 ========== */
export interface CitationEdge {
  source: string;
  target: string;
  depth: number;
}

export interface CitationNode {
  id: string;
  title: string;
  year?: number;
}

export interface CitationTree {
  root: string;
  root_title: string;
  ancestors: CitationEdge[];
  descendants: CitationEdge[];
  nodes: CitationNode[];
  edge_count: number;
}

export interface TimelineEntry {
  paper_id: string;
  title: string;
  year: number;
  indegree: number;
  outdegree: number;
  pagerank: number;
  seminal_score: number;
  why_seminal?: string;
}

export interface TimelineResponse {
  keyword: string;
  timeline: TimelineEntry[];
  seminal: TimelineEntry[];
  milestones: TimelineEntry[];
}

export interface GraphQuality {
  keyword: string;
  node_count: number;
  edge_count: number;
  density: number;
  connected_node_ratio: number;
  publication_date_coverage: number;
}

export interface YearBucket {
  year: number;
  paper_count: number;
  avg_seminal_score: number;
  top_titles: string[];
}

export interface EvolutionResponse {
  keyword: string;
  year_buckets: YearBucket[];
  summary: {
    trend_summary: string;
    phase_shift_signals: string;
    next_week_focus: string;
  };
}

export interface SurveyResponse {
  keyword: string;
  summary: {
    overview: string;
    stages: string[];
    reading_list: string[];
    open_questions: string[];
  };
  milestones: TimelineEntry[];
  seminal: TimelineEntry[];
}

/* ========== Wiki ========== */
export interface PaperWiki {
  paper_id: string;
  markdown: string;
  graph: CitationTree;
  content_id?: string;
}

export interface TopicWiki {
  keyword: string;
  markdown: string;
  timeline: TimelineResponse;
  survey: SurveyResponse;
  content_id?: string;
}

/* ========== 简报 ========== */
export interface DailyBriefRequest {
  date?: string;
  recipient?: string;
}

export interface DailyBriefResponse {
  saved_path: string;
  email_sent: boolean;
  content_id?: string;
}

/* ========== 生成内容 ========== */
export interface GeneratedContent {
  id: string;
  content_type: "topic_wiki" | "paper_wiki" | "daily_brief";
  title: string;
  keyword?: string;
  paper_id?: string;
  markdown: string;
  metadata_json?: Record<string, unknown>;
  created_at: string;
}

export interface GeneratedContentListItem {
  id: string;
  content_type: string;
  title: string;
  keyword?: string;
  paper_id?: string;
  created_at: string;
}

/* ========== 指标 ========== */
export interface CostStage {
  stage: string;
  calls: number;
  total_cost_usd: number;
}

export interface CostModel {
  provider: string;
  model: string;
  calls: number;
  total_cost_usd: number;
}

export interface CostMetrics {
  window_days: number;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_cost_usd: number;
  by_stage: CostStage[];
  by_model: CostModel[];
}

/* ========== 引用同步 ========== */
export interface CitationSyncResult {
  paper_id?: string;
  topic_id?: string;
  papers_processed?: number;
  edges_inserted: number;
  processed_papers?: number;
  strategy?: string;
}

/* ========== 摄入 ========== */
export interface IngestResult {
  ingested: number;
}

/* ========== 聊天消息 ========== */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  cited_paper_ids?: string[];
  evidence?: Record<string, unknown>[];
  timestamp: Date;
}

/* ========== LLM 配置 ========== */
export type LLMProvider = "openai" | "anthropic" | "zhipu";

export interface LLMProviderConfig {
  id: string;
  name: string;
  provider: LLMProvider;
  api_key_masked: string;
  api_base_url?: string | null;
  model_skim: string;
  model_deep: string;
  model_vision?: string | null;
  model_embedding: string;
  model_fallback: string;
  is_active: boolean;
}

export interface LLMProviderCreate {
  name: string;
  provider: LLMProvider;
  api_key: string;
  api_base_url?: string;
  model_skim: string;
  model_deep: string;
  model_vision?: string;
  model_embedding: string;
  model_fallback: string;
}

export interface LLMProviderUpdate {
  name?: string;
  provider?: string;
  api_key?: string;
  api_base_url?: string;
  model_skim?: string;
  model_deep?: string;
  model_vision?: string;
  model_embedding?: string;
  model_fallback?: string;
}

export interface ActiveLLMConfig {
  source: "database" | "env";
  config: LLMProviderConfig & { provider?: string };
}
