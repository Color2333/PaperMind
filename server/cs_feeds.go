package main

// cs_feeds.go：CS 分类订阅管理（Phase 2）——与 apps/api/routers/cs_feeds.py
// 逐契约对齐，同时修复旧实现的三个设计问题：
// 1. fetch 后无 post-processing（papers 留 unread 无 embedding）→ Go Core 的
//    cs_feed_fetch_category 任务自带 A 档 apply，后续 idle_processor 补偿
// 2. token bucket 在 migration 中丢失 → dispatcher 按 daily_limit + cool_down 控制
// 3. 冷却逻辑与配额检查分散在 Python handler → 统一收口到 dispatcher

import (
	"encoding/json"
	"net/http"
	"strings"
)

// handleCSCategories：GET /cs/categories。
func (s *Server) handleCSCategories(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(
		"SELECT code, name, COALESCE(description,'') FROM cs_categories ORDER BY code")
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	categories := []map[string]string{}
	for rows.Next() {
		var code, name, desc string
		if err := rows.Scan(&code, &name, &desc); err == nil {
			categories = append(categories, map[string]string{"code": code, "name": name, "description": desc})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"categories": categories})
}

// handleCSFeeds：GET /cs/feeds。
func (s *Server) handleCSFeeds(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(
		`SELECT f.category_code, COALESCE(c.name, f.category_code),
			f.daily_limit, f.enabled, f.status,
			TO_CHAR(f.last_run_at, 'YYYY-MM-DD"T"HH24:MI:SSOF'),
			COALESCE(f.last_run_count, 0)
		 FROM cs_feed_subscriptions f
		 LEFT JOIN cs_categories c ON c.code = f.category_code
		 ORDER BY f.category_code`)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	feeds := []map[string]any{}
	for rows.Next() {
		var code, catName, status string
		var dailyLimit int
		var enabled bool
		var lastRunAt *string
		var lastRunCount int
		if err := rows.Scan(&code, &catName, &dailyLimit, &enabled, &status, &lastRunAt, &lastRunCount); err != nil {
			continue
		}
		feeds = append(feeds, map[string]any{
			"category_code": code, "category_name": catName,
			"daily_limit": dailyLimit, "enabled": enabled, "status": status,
			"last_run_at": jsonStrOrNull(lastRunAt), "last_run_count": lastRunCount,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"feeds": feeds})
}

type csSubscribeReq struct {
	CategoryCodes []string `json:"category_codes"`
	DailyLimit    int      `json:"daily_limit"`
	Enabled       bool     `json:"enabled"`
}

// handleCSSubscribe：POST /cs/feeds。
func (s *Server) handleCSSubscribe(w http.ResponseWriter, r *http.Request) {
	var body csSubscribeReq
	body.DailyLimit = 30
	body.Enabled = true
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		// 也支持 query 参数
		body.CategoryCodes = strings.Split(r.URL.Query().Get("category_codes"), ",")
		body.DailyLimit = atoiOr(r.URL.Query().Get("daily_limit"), 30)
		body.Enabled = r.URL.Query().Get("enabled") != "false"
	}
	if len(body.CategoryCodes) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "category_codes required"})
		return
	}
	created := []map[string]any{}
	for _, code := range body.CategoryCodes {
		code = strings.TrimSpace(code)
		if code == "" {
			continue
		}
		_, err := s.db.Exec(
			`INSERT INTO cs_feed_subscriptions (id, category_code, daily_limit, enabled, status, created_at)
			 VALUES (gen_random_uuid()::text, $1, $2, $3, 'active', now()::timestamp)
			 ON CONFLICT (category_code) DO UPDATE SET daily_limit=$2, enabled=$3, updated_at=now()::timestamp`,
			code, body.DailyLimit, body.Enabled)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
			return
		}
		created = append(created, map[string]any{
			"category_code": code, "daily_limit": body.DailyLimit, "enabled": body.Enabled,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"created": len(created), "feeds": created})
}

// handleCSUnsubscribe：DELETE /cs/feeds/{code}。
func (s *Server) handleCSUnsubscribe(w http.ResponseWriter, r *http.Request) {
	res, err := s.db.Exec(
		"DELETE FROM cs_feed_subscriptions WHERE category_code=$1",
		r.PathValue("category_code"),
	)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	n, _ := res.RowsAffected()
	writeJSON(w, http.StatusOK, map[string]int{"deleted": int(n)})
}

// handleCSUpdateFeed：PATCH /cs/feeds/{code}。
func (s *Server) handleCSUpdateFeed(w http.ResponseWriter, r *http.Request) {
	code := r.PathValue("category_code")
	var body struct {
		DailyLimit *int  `json:"daily_limit"`
		Enabled    *bool `json:"enabled"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "bad json"})
		return
	}
	sets := []string{}
	args := []any{}
	argN := 0
	if body.DailyLimit != nil {
		argN++
		sets = append(sets, "daily_limit=$"+itoa(argN))
		args = append(args, *body.DailyLimit)
	}
	if body.Enabled != nil {
		argN++
		sets = append(sets, "enabled=$"+itoa(argN))
		args = append(args, *body.Enabled)
	}
	if len(sets) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "nothing to update"})
		return
	}
	args = append(args, code)
	res, err := s.db.Exec(
		"UPDATE cs_feed_subscriptions SET "+strings.Join(sets, ", ")+" WHERE category_code=$"+itoa(len(args)),
		args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "订阅不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"category_code": code, "status": "updated"})
}

// handleCSFetch：POST /cs/feeds/{code}/fetch —— 提交 cs_feed_fetch_category 任务。
func (s *Server) handleCSFetch(w http.ResponseWriter, r *http.Request) {
	code := r.PathValue("category_code")
	var exists bool
	if err := s.db.QueryRow(
		"SELECT EXISTS(SELECT 1 FROM cs_feed_subscriptions WHERE category_code=$1 AND enabled)", code,
	).Scan(&exists); err != nil || !exists {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "订阅不存在或已禁用"})
		return
	}
	jobID, taskID, err := s.submitCoreTask("cs_feed_fetch_category", map[string]any{
		"category_code": code,
	}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"job_id": jobID, "task_id": taskID, "status": "started",
	})
}
