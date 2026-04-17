/**
 * PaperMind - TypeScript 类型定义
 * @author Color2333
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
export type ScheduleFrequency = "daily" | "twice_daily" | "weekdays" | "weekly";

export interface Topic {
  id: string;
  name: string;
  query: string;
  enabled: boolean;
  max_results_per_run: number;
  retry_limit: number;
  schedule_frequency: ScheduleFrequency;
  schedule_time_utc: number;
  enable_date_filter: boolean;
  date_filter_days: number;
  paper_count?: number;
  last_run_at?: string | null;
  last_run_count?: number | null;
}

export interface TopicCreate {
  name: string;
  query: string;
  enabled?: boolean;
  max_results_per_run?: number;
  retry_limit?: number;
  schedule_frequency?: ScheduleFrequency;
  schedule_time_utc?: number;
  enable_date_filter?: boolean;
  date_filter_days?: number;
}

export interface TopicUpdate {
  query?: string;
  enabled?: boolean;
  max_results_per_run?: number;
  retry_limit?: number;
  schedule_frequency?: ScheduleFrequency;
  schedule_time_utc?: number;
  enable_date_filter?: boolean;
  date_filter_days?: number;
}

export interface KeywordSuggestion {
  name: string;
  query: string;
  reason: string;
}

export interface TopicStats {
  topic_id: string;
  topic_name: string;
  paper_count: number;
  total_citations: number;
  recent_30d: number;
  status_dist: {
    unread: number;
    skimmed: number;
    deep_read: number;
  };
}

export interface TopicStatsResponse {
  topics: TopicStats[];
}

export interface PaperDistributionStats {
  by_year: { year: string; count: number }[];
  by_source: { source: string; raw_source: string; count: number }[];
}

export interface PaperDistributionResponse {
  by_year: { year: string; count: number }[];
  by_source: { source: string; raw_source: string; count: number }[];
  by_status: { status: string; raw_status: string; count: number }[];
  by_month: { month: string; count: number }[];
  by_venue: { venue: string; count: number }[];
  by_action_source: { source: string; raw_source: string; count: number }[];
}

/* ========== 抓取任务 ========== */
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

