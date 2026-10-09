// PaperMind Go API Server（2.1 全量重写 Phase 0：绞杀者入口）。
//
// 职责：/api/ 流量的唯一入口——已移植路由（设备码授权全流程、健康检查）
// 由本服务直接执行（PG 权威数据）；未移植路由透明反代到 Python backend。
// 前端 nginx 的 /api/ upstream 指向本服务（infra/nginx.conf）。
package main

import (
	"log"
	"net/http"
	"time"
)

func main() {
	cfg := LoadConfig()
	db, err := OpenDB(cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("db open: %v", err)
	}
	defer db.Close()

	s := &Server{cfg: cfg, db: db}

	mux := http.NewServeMux()

	// ---- 已移植：Go 直接执行 ----
	// 注意：frontend nginx 已剥掉 /api/ 前缀（rewrite ^/api/(.*) /$1）——
	// 本服务收到的路径与 Python backend 同形状（无 /api/ 前缀）
	mux.HandleFunc("GET /api/health", s.handleHealth) // 直连巡检入口（nginx /health 由其自答）
	mux.HandleFunc("GET /health", s.handleHealth)
	mux.HandleFunc("POST /auth/device/start", s.handleDeviceStart)
	mux.HandleFunc("POST /auth/device/poll", s.handleDevicePoll)
	mux.HandleFunc("GET /auth/device/{code}", s.handleDeviceInfo)
	mux.HandleFunc("POST /auth/device/{code}/authorize", s.requireWebSession(s.handleDeviceAuthorize))
	mux.HandleFunc("POST /auth/device/{code}/deny", s.requireWebSession(s.handleDeviceDeny))
	mux.HandleFunc("GET /papers/folder-stats", s.requireAuth(s.handleFolderStats))
	mux.HandleFunc("GET /papers/latest", s.requireAuth(s.handlePapersLatest))
	mux.HandleFunc("GET /papers/{paper_id}", s.requireAuth(s.handlePaperDetail))
	mux.HandleFunc("PATCH /papers/{paper_id}/favorite", s.requireAuth(s.handleToggleFavorite))
	mux.HandleFunc("PATCH /papers/{paper_id}/reject", s.requireAuth(s.handleToggleReject))

	// ---- Phase 2：jobs/tasks/queue 管理面 ----
	mux.HandleFunc("GET /jobs", s.requireAuth(s.handleListJobs))
	mux.HandleFunc("GET /jobs/{job_id}", s.requireAuth(s.handleGetJob))
	mux.HandleFunc("POST /jobs/durable", s.requireAuth(s.handleSubmitDurable))
	mux.HandleFunc("POST /jobs/{job_id}/cancel", s.requireAuth(s.handleCancelJob))
	mux.HandleFunc("POST /jobs/{job_id}/retry", s.requireAuth(s.handleRetryJob))
	mux.HandleFunc("POST /tasks/{task_id}/retry", s.requireAuth(s.handleRetryTask))
	mux.HandleFunc("POST /queue/pause", s.requireAuth(s.handlePauseQueue))
	mux.HandleFunc("POST /queue/resume", s.requireAuth(s.handleResumeQueue))

	// ---- Phase 2：topics 12 端点 ----
	mux.HandleFunc("GET /topics", s.requireAuth(s.handleListTopics))
	mux.HandleFunc("POST /topics", s.requireAuth(s.handleUpsertTopic))
	mux.HandleFunc("PATCH /topics/{topic_id}", s.requireAuth(s.handleUpdateTopic))
	mux.HandleFunc("DELETE /topics/{topic_id}", s.requireAuth(s.handleDeleteTopic))
	mux.HandleFunc("POST /topics/{topic_id}/fetch", s.requireAuth(s.handleManualFetchTopic))
	mux.HandleFunc("GET /topics/stats", s.requireAuth(s.handleTopicStats))
	mux.HandleFunc("POST /ingest/arxiv", s.requireAuth(s.handleIngestArxiv))

	// ---- Phase 2：cs_feeds 6 端点 ----
	mux.HandleFunc("GET /cs/categories", s.requireAuth(s.handleCSCategories))
	mux.HandleFunc("GET /cs/feeds", s.requireAuth(s.handleCSFeeds))
	mux.HandleFunc("POST /cs/feeds", s.requireAuth(s.handleCSSubscribe))
	mux.HandleFunc("DELETE /cs/feeds/{category_code}", s.requireAuth(s.handleCSUnsubscribe))
	mux.HandleFunc("PATCH /cs/feeds/{category_code}", s.requireAuth(s.handleCSUpdateFeed))
	mux.HandleFunc("POST /cs/feeds/{category_code}/fetch", s.requireAuth(s.handleCSFetch))

	// ---- Phase 1：tags 8 端点 ----
	mux.HandleFunc("GET /tags", s.requireAuth(s.handleListTags))
	mux.HandleFunc("POST /tags", s.requireAuth(s.handleCreateTag))
	mux.HandleFunc("PATCH /tags/{tag_id}", s.requireAuth(s.handleUpdateTag))
	mux.HandleFunc("DELETE /tags/{tag_id}", s.requireAuth(s.handleDeleteTag))
	mux.HandleFunc("GET /papers/{paper_id}/tags", s.requireAuth(s.handleGetPaperTags))
	mux.HandleFunc("POST /papers/{paper_id}/tags", s.requireAuth(s.handleAddPaperTag))
	mux.HandleFunc("DELETE /papers/{paper_id}/tags/{tag_id}", s.requireAuth(s.handleRemovePaperTag))
	mux.HandleFunc("POST /papers/{paper_id}/tags/batch", s.requireAuth(s.handleBatchPaperTags))

	// ---- Phase 1：research 读面 5 端点 ----
	mux.HandleFunc("GET /research/questions/{question_id}", s.requireAuth(s.handleResearchQuestion))
	mux.HandleFunc("GET /research/questions/{question_id}/claims", s.requireAuth(s.handleListClaims))
	mux.HandleFunc("GET /research/claims/{claim_id}/evidence", s.requireAuth(s.handleClaimEvidence))
	mux.HandleFunc("GET /research/questions/{question_id}/diff", s.requireAuth(s.handleDiffResearchState))
	mux.HandleFunc("GET /research/questions/{question_id}/export", s.requireAuth(s.handleResearchExport))

	// ---- Phase 4：pipelines / tasks / RAG / content / writing / agent ----
	mux.HandleFunc("POST /pipelines/skim/{paper_id}", s.requireAuth(s.handleStartSkim))
	mux.HandleFunc("POST /pipelines/skim-batch", s.requireAuth(s.handleStartSkimBatch))
	mux.HandleFunc("POST /pipelines/deep/{paper_id}", s.requireAuth(s.handleStartDeep))
	mux.HandleFunc("POST /pipelines/embed/{paper_id}", s.requireAuth(s.handleStartEmbed))
	mux.HandleFunc("GET /tasks/active", s.requireAuth(s.handleTaskActive))
	mux.HandleFunc("GET /tasks/{task_id}", s.requireAuth(s.handleTaskStatus))
	mux.HandleFunc("GET /tasks/{task_id}/result", s.requireAuth(s.handleTaskResult))
	mux.HandleFunc("POST /tasks/wiki/topic", s.requireAuth(s.handleStartTopicWiki))
	mux.HandleFunc("POST /rag/ask", s.requireAuth(s.handleRagAsk))
	mux.HandleFunc("POST /rag/ask-iterative", s.requireAuth(s.handleRagAsk))
	mux.HandleFunc("GET /wiki/paper/{paper_id}", s.requireAuth(s.handleWikiPaper))
	mux.HandleFunc("GET /wiki/topic", s.requireAuth(s.handleWikiTopic))
	mux.HandleFunc("GET /generated/list", s.requireAuth(s.handleGeneratedList))
	mux.HandleFunc("GET /generated/{content_id}", s.requireAuth(s.handleGeneratedDetail))
	mux.HandleFunc("DELETE /generated/{content_id}", s.requireAuth(s.handleGeneratedDelete))
	mux.HandleFunc("POST /brief/daily", s.requireAuth(s.handleBriefDaily))
	mux.HandleFunc("GET /trends/hot", s.requireAuth(s.handleTrendsHot))
	mux.HandleFunc("GET /trends/emerging", s.requireAuth(s.handleTrendsEmerging))
	mux.HandleFunc("GET /today", s.requireAuth(s.handleToday))
	mux.HandleFunc("GET /writing/templates", s.requireAuth(s.handleWritingTemplates))
	mux.HandleFunc("POST /writing/process", s.requireAuth(s.handleWritingProcess))
	mux.HandleFunc("POST /writing/refine", s.requireAuth(s.handleWritingRefine))
	mux.HandleFunc("POST /writing/process-multimodal", s.requireAuth(s.handleWritingProcessMultimodal))
	mux.HandleFunc("GET /agent/engine", s.requireAuth(s.handleAgentEngine))
	mux.HandleFunc("POST /agent/chat", s.requireAuth(s.handleAgentChat))
	mux.HandleFunc("POST /agent/pending-actions", s.requireAuth(s.handleCreatePendingAction))
	mux.HandleFunc("GET /agent/pending-actions/{action_id}", s.requireAuth(s.handleGetPendingAction))
	mux.HandleFunc("POST /agent/confirm/{action_id}", s.requireAuth(s.handleAgentConfirm))
	mux.HandleFunc("POST /agent/reject/{action_id}", s.requireAuth(s.handleAgentReject))
	mux.HandleFunc("GET /agent/conversations", s.requireAuth(s.handleListConversations))
	mux.HandleFunc("GET /agent/conversations/{conversation_id}", s.requireAuth(s.handleGetConversation))
	mux.HandleFunc("DELETE /agent/conversations/{conversation_id}", s.requireAuth(s.handleDeleteConversation))

	// ---- Phase 5：认证全量 + settings + system + metrics ----
	mux.HandleFunc("POST /auth/login", s.handleLogin)
	mux.HandleFunc("GET /auth/status", s.handleAuthStatus)
	mux.HandleFunc("GET /auth/me", s.requireAuth(s.handleMe))
	mux.HandleFunc("POST /auth/tokens", s.requireWebSession(s.handleCreateToken))
	mux.HandleFunc("GET /auth/tokens", s.requireWebSession(s.handleListTokens))
	mux.HandleFunc("DELETE /auth/tokens/{token_id}", s.requireAuth(s.handleRevokeToken))
	mux.HandleFunc("GET /settings/llm-providers", s.requireAuth(s.handleListLLMProviders))
	mux.HandleFunc("GET /settings/llm-providers/active", s.requireAuth(s.handleActiveLLMProvider))
	mux.HandleFunc("POST /settings/llm-providers/deactivate", s.requireAuth(s.handleDeactivateLLMProviders))
	mux.HandleFunc("POST /settings/llm-providers", s.requireAuth(s.handleCreateLLMProvider))
	mux.HandleFunc("PATCH /settings/llm-providers/{config_id}", s.requireAuth(s.handleUpdateLLMProvider))
	mux.HandleFunc("DELETE /settings/llm-providers/{config_id}", s.requireAuth(s.handleDeleteLLMProvider))
	mux.HandleFunc("POST /settings/llm-providers/{config_id}/activate", s.requireAuth(s.handleActivateLLMProvider))
	mux.HandleFunc("GET /settings/email-configs", s.requireAuth(s.handleListEmailConfigs))
	mux.HandleFunc("POST /settings/email-configs", s.requireAuth(s.handleCreateEmailConfig))
	mux.HandleFunc("PATCH /settings/email-configs/{config_id}", s.requireAuth(s.handleUpdateEmailConfig))
	mux.HandleFunc("DELETE /settings/email-configs/{config_id}", s.requireAuth(s.handleDeleteEmailConfig))
	mux.HandleFunc("POST /settings/email-configs/{config_id}/activate", s.requireAuth(s.handleActivateEmailConfig))
	mux.HandleFunc("POST /settings/email-configs/{config_id}/test", s.requireAuth(s.handleTestEmailConfig))
	mux.HandleFunc("GET /settings/daily-report-config", s.requireAuth(s.handleGetDailyReportConfig))
	mux.HandleFunc("PUT /settings/daily-report-config", s.requireAuth(s.handleUpdateDailyReportConfig))
	mux.HandleFunc("GET /settings/smtp-presets", s.requireAuth(s.handleSMTPPresets))
	mux.HandleFunc("GET /system/worker", s.requireAuth(s.handleSystemWorker))
	mux.HandleFunc("GET /system/status", s.requireAuth(s.handleSystemStatus))
	mux.HandleFunc("GET /metrics/costs", s.requireAuth(s.handleMetricsCosts))

	// ---- Phase 6：translate + sensemaking + graph + citations ----
	mux.HandleFunc("POST /translate/selection", s.requireAuth(s.handleTranslateSelection))
	mux.HandleFunc("POST /translate/segments", s.requireAuth(s.handleTranslateSegments))
	mux.HandleFunc("POST /translate/bilingual-pdf", s.requireAuth(s.handleBilingualPDFStart))
	mux.HandleFunc("GET /translate/bilingual-pdf/{paper_id}", s.requireAuth(s.handleBilingualPDFCache))
	mux.HandleFunc("GET /translate/bilingual-pdf/{paper_id}/file", s.requireAuth(s.handleBilingualPDFFile))
	mux.HandleFunc("POST /sensemaking/schemas", s.requireAuth(s.handleCreateSchema))
	mux.HandleFunc("GET /sensemaking/schemas", s.requireAuth(s.handleListSchemas))
	mux.HandleFunc("GET /sensemaking/schemas/{schema_id}", s.requireAuth(s.handleGetSchema))
	mux.HandleFunc("POST /sensemaking/sessions", s.requireAuth(s.handleCreateSenseSession))
	mux.HandleFunc("GET /sensemaking/sessions", s.requireAuth(s.handleListSenseSessions))
	mux.HandleFunc("GET /sensemaking/sessions/{session_id}", s.requireAuth(s.handleGetSenseSession))
	mux.HandleFunc("PATCH /sensemaking/sessions/{session_id}/act1", s.requireAuth(s.handleUpdateAct))
	mux.HandleFunc("PATCH /sensemaking/sessions/{session_id}/act2", s.requireAuth(s.handleUpdateAct))
	mux.HandleFunc("PATCH /sensemaking/sessions/{session_id}/act3", s.requireAuth(s.handleUpdateAct))
	mux.HandleFunc("POST /sensemaking/sessions/{session_id}/act1/generate", s.requireAuth(s.handleGenerateAct))
	mux.HandleFunc("POST /sensemaking/sessions/{session_id}/act2/generate", s.requireAuth(s.handleGenerateAct))
	mux.HandleFunc("POST /sensemaking/sessions/{session_id}/act3/generate", s.requireAuth(s.handleGenerateAct))
	mux.HandleFunc("POST /sensemaking/interactions", s.requireAuth(s.handleCreateInteraction))
	mux.HandleFunc("POST /citations/sync/incremental", s.requireAuth(s.handleSyncCitationsIncremental))
	mux.HandleFunc("POST /citations/sync/topic/{topic_id}", s.requireAuth(s.handleSyncCitationsTopic))
	mux.HandleFunc("POST /citations/sync/{paper_id}", s.requireAuth(s.handleSyncCitationsPaper))
	mux.HandleFunc("GET /graph/similarity-map", s.requireAuth(s.handleSimilarityMap))
	mux.HandleFunc("GET /graph/cluster-map", s.requireAuth(s.handleClusterMap))
	mux.HandleFunc("GET /graph/similar-via-citation/{paper_id}", s.requireAuth(s.handleSimilarViaCitation))
	mux.HandleFunc("GET /graph/citation-tree/{paper_id}", s.requireAuth(s.handleCitationTree))
	mux.HandleFunc("GET /graph/citation-detail/{paper_id}", s.requireAuth(s.handleCitationDetail))
	mux.HandleFunc("GET /graph/citation-network/topic/{topic_id}", s.requireAuth(s.handleTopicCitationNetwork))
	mux.HandleFunc("POST /graph/citation-network/topic/{topic_id}/deep-trace", s.requireAuth(s.handleTopicDeepTrace))
	mux.HandleFunc("GET /graph/overview", s.requireAuth(s.handleGraphOverview))
	mux.HandleFunc("GET /graph/bridges", s.requireAuth(s.handleGraphBridges))
	mux.HandleFunc("GET /graph/frontier", s.requireAuth(s.handleGraphFrontier))
	mux.HandleFunc("GET /graph/cocitation-clusters", s.requireAuth(s.handleCocitationClusters))
	mux.HandleFunc("GET /graph/timeline", s.requireAuth(s.handleGraphTimeline))
	mux.HandleFunc("GET /graph/quality", s.requireAuth(s.handleGraphQuality))
	mux.HandleFunc("GET /graph/evolution/weekly", s.requireAuth(s.handleWeeklyEvolution))
	mux.HandleFunc("GET /graph/survey", s.requireAuth(s.handleGraphSurvey))
	mux.HandleFunc("GET /graph/research-gaps", s.requireAuth(s.handleResearchGaps))

	// ---- 未移植：透明反代到 Python backend（绞杀者回退） ----
	// "/" 兜底：/whoami /jobs /papers/search 等未注册路径全部进反代
	// （Go 1.22 ServeMux 中精确/具体 pattern 优先于 "/"）
	mux.HandleFunc("/", s.proxyLegacy)

	addr := cfg.ListenAddr
	srv := &http.Server{Addr: addr, Handler: mux,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       120 * time.Second,
		WriteTimeout:      600 * time.Second, // SSE 长流
		IdleTimeout:       120 * time.Second,
	}
	log.Printf("PaperMind Go API listening on %s (legacy=%s)", addr, cfg.BackendOrigin)
	log.Fatal(srv.ListenAndServe())
}
