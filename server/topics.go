package main

// topics.go：主题订阅 CRUD + 摄入（Phase 2）——与
// apps/api/routers/topics.py 逐契约对齐。

import (
	"encoding/json"
	"net/http"
	"strings"
)

// handleListTopics：GET /topics。
func (s *Server) handleListTopics(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	enabledOnly := q.Get("enabled_only") == "true"
	failed := q.Get("failed") == "true"

	where := "1=1"
	if enabledOnly {
		where += " AND enabled = true"
	}
	if failed {
		where += " AND last_error IS NOT NULL AND last_error != ''"
	}

	rows, err := s.db.Query(
		`SELECT t.id, t.name, t.query, t.enabled, t.max_results_per_run, t.retry_limit,
			COALESCE(t.schedule_frequency,'daily'), COALESCE(t.schedule_time_utc,21),
			COALESCE(t.enable_date_filter,false), COALESCE(t.date_filter_days,7),
			TO_CHAR(t.last_run_at AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), COALESCE(t.last_error,''),
			(SELECT COUNT(*) FROM paper_topics pt WHERE pt.topic_id = t.id) AS paper_count,
			(SELECT COALESCE(TO_CHAR(MAX(ca.created_at) AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),'') FROM collection_actions ca WHERE ca.topic_id = t.id) AS last_action_at,
			(SELECT COALESCE(MAX(ca.paper_count),0) FROM collection_actions ca WHERE ca.topic_id = t.id) AS last_run_count
		 FROM topic_subscriptions t WHERE ` + where + ` ORDER BY t.created_at`)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()

	items := []map[string]any{}
	for rows.Next() {
		var id, name, query, scheduleFreq string
		var enabled bool
		var maxResults, retryLimit, scheduleTime, dateFilterDays, paperCount, lastRunCount int
		var lastRunAt, lastError, lastActionAt *string
		var enableDateFilter bool
		if err := rows.Scan(&id, &name, &query, &enabled, &maxResults, &retryLimit,
			&scheduleFreq, &scheduleTime, &enableDateFilter, &dateFilterDays,
			&lastRunAt, &lastError, &paperCount, &lastActionAt, &lastRunCount); err != nil {
			continue
		}
		items = append(items, map[string]any{
			"id": id, "name": name, "query": query, "enabled": enabled,
			"max_results_per_run": maxResults, "retry_limit": retryLimit,
			"schedule_frequency": scheduleFreq, "schedule_time_utc": scheduleTime,
			"enable_date_filter": enableDateFilter, "date_filter_days": dateFilterDays,
			"paper_count": paperCount, "last_run_at": jsonStrOrNull(lastRunAt),
			"last_error": jsonStrOrNull(lastError), "last_run_count": lastRunCount,
			"last_action_at": lastActionAt,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

// handleUpsertTopic：POST /topics。
func (s *Server) handleUpsertTopic(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Name             string `json:"name"`
		Query            string `json:"query"`
		Enabled          *bool  `json:"enabled"`
		MaxResultsPerRun *int   `json:"max_results_per_run"`
		RetryLimit       *int   `json:"retry_limit"`
		ScheduleFreq     string `json:"schedule_frequency"`
		ScheduleTimeUTC  *int   `json:"schedule_time_utc"`
		EnableDateFilter *bool  `json:"enable_date_filter"`
		DateFilterDays   *int   `json:"date_filter_days"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "bad json"})
		return
	}
	if body.Name == "" || body.Query == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "name and query are required"})
		return
	}
	enabled := true
	if body.Enabled != nil {
		enabled = *body.Enabled
	}
	maxResults := 20
	if body.MaxResultsPerRun != nil {
		maxResults = *body.MaxResultsPerRun
	}
	retryLimit := 2
	if body.RetryLimit != nil {
		retryLimit = *body.RetryLimit
	}
	scheduleFreq := body.ScheduleFreq
	if scheduleFreq == "" {
		scheduleFreq = "daily"
	}
	scheduleTime := 21
	if body.ScheduleTimeUTC != nil {
		scheduleTime = *body.ScheduleTimeUTC
	}
	enableDateFilter := false
	if body.EnableDateFilter != nil {
		enableDateFilter = *body.EnableDateFilter
	}
	dateFilterDays := 7
	if body.DateFilterDays != nil {
		dateFilterDays = *body.DateFilterDays
	}

	var id string
	err := s.db.QueryRow(
		`INSERT INTO topic_subscriptions (id, name, query, enabled, max_results_per_run, retry_limit,
			schedule_frequency, schedule_time_utc, enable_date_filter, date_filter_days, created_at, updated_at)
		 VALUES (gen_random_uuid()::text, $1, $2, $3, $4, $5, $6, $7, $8, $9, now()::timestamp, now()::timestamp)
		 ON CONFLICT (name) DO UPDATE SET query=$2, enabled=$3, max_results_per_run=$4, retry_limit=$5,
			schedule_frequency=$6, schedule_time_utc=$7, enable_date_filter=$8, date_filter_days=$9,
			updated_at=now()::timestamp
		 RETURNING id`,
		body.Name, body.Query, enabled, maxResults, retryLimit,
		scheduleFreq, scheduleTime, enableDateFilter, dateFilterDays,
	).Scan(&id)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": id, "name": body.Name, "query": body.Query, "enabled": enabled})
}

// handleUpdateTopic：PATCH /topics/{id}。
func (s *Server) handleUpdateTopic(w http.ResponseWriter, r *http.Request) {
	topicID := r.PathValue("topic_id")
	var body struct {
		Query            *string `json:"query"`
		Enabled          *bool   `json:"enabled"`
		MaxResultsPerRun *int    `json:"max_results_per_run"`
		RetryLimit       *int    `json:"retry_limit"`
		ScheduleFreq     *string `json:"schedule_frequency"`
		ScheduleTimeUTC  *int    `json:"schedule_time_utc"`
		EnableDateFilter *bool   `json:"enable_date_filter"`
		DateFilterDays   *int    `json:"date_filter_days"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "bad json"})
		return
	}
	sets := []string{"updated_at=now()::timestamp"}
	args := []any{}
	argN := 0
	addSet := func(col string, val any) {
		argN++
		sets = append(sets, col+"=$"+itoa(argN))
		args = append(args, val)
	}
	if body.Query != nil {
		addSet("query", *body.Query)
	}
	if body.Enabled != nil {
		addSet("enabled", *body.Enabled)
	}
	if body.MaxResultsPerRun != nil {
		addSet("max_results_per_run", *body.MaxResultsPerRun)
	}
	if body.RetryLimit != nil {
		addSet("retry_limit", *body.RetryLimit)
	}
	if body.ScheduleFreq != nil {
		addSet("schedule_frequency", *body.ScheduleFreq)
	}
	if body.ScheduleTimeUTC != nil {
		addSet("schedule_time_utc", *body.ScheduleTimeUTC)
	}
	if body.EnableDateFilter != nil {
		addSet("enable_date_filter", *body.EnableDateFilter)
	}
	if body.DateFilterDays != nil {
		addSet("date_filter_days", *body.DateFilterDays)
	}
	args = append(args, topicID)
	res, err := s.db.Exec(
		"UPDATE topic_subscriptions SET "+strings.Join(sets, ", ")+" WHERE id=$"+itoa(len(args)),
		args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "主题不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"id": topicID, "status": "updated"})
}

// handleDeleteTopic：DELETE /topics/{id}。
func (s *Server) handleDeleteTopic(w http.ResponseWriter, r *http.Request) {
	res, err := s.db.Exec("DELETE FROM topic_subscriptions WHERE id=$1", r.PathValue("topic_id"))
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "主题不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
}

// handleManualFetchTopic：POST /topics/{id}/fetch —— 提交 fetch_topic_papers 任务。
func (s *Server) handleManualFetchTopic(w http.ResponseWriter, r *http.Request) {
	topicID := r.PathValue("topic_id")
	var name string
	if err := s.db.QueryRow(
		"SELECT name FROM topic_subscriptions WHERE id=$1", topicID,
	).Scan(&name); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "主题不存在"})
		return
	}
	jobID, taskID, err := s.submitCoreTask("fetch_topic_papers", map[string]any{"topic_id": topicID}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID, "task_id": taskID, "status": "started"})
}