/* ========== 标签 ========== */
export interface Tag {
  id: string;
  name: string;
  color: string;
  paper_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface TagCreate {
  name: string;
  color?: string;
}

export interface TagUpdate {
  name?: string;
  color?: string;
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
  favorited?: boolean;
  categories?: string[];
  keywords?: string[];
  authors?: string[];
  title_zh?: string;
  abstract_zh?: string;
  topics?: string[];
  tags?: Tag[];
  skim_report?: {
    summary_md: string;
    skim_score: number | null;
    key_insights: Record<string, unknown>;
  } | null;
  deep_report?: {
    deep_dive_md: string;
    key_insights: Record<string, unknown>;
  } | null;
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
export interface WikiSection {
  title: string;
  content: string;
  key_insight?: string;
}

export interface PdfExcerpt {
  title: string;
  excerpt: string;
}

export interface ScholarMetadataItem {
  title: string;
  year?: number;
  citationCount?: number;
  influentialCitationCount?: number;
  venue?: string;
  fieldsOfStudy?: string[];
  tldr?: string;
}

export interface WikiReadingItem {
  title: string;
  year?: number;
  reason: string;
}

export interface TopicWikiContent {
  overview: string;
  sections: WikiSection[];
  key_findings: string[];
  methodology_evolution: string;
  future_directions: string[];
  reading_list: WikiReadingItem[];
  citation_contexts?: string[];
  pdf_excerpts?: PdfExcerpt[];
  scholar_metadata?: ScholarMetadataItem[];
}

export interface PaperWikiContent {
  summary: string;
  contributions: string[];
  methodology: string;
  significance: string;
  limitations: string[];
  related_work_analysis: string;
  reading_suggestions: WikiReadingItem[];
  citation_contexts?: string[];
  pdf_excerpts?: PdfExcerpt[];
  scholar_metadata?: ScholarMetadataItem[];
}

export interface PaperWiki {
  paper_id: string;
  title?: string;
  markdown: string;
  wiki_content?: PaperWikiContent;
  graph: CitationTree;
  content_id?: string;
}

export interface TopicWiki {
  keyword: string;
  markdown: string;
  wiki_content?: TopicWikiContent;
  timeline: TimelineResponse;
  survey: SurveyResponse;
  content_id?: string;
}

/* ========== 推理链分析 ========== */
export interface ReasoningStep {
  step: string;
  thinking: string;
  conclusion: string;
}

export interface MethodChain {
  problem_definition: string;
  core_hypothesis: string;
  method_derivation: string;
  theoretical_basis: string;
  innovation_analysis: string;
}

export interface ExperimentChain {
  experimental_design: string;
  baseline_fairness: string;
  result_validation: string;
  ablation_insights: string;
}

export interface ImpactAssessment {
  novelty_score: number;
  rigor_score: number;
  impact_score: number;
  overall_assessment: string;
  strengths: string[];
  weaknesses: string[];
  future_suggestions: string[];
}

export interface ReasoningChainResult {
  reasoning_steps: ReasoningStep[];
  method_chain: MethodChain;
  experiment_chain: ExperimentChain;
  impact_assessment: ImpactAssessment;
}

export interface ReasoningAnalysisResponse {
  paper_id: string;
  title: string;
  reasoning: ReasoningChainResult;
}

/* ========== 研究空白识别 ========== */
export interface ResearchGap {
  gap_title: string;
  description: string;
  evidence: string;
  potential_impact: string;
  suggested_approach: string;
  difficulty: "easy" | "medium" | "hard";
  confidence: number;
}

export interface MethodComparisonEntry {
  name: string;
  scores: Record<string, string>;
  papers: string[];
}

export interface MethodComparison {
  dimensions: string[];
  methods: MethodComparisonEntry[];
  underexplored_combinations: string[];
}

export interface TrendAnalysis {
  hot_directions: string[];
  declining_areas: string[];
  emerging_opportunities: string[];
}

export interface ResearchGapsAnalysis {
  research_gaps: ResearchGap[];
  method_comparison: MethodComparison;
  trend_analysis: TrendAnalysis;
  overall_summary: string;
}

export interface ResearchGapsResponse {
  keyword: string;
  network_stats: {
    total_papers: number;
    edge_count: number;
    density: number;
    connected_ratio: number;
    isolated_count: number;
  };
  analysis: ResearchGapsAnalysis;
}

/* ========== 丰富引用详情 ========== */
export interface RichCitationEntry {
  scholar_id: string | null;
  title: string;
  year: number | null;
  venue: string | null;
  citation_count: number | null;
  arxiv_id: string | null;
  abstract: string | null;
  in_library: boolean;
  library_paper_id: string | null;
}

export interface CitationDetail {
  paper_id: string;
  paper_title: string;
  references: RichCitationEntry[];
  cited_by: RichCitationEntry[];
  stats: {
    total_references: number;
    total_cited_by: number;
    in_library_references: number;
    in_library_cited_by: number;
  };
}

export interface NetworkNode {
  id: string;
  title: string;
  year: number | null;
  arxiv_id: string | null;
  in_degree: number;
  out_degree: number;
  is_hub: boolean;
  is_external: boolean;
  co_citation_count?: number;
}

export interface NetworkEdge {
  source: string;
  target: string;
}

export interface TopicCitationNetwork {
  topic_id: string;
  topic_name: string;
  nodes: NetworkNode[];
  edges: NetworkEdge[];
  stats: {
    total_papers: number;
    total_edges: number;
    density: number;
    hub_papers: number;
    internal_papers?: number;
    external_papers?: number;
    internal_edges?: number;
    new_edges_synced?: number;
  };
  key_external_papers?: Array<{
    id: string;
    title: string;
    co_citation_count: number;
  }>;
}

/* ========== 图谱增强 ========== */
export interface OverviewNode {
  id: string;
  title: string;
  arxiv_id: string;
  year: number | null;
  in_degree: number;
  out_degree: number;
  pagerank: number;
  topics: string[];
  read_status: string;
}

export interface SimilarityMapPoint {
  id: string;
  title: string;
  x: number;
  y: number;
  year: number | null;
  read_status: string;
  topics: string[];
  topic: string;
  arxiv_id: string;
  title_zh?: string;
}

export interface SimilarityMapData {
  points: SimilarityMapPoint[];
  total?: number;
  message?: string;
}

export interface LibraryOverview {
  total_papers: number;
  total_edges: number;
  density: number;
  nodes: OverviewNode[];
  edges: NetworkEdge[];
  top_papers: OverviewNode[];
  topic_stats: Record<string, { count: number; edges: number }>;
}

export interface BridgePaper {
  id: string;
  title: string;
  arxiv_id: string;
  topics_citing: string[];
  cross_topic_count: number;
  own_topics: string[];
}

export interface BridgesResponse {
  bridges: BridgePaper[];
  total: number;
}

export interface FrontierPaper {
  id: string;
  title: string;
  arxiv_id: string;
  year: number;
  publication_date: string;
  citations_in_library: number;
  citation_velocity: number;
  read_status: string;
}

export interface FrontierResponse {
  period_days: number;
  total_recent: number;
  frontier: FrontierPaper[];
}

export interface CocitationCluster {
  size: number;
  papers: Array<{ id: string; title: string; arxiv_id: string }>;
}

export interface CocitationResponse {
  total_clusters: number;
  clusters: CocitationCluster[];
  cocitation_pairs: number;
}

/* ========== 简报 ========== */
export interface DailyBriefRequest {
  date?: string;
  recipient?: string;
}

export interface DailyBriefResponse {
  task_id: string;
  status: string;
  message: string;
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
  input_tokens: number;
  output_tokens: number;
}

export interface CostModel {
  provider: string;
  model: string;
  calls: number;
  total_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
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
  message?: string;  // 添加 message 属性
}

/* ========== 摄入 ========== */
export interface IngestPaper {
  id: string;
  title: string;
  arxiv_id?: string;
  publication_date?: string | null;
}

export interface IngestResult {
  ingested: number;
  papers?: IngestPaper[];
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

/* ========== 写作助手 ========== */
export type WritingAction =
  | "zh_to_en" | "en_to_zh" | "zh_polish" | "en_polish"
  | "compress" | "expand" | "logic_check" | "deai"
  | "fig_caption" | "table_caption"
  | "experiment_analysis" | "reviewer" | "chart_recommend"
  | "ocr_extract";

export interface WritingTemplate {
  action: WritingAction;
  label: string;
  description: string;
  icon: string;
  placeholder: string;
  supports_image?: boolean;
}

export interface WritingResult {
  action: string;
  label: string;
  content: string;
  input_tokens?: number;
  output_tokens?: number;
  total_cost_usd?: number;
}

export interface WritingRefineMessage {
  role: "user" | "assistant";
  content: string;
}

export interface WritingRefineResult {
  content: string;
  input_tokens?: number;
  output_tokens?: number;
  total_cost_usd?: number;
}

/* ========== Agent ========== */
export interface AgentMessage {
  role: "user" | "assistant" | "tool";
  content: string;
  tool_call_id?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_result?: Record<string, unknown>;
}

export interface AgentToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface PendingAction {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  description: string;
}

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

/* ========== 论文列表 ========== */
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

/* ========== 引用入库 ========== */
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

/* ========== 每日报告配置 ========== */
export interface DailyReportConfig {
  enabled: boolean;
  auto_deep_read: boolean;
  deep_read_limit: number;
  send_email_report: boolean;
  recipient_emails: string[];
  cron_expression: string;  // 新增：cron 表达式
  report_time_utc: number;  // 保留：向后兼容
  include_paper_details: boolean;
  include_graph_insights: boolean;
}

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
  category?: string;
  created_at?: number;
}

/* ========== 认证 ========== */
export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface AuthStatusResponse {
  auth_enabled: boolean;
}

export type SSEEventType =
  | "text_delta"
  | "tool_start"
  | "tool_result"
  | "tool_progress"
  | "action_confirm"
  | "action_result"
  | "done"
  | "error";

export interface SSEEvent {
  type: SSEEventType;
  data: Record<string, unknown>;
}

/**
 * 解析 SSE 文本流
 */
export function parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: SSEEvent) => void,
  onDone?: () => void,
): () => void {
  const decoder = new TextDecoder();
  let buffer = "";
  let cancelled = false;
  // 跨 chunk 保留事件类型
  let currentEvent = "";

  const processBuffer = () => {
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        const dataStr = line.slice(6);
        try {
          const data = JSON.parse(dataStr);
          onEvent({ type: currentEvent as SSEEventType, data });
        } catch (e) {
          console.warn("[SSE] Failed to parse:", currentEvent, dataStr.slice(0, 200), e);
        }
        currentEvent = "";
      }
    }
  };

  const read = async () => {
    try {
      while (!cancelled) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        processBuffer();
      }
      // 流结束时处理残余数据
      if (buffer.trim()) {
        buffer += "\n";
        processBuffer();
      }
    } finally {
      onDone?.();
    }
  };

  read();

  return () => {
    cancelled = true;
    reader.cancel();
  };
}
