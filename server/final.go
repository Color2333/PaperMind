// Phase 7 终：最后 7 个前端端点——fetch-status / suggest-keywords /
// ingest-references / auto-link / actions 详情。
package main

import (
	"database/sql"
	"fmt"
	"encoding/json"
	"net/http"
	"strings"
)

// handleFetchTopicStatus GET /topics/{topic_id}/fetch-status —— 观察面轮询。
func (s *Server) handleFetchTopicStatus(w http.ResponseWriter, r *http.Request) {
	topicID := r.PathValue("topic_id")
	// 在途 ingest 任务（该主题最近的）
	var taskID, status string
	err := s.db.QueryRow(
		`SELECT id, status FROM core_tasks
		 WHERE capability='ingest_arxiv_query'
		   AND input_ref->>'topic_id' = $1
		   AND status IN ('queued','leased','cancelling')
		 ORDER BY created_at DESC LIMIT 1`, topicID).Scan(&taskID, &status)
	if err == nil {
		writeJSON(w, http.StatusOK, map[string]any{
			"status": "running", "task_id": taskID, "task_status": status, "finished": false,
		})
		return
	}
	// 最近完成的
	var doneID, doneStatus string
	err = s.db.QueryRow(
		`SELECT id, status FROM core_tasks
		 WHERE capability='ingest_arxiv_query' AND input_ref->>'topic_id' = $1
		 ORDER BY created_at DESC LIMIT 1`, topicID).Scan(&doneID, &doneStatus)
	if err == nil && (doneStatus == "succeeded" || doneStatus == "failed" || doneStatus == "dead_letter") {
		writeJSON(w, http.StatusOK, map[string]any{
			"status": map[bool]string{true: "completed", false: "failed"}[doneStatus == "succeeded"],
			"task_id": doneID, "finished": true, "success": doneStatus == "succeeded",
		})
		return
	}
	// 主题信息兜底
	var name string
	info := map[string]any{}
	if s.db.QueryRow(`SELECT COALESCE(name,'') FROM topic_subscriptions WHERE id=$1`, topicID).Scan(&name) == nil {
		info["topic"] = map[string]any{"id": topicID, "name": name}
	}
	writeJSON(w, http.StatusOK, info)
}

// handleSuggestKeywords POST /topics/suggest-keywords —— LLM 关键词建议（同 suggest-channels）。
func (s *Server) handleSuggestKeywords(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Description string `json:"description"`
	}
	if err := readBody(r, &body); err != nil || strings.TrimSpace(body.Description) == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "description is required"})
		return
	}
	prompt := "请为以下研究方向描述生成 5-8 个英文学术检索关键词（arXiv 检索用），输出严格 JSON：{\"suggestions\":[\"keyword1\",\"keyword2\"]}\n\n研究方向: " + body.Description
	parsed, _, err := s.GW().CompleteJSON(r.Context(), "skim", prompt)
	if err != nil || parsed == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "LLM 生成失败"})
		return
	}
	suggestions := []string{}
	if list, ok := parsed["suggestions"].([]any); ok {
		for _, x := range list {
			if v := strOf(x); v != "" {
				suggestions = append(suggestions, v)
			}
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"suggestions": suggestions})
}

// handleIngestReferences POST /ingest/references —— 一键导入参考文献（任务提交）。
func (s *Server) handleIngestReferences(w http.ResponseWriter, r *http.Request) {
	var body struct {
		SourcePaperID    string         `json:"source_paper_id"`
		SourcePaperTitle string         `json:"source_paper_title"`
		Entries          []map[string]any `json:"entries"`
		TopicIDs         []string       `json:"topic_ids"`
	}
	if err := readBody(r, &body); err != nil || body.SourcePaperID == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "source_paper_id required"})
		return
	}
	if body.Entries == nil {
		body.Entries = []map[string]any{}
	}
	input := map[string]any{
		"source_paper_id":    body.SourcePaperID,
		"source_paper_title": body.SourcePaperTitle,
		"entries":            body.Entries,
		"topic_ids":          orSlice(body.TopicIDs),
	}
	jobID, taskID, err := s.submitCoreTask("import_references", input, 3600)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleIngestReferencesStatus GET /ingest/references/status/{task_id}。
func (s *Server) handleIngestReferencesStatus(w http.ResponseWriter, r *http.Request) {
	view, err := s.taskView(r.PathValue("task_id"))
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if view == nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Task not found"})
		return
	}
	writeJSON(w, http.StatusOK, view)
}

// handleGraphAutoLink POST /graph/auto-link —— 提交引用自动关联任务链。
func (s *Server) handleGraphAutoLink(w http.ResponseWriter, r *http.Request) {
	var paperIDs []string
	if err := readBody(r, &paperIDs); err != nil || len(paperIDs) == 0 {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "paper_ids required"})
		return
	}
	submitted := 0
	for _, pid := range paperIDs {
		if _, _, err := s.submitCoreTaskQuiet("sync_citations_paper", map[string]any{
			"paper_id": pid, "limit": 8,
		}, 600); err == nil {
			submitted++
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"submitted": submitted, "total": len(paperIDs)})
}

