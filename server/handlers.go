package main

// handlers.go：已移植路由的业务处理（folder-stats / 设备信息与授权决策）。

import (
	"encoding/json"
	"net/http"
	"time"
)

var srvHealthBody = `{"status":"ok","app":"PaperMind Go API","component":"goserver"}`

// handleHealth：Go 组件健康（无鉴权，巡检用）。
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(srvHealthBody))
}

// handleFolderStats：论文库概况（GET /api/papers/folder-stats，需鉴权）。
// 与 Python get_folder_stats 输出键对齐：total/favorites/recent_7d/unclassified/by_topic。
func (s *Server) handleFolderStats(w http.ResponseWriter, r *http.Request) {
	var total, favorites, recent7d, unclassified int
	err := s.db.QueryRow(`
		WITH t AS (
			SELECT p.id, p.favorited, p.created_at,
				(SELECT COUNT(*) FROM paper_topics pt WHERE pt.paper_id = p.id) AS topic_links
			FROM papers p
		)
		SELECT
			COUNT(*) AS total,
			COUNT(*) FILTER (WHERE favorited) AS favorites,
			COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days') AS recent_7d,
			COUNT(*) FILTER (WHERE topic_links = 0) AS unclassified
		FROM t`).Scan(&total, &favorites, &recent7d, &unclassified)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	type topicRow struct {
		TopicID   string `json:"topic_id"`
		TopicName string `json:"topic_name"`
		Count     int    `json:"count"`
	}
	byTopic := []topicRow{}
	rows, err := s.db.Query(`
		SELECT ts.id, ts.name, COUNT(pt.paper_id) AS cnt
		FROM topic_subscriptions ts
		JOIN paper_topics pt ON pt.topic_id = ts.id
		GROUP BY ts.id, ts.name
		ORDER BY cnt DESC
		LIMIT 10`)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var tr topicRow
			if err := rows.Scan(&tr.TopicID, &tr.TopicName, &tr.Count); err == nil {
				byTopic = append(byTopic, tr)
			}
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"total":        total,
		"favorites":    favorites,
		"recent_7d":    recent7d,
		"unclassified": unclassified,
		"by_topic":     byTopic,
	})
}

// requireAuth：CLI/API 令牌 或 Web JWT 二选一通过（Phase 0 仅校验有效性）。
func (s *Server) requireAuth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.cfg.AuthPassword == "" {
			next(w, r) // 认证关闭（与 Python 行为一致）
			return
		}
		token := bearerToken(r)
		if token == "" {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "Not authenticated"})
			return
		}
		// API 令牌（SHA-256 查表）优先；Web JWT 兜底
		if s.validAPITokenScoped(token, r.Method) {
			next(w, r)
			return
		}
		if validWebJWT(token, s.cfg.SecretKey) {
			next(w, r)
			return
		}
		writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "Invalid or expired token"})
	}
}

// requireWebSession：仅 Web JWT 会话（网页批准设备授权等页面用）。
func (s *Server) requireWebSession(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.cfg.AuthPassword == "" {
			next(w, r)
			return
		}
		token := bearerToken(r)
		if token == "" || !validWebJWT(token, s.cfg.SecretKey) {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "Not authenticated"})
			return
		}
		next(w, r)
	}
}

func (s *Server) validAPIToken(raw string) bool {
	var id string
	err := s.db.QueryRow(
		`SELECT id FROM api_tokens
		 WHERE token_hash = $1 AND revoked_at IS NULL
		   AND (expires_at IS NULL OR expires_at > now()::timestamp)`,
		hashToken(raw),
	).Scan(&id)
	return err == nil
}

// validAPITokenScoped：API 令牌 + 方法级 scope 校验（R01——写方法需 write scope）。
func (s *Server) validAPITokenScoped(raw string, method string) bool {
	if method == http.MethodGet || method == http.MethodHead || method == http.MethodOptions {
		return s.validAPIToken(raw)
	}
	var id string
	var scopes []byte
	err := s.db.QueryRow(
		`SELECT id, scopes FROM api_tokens
		 WHERE token_hash = $1 AND revoked_at IS NULL
		   AND (expires_at IS NULL OR expires_at > now()::timestamp)`,
		hashToken(raw),
	).Scan(&id, &scopes)
	if err != nil {
		return false
	}
	var list []string
	if json.Unmarshal(scopes, &list) != nil {
		return false
	}
	for _, sc := range list {
		if sc == "write" {
			return true
		}
	}
	return false
}

func validWebJWT(token, secret string) bool {
	parsed, err := jwtParseHS256(token, secret)
	return err == nil && parsed.valid
}

// bearerToken：从 Authorization 头提取 Bearer 值。
func bearerToken(r *http.Request) string {
	const prefix = "Bearer "
	h := r.Header.Get("Authorization")
	if len(h) > len(prefix) && h[:len(prefix)] == prefix {
		return h[len(prefix):]
	}
	return ""
}

// JWT 过期兜底引用（validWebJWT 内部使用 jwt.WithExpirationRequired）。
var _ = time.Time{}
