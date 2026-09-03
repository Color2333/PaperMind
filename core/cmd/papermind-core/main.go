// PaperMind Go Core 入口（P0：durable-state 网关模式）。
//
// 环境变量：
//
//	CORE_ADDR          监听地址（默认 127.0.0.1:8081，不绑所有网卡）
//	CORE_TOKEN         Executor/控制面 Bearer token（空 = 不校验）
//	STATE_ADDR         Python durable-state API 地址（默认 127.0.0.1:8000）
//	STATE_TOKEN        X-Internal-Token（与 settings.durable_state_token 一致）
//	RECONCILE_INTERVAL 过期 lease 回收周期（默认 15s）
//	RECLAIM_BACKOFF_S  lease 过期后的额外宽限（默认 60s）
package main

import (
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/Color2333/PaperMind/core"
)

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	addr := envOr("CORE_ADDR", "127.0.0.1:8081")
	stateAddr := envOr("STATE_ADDR", "http://127.0.0.1:8000")
	token := os.Getenv("CORE_TOKEN")
	stateToken := os.Getenv("STATE_TOKEN")

	reconcileInterval := 15 * time.Second
	if v, err := strconv.Atoi(envOr("RECONCILE_INTERVAL_S", "15")); err == nil && v > 0 {
		reconcileInterval = time.Duration(v) * time.Second
	}
	reclaimBackoff := 60
	if v, err := strconv.Atoi(envOr("RECLAIM_BACKOFF_S", "60")); err == nil && v > 0 {
		reclaimBackoff = v
	}

	// P1 fail-closed：生产默认要求双令牌齐备（executor 面 + state 面）。
	// 缺任一即拒绝启动——无认证的控制面不应"碰巧能跑"。
	if (token == "" || stateToken == "") && os.Getenv("ALLOW_INSECURE_CORE") != "1" {
		log.Fatalf(
			"refusing to start: CORE_TOKEN and STATE_TOKEN are required (set ALLOW_INSECURE_CORE=1 to override for local experiments)",
		)
	}

	registry := core.NewExecutorRegistry()
	state := core.NewStateClient(stateAddr, stateToken)
	server := core.NewServer(registry, state)
	server.StartReconciler(reconcileInterval, reclaimBackoff, make(chan struct{}))

	var handler http.Handler = server.Handler()
	if token != "" {
		handler = core.TokenAuthMiddleware(handler, token)
	}

	srv := &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: 10 * time.Second,
	}
	log.Printf("PaperMind Go Core (%s) listening on %s [state=%s]", core.CoreVersion, addr, stateAddr)
	log.Fatal(srv.ListenAndServe())
}