// handleTopicStats：GET /topics/stats。
func (s *Server) handleTopicStats(w http.ResponseWriter, r *http.Request) {
	// 契约：TopicStatsResponse{topics:[TopicStats{topic_id,topic_name,paper_count,total_citations,recent_30d,status_dist}]}
	rows, err := s.db.Query(
		`SELECT ts.id, ts.name, COUNT(DISTINCT pt.paper_id),
			COALESCE((SELECT COUNT(*) FROM citations c
			  JOIN paper_topics pt2 ON pt2.paper_id = c.source_paper_id
			  WHERE pt2.topic_id = ts.id), 0) AS total_citations,
			COALESCE((SELECT COUNT(*) FROM paper_topics pt3 JOIN papers p3 ON p3.id = pt3.paper_id
			  WHERE pt3.topic_id = ts.id AND p3.created_at >= NOW() - INTERVAL '30 days'), 0)
		 FROM topic_subscriptions ts
		 LEFT JOIN paper_topics pt ON pt.topic_id = ts.id
		 GROUP BY ts.id, ts.name ORDER BY COUNT(DISTINCT pt.paper_id) DESC`)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	topics := []map[string]any{}
	ids := []string{}
	for rows.Next() {
		var id, name string
		var paperCount, citations, recent int
		if err := rows.Scan(&id, &name, &paperCount, &citations, &recent); err != nil {
			continue
		}
		ids = append(ids, id)
		topics = append(topics, map[string]any{
			"topic_id": id, "topic_name": name, "paper_count": paperCount,
			"total_citations": citations, "recent_30d": recent,
			"status_dist": map[string]int{"unread": 0, "skimmed": 0, "deep_read": 0},
		})
	}
	rows.Close()
	// 每主题的阅读状态分布
	for _, t := range topics {
		tid := t["topic_id"].(string)
		sd := map[string]int{"unread": 0, "skimmed": 0, "deep_read": 0}
		srows, err := s.db.Query(
			`SELECT p.read_status, COUNT(*) FROM papers p
			 JOIN paper_topics pt ON pt.paper_id = p.id
			 WHERE pt.topic_id=$1 GROUP BY p.read_status`, tid)
		if err == nil {
			for srows.Next() {
				var rs string
				var c int
				if srows.Scan(&rs, &c) == nil {
					if _, ok := sd[rs]; ok {
						sd[rs] = c
					}
				}
			}
			srows.Close()
			t["status_dist"] = sd
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"topics": topics})
}

// handleIngestArxiv：POST /ingest/arxiv —— 提交 ingest_arxiv_query 任务到 Go Core。
func (s *Server) handleIngestArxiv(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	query := q.Get("query")
	if query == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "query required"})
		return
	}
	maxResults := atoiOr(q.Get("max_results"), 20)
	topicID := q.Get("topic_id")
	sortBy := q.Get("sort_by")
	if sortBy == "" {
		sortBy = "submittedDate"
	}
	daysBack := atoiOr(q.Get("days_back"), 0)
	inputRef := map[string]any{
		"query": query, "max_results": maxResults,
		"sort_by": sortBy, "days_back": daysBack,
	}
	if topicID != "" {
		inputRef["topic_id"] = topicID
	}
	jobID, taskID, err := s.submitCoreTask("ingest_arxiv_query", inputRef, 900)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID})
}
