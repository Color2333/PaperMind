package main

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"sync"
	"time"

	core "github.com/Color2333/PaperMind/core"
)

// Server：Go API 服务（绞杀者入口）。
type Server struct {
	cfg Config
	db  *sql.DB

	gateway *core.GatewayClient
	gwOnce  sync.Once

	pollMu   sync.Mutex
	lastPoll map[string]time.Time
}

// workerEnv 构建 core.HandlerEnv（Phase 4/6 端点复用 worker 的生成能力）。
func (s *Server) workerEnv() *core.HandlerEnv {
	return &core.HandlerEnv{
		Store:   &core.CoreStore{DB: s.db, IsPG: true},
		Gateway: s.GW(),
		Embed:   core.NewEmbedClient(),
		Arxiv:   core.NewArxivClient(),
		Scholar: core.NewScholarClient(),
		SMTP:    core.LoadSMTPConfig(),
		PDFRoot: envOr("PDF_STORAGE_ROOT", "/app/data/papers"),
	}
}

// GW 网关客户端单例。
func (s *Server) GW() *core.GatewayClient {
	s.gwOnce.Do(func() { s.gateway = core.NewGatewayClient() })
	return s.gateway
}

// queryInt 查询参数整数解析。
func queryInt(r *http.Request, key string, def int) int {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < 0 {
		return def
	}
	return n
}

// newUUID UUIDv4（读面落库用）。
func newUUID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// writeJSON：统一 JSON 响应。
func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// withTx：事务包裹（错误自动回滚）。
func (s *Server) withTx(ctx context.Context, fn func(tx *sql.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	if err = fn(tx); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}