// handleGetAction GET /actions/{action_id} —— 收集行动详情。
func (s *Server) handleGetAction(w http.ResponseWriter, r *http.Request) {
	actionID := r.PathValue("action_id")
	var id, actionType, title string
	var query sql.NullString
	var topicID sql.NullString
	var paperCount int
	var createdAt string
	err := s.db.QueryRow(
		`SELECT id, action_type, COALESCE(title,''), COALESCE(query,''), topic_id, paper_count,
		        TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')
		 FROM collection_actions WHERE id=$1`, actionID,
	).Scan(&id, &actionType, &title, &query, &topicID, &paperCount, &createdAt)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "行动记录不存在"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	out := map[string]any{
		"id": id, "action_type": actionType, "title": title,
		"query": nullStr(query), "topic_id": nullStr(topicID),
		"paper_count": paperCount, "created_at": createdAt,
	}
	// 关联论文列表
	rows, err := s.db.Query(
		`SELECT p.id, COALESCE(p.title,'') FROM action_papers ap JOIN papers p ON p.id = ap.paper_id
		 WHERE ap.action_id=$1 LIMIT 500`, actionID)
	if err == nil {
		defer rows.Close()
		papers := []map[string]any{}
		for rows.Next() {
			var pid, ptitle string
			if rows.Scan(&pid, &ptitle) == nil {
				papers = append(papers, map[string]any{"id": pid, "title": ptitle})
			}
		}
		out["papers"] = papers
	}
	writeJSON(w, http.StatusOK, out)
}

// handleGetActionPapers GET /actions/{action_id}/papers。
func (s *Server) handleGetActionPapers(w http.ResponseWriter, r *http.Request) {
	actionID := r.PathValue("action_id")
	limit := queryInt(r, "limit", 200)
	rows, err := s.db.Query(
		`SELECT p.id, COALESCE(p.title,''), COALESCE(p.arxiv_id,''), p.read_status
		 FROM action_papers ap JOIN papers p ON p.id = ap.paper_id
		 WHERE ap.action_id=$1 LIMIT $2`, actionID, limit)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, title, arxivID, readStatus string
		if rows.Scan(&id, &title, &arxivID, &readStatus) == nil {
			items = append(items, map[string]any{
				"id": id, "title": title, "arxiv_id": arxivID, "read_status": readStatus,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "total": len(items)})
}

// jsonMarshalSafe 安全序列化（占位引用）。
var _ = json.Marshal

// handleListActionsGo GET /actions —— 收集行动列表（Phase 2 遗漏项，backend 退役后暴露）。
func (s *Server) handleListActionsGo(w http.ResponseWriter, r *http.Request) {
	actionType := r.URL.Query().Get("action_type")
	topicID := r.URL.Query().Get("topic_id")
	limit := queryInt(r, "limit", 50)
	offset := queryInt(r, "offset", 0)
	query := `SELECT id, action_type, COALESCE(title,''), COALESCE(query,''), topic_id, paper_count,
	                 TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"'), COUNT(*) OVER() AS total
	          FROM collection_actions WHERE 1=1`
	args := []any{}
	if actionType != "" {
		args = append(args, actionType)
		query += fmt.Sprintf(" AND action_type=$%d", len(args))
	}
	if topicID != "" {
		args = append(args, topicID)
		query += fmt.Sprintf(" AND topic_id=$%d", len(args))
	}
	args = append(args, limit, offset)
	query += fmt.Sprintf(" ORDER BY created_at DESC LIMIT $%d OFFSET $%d", len(args)-1, len(args))
	rows, err := s.db.Query(query, args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	total := 0
	for rows.Next() {
		var id, aType, title, createdAt string
		var q, topicID sql.NullString
		var paperCount, t int
		if rows.Scan(&id, &aType, &title, &q, &topicID, &paperCount, &createdAt, &t) == nil {
			total = t
			items = append(items, map[string]any{
				"id": id, "action_type": aType, "title": title,
				"query": nullStr(q), "topic_id": nullStr(topicID),
				"paper_count": paperCount, "created_at": createdAt,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "total": total})
}

// handlePaperDistribution GET /topics/distribution —— 年份 + 来源分布。
func (s *Server) handlePaperDistribution(w http.ResponseWriter, r *http.Request) {
	// 年份分布
	yearRows, err := s.db.Query(
		`SELECT COALESCE(TO_CHAR(publication_date,'YYYY'),'unknown') AS yr, COUNT(*)
		 FROM papers GROUP BY yr ORDER BY yr DESC`)
	byYear := []map[string]any{}
	if err == nil {
		for yearRows.Next() {
			var yr string
			var c int
			if yearRows.Scan(&yr, &c) == nil {
				byYear = append(byYear, map[string]any{"year": yr, "count": c})
			}
		}
		yearRows.Close()
	}
	// 来源分布（metadata->>'source' 缺失按 arxiv 计）
	srcRows, err2 := s.db.Query(
		`SELECT COALESCE(metadata->>'source', CASE WHEN source IS NOT NULL AND source != '' THEN source ELSE 'arxiv' END) AS src, COUNT(*)
		 FROM papers GROUP BY src ORDER BY COUNT(*) DESC`)
	bySource := []map[string]any{}
	if err2 == nil {
		for srcRows.Next() {
			var src string
			var c int
			if srcRows.Scan(&src, &c) == nil {
				bySource = append(bySource, map[string]any{"source": src, "count": c})
			}
		}
		srcRows.Close()
	}
	writeJSON(w, http.StatusOK, map[string]any{"by_year": byYear, "by_source": bySource})
}
