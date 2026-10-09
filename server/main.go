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
	mux.HandleFunc("GET /api/health", s.handleHealth)
	mux.HandleFunc("POST /api/auth/device/start", s.handleDeviceStart)
	mux.HandleFunc("POST /api/auth/device/poll", s.handleDevicePoll)
	mux.HandleFunc("GET /api/auth/device/{code}", s.handleDeviceInfo)
	mux.HandleFunc("POST /api/auth/device/{code}/authorize", s.requireWebSession(s.handleDeviceAuthorize))
	mux.HandleFunc("POST /api/auth/device/{code}/deny", s.requireWebSession(s.handleDeviceDeny))
	mux.HandleFunc("GET /api/papers/folder-stats", s.requireAuth(s.handleFolderStats))
	mux.HandleFunc("GET /api/papers/latest", s.requireAuth(s.handlePapersLatest))

	// ---- 未移植：透明反代到 Python backend（绞杀者回退） ----
	mux.HandleFunc("/api/", s.proxyLegacy)
	mux.HandleFunc("/internal/", s.proxyLegacy)

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
