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
