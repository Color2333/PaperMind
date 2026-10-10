package main

// jobs.go：任务/队列管理（Phase 2）——与 apps/api/routers/jobs.py 逐契约对齐。
// Go Core 本身拥有 Job/Task/Attempt 权威数据——大部分端点直接查 PG core_jobs/core_tasks。

import (
	core "github.com/Color2333/PaperMind/core"
	"encoding/json"
	"net/http"
)

// handleListJobs：GET /jobs。
func (s *Server) handleListJobs(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	status := q.Get("status")
	kind := q.Get("kind")
	limit := atoiOr(q.Get("limit"), 50)
	if limit < 1 || limit > 200 {
		limit = 50
	}

	where := "1=1"
	args := []any{}
	argN := 0
	addArg := func(v any) string {
		argN++
		args = append(args, v)
		return "$" + itoa(argN)
	}
	if status != "" {
		where += " AND status = " + addArg(status)
	}
	if kind != "" {
		where += " AND kind = " + addArg(kind)
	}

	rows, err := s.db.Query(
		`SELECT id, kind, capability, status, created_at::text
		 FROM core_jobs WHERE `+where+` ORDER BY created_at DESC LIMIT `+itoa(limit), args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()

	items := []map[string]any{}
	for rows.Next() {
		var id, kind, capability, jobStatus, createdAt string
		if err := rows.Scan(&id, &kind, &capability, &jobStatus, &createdAt); err != nil {
			continue
		}
		items = append(items, map[string]any{
			"id": id, "kind": kind, "capability": capability,
			"status": jobStatus, "created_at": createdAt,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

// handleGetJob：GET /jobs/{job_id} —— Job graph + 子 Task + Attempt 概览。
func (s *Server) handleGetJob(w http.ResponseWriter, r *http.Request) {
	jobID := r.PathValue("job_id")
	var jid, kind, capability, jobStatus, createdAt string
	var payload string
	err := s.db.QueryRow(
		`SELECT id, kind, capability, status, created_at::text, payload::text
		 FROM core_jobs WHERE id=$1`, jobID,
	).Scan(&jid, &kind, &capability, &jobStatus, &createdAt, &payload)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Job " + jobID + " not found"})
		return
	}

	attempts := []map[string]any{}
	attemptRows, err := s.db.Query(
		`SELECT a.id, a.task_id, a.attempt_no, a.executor_id, a.status,
			COALESCE(a.error_class,''), COALESCE(a.error_message,''), a.started_at::text,
			COALESCE(TO_CHAR(a.finished_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"'),'')
		 FROM core_attempts a JOIN core_tasks t ON t.id = a.task_id
		 WHERE t.job_id=$1 ORDER BY a.started_at DESC LIMIT 200`, jobID)
	if err == nil {
		for attemptRows.Next() {
			var aid, tid, executor, aStatus, started, finished, errClass, errMsg string
			var attemptNo int
			if err := attemptRows.Scan(&aid, &tid, &attemptNo, &executor, &aStatus,
				&errClass, &errMsg, &started, &finished); err == nil {
				attempts = append(attempts, map[string]any{
					"id": aid, "task_id": tid, "attempt_no": attemptNo,
					"executor_id": executor, "status": aStatus,
					"error_class": errClass, "error_message": errMsg,
					"started_at": started, "finished_at": finished,
				})
			}
		}
		attemptRows.Close()
	}

	tasks := []map[string]any{}
	taskRows, err := s.db.Query(
		`SELECT id, capability, status, attempt_count, max_attempts,
			COALESCE(last_error,''), created_at::text
		 FROM core_tasks WHERE job_id=$1 ORDER BY seq`, jobID)
	if err == nil {
		defer taskRows.Close()
		for taskRows.Next() {
			var tid, cap_, tStatus, tCreatedAt string
			var attemptCount, maxAttempts int
			var lastErr string
			if err := taskRows.Scan(&tid, &cap_, &tStatus, &attemptCount, &maxAttempts, &lastErr, &tCreatedAt); err != nil {
				continue
			}
			tasks = append(tasks, map[string]any{
				"id": tid, "capability": cap_, "status": tStatus,
				"attempt_count": attemptCount, "max_attempts": maxAttempts,
				"last_error": lastErr, "created_at": tCreatedAt,
			})
		}
	}

	var payloadObj any
	json.Unmarshal([]byte(payload), &payloadObj)
	writeJSON(w, http.StatusOK, map[string]any{
		"id": jid, "kind": kind, "capability": capability, "status": jobStatus,
		"created_at": createdAt, "payload": payloadObj, "tasks": tasks, "attempts": attempts,
	})
}

// handleSubmitDurable：POST /jobs/durable —— 权威提交入口。
func (s *Server) handleSubmitDurable(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Kind           string         `json:"kind"`
		Capability     string         `json:"capability"`
		Title          string         `json:"title"`
		InputRef       map[string]any `json:"input_ref"`
		Payload        map[string]any `json:"payload"`
		IdempotencyKey *string        `json:"idempotency_key"`
		ResourceClass  string         `json:"resource_class"`
		TimeoutS       int            `json:"timeout_s"`
		MaxAttempts    int            `json:"max_attempts"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "bad json"})
		return
	}
	if body.Capability == "" || body.Kind == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "kind and capability are required"})
		return
	}
	if body.TimeoutS <= 0 {
		body.TimeoutS = 1800
	}
	if body.MaxAttempts <= 0 {
		body.MaxAttempts = 1
	}
	inputRef, _ := json.Marshal(body.InputRef)
	var idempotency *string
	if body.IdempotencyKey != nil && *body.IdempotencyKey != "" {
		idempotency = body.IdempotencyKey
	}
	jobID, taskID, err := s.submitCoreTask(body.Capability, body.InputRef, body.TimeoutS)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": err.Error()})
		return
	}
	_ = inputRef
	_ = idempotency
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID, "task_id": taskID})
}

// handleCancelJob：POST /jobs/{id}/cancel。
func (s *Server) handleCancelJob(w http.ResponseWriter, r *http.Request) {
	jobID := r.PathValue("job_id")
	// R09：复用 CoreStore.CancelJob 权威状态机——leased 子任务进入 cancelling，
	// Runner 心跳探测到 cancel_requested 后安全点退出，而不是只取消 queued。
	store := &core.CoreStore{DB: s.db, IsPG: true}
	counts, err := store.CancelJob(jobID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, counts)
}

// handleRetryJob：POST /jobs/{id}/retry。
func (s *Server) handleRetryJob(w http.ResponseWriter, r *http.Request) {
	jobID := r.PathValue("job_id")
	res, err := s.db.Exec(
		`UPDATE core_tasks SET status='queued', attempt_count=0, last_error=NULL, lease_token=NULL
		 WHERE job_id=$1 AND status IN ('dead_letter','failed')`, jobID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	n, _ := res.RowsAffected()
	_, _ = s.db.Exec(
		`UPDATE core_jobs SET status='running', finished_at=NULL WHERE id=$1 AND status IN ('failed','cancelled')`, jobID)
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID, "retried": n})
}

// handleRetryTask：POST /tasks/{task_id}/retry。
func (s *Server) handleRetryTask(w http.ResponseWriter, r *http.Request) {
	taskID := r.PathValue("task_id")
	var status string
	if err := s.db.QueryRow("SELECT status FROM core_tasks WHERE id=$1", taskID).Scan(&status); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "task not found"})
		return
	}
	if status != "dead_letter" && status != "failed" {
		writeJSON(w, http.StatusConflict, map[string]string{"detail": "仅 dead_letter/failed 任务可重试"})
		return
	}
	_, err := s.db.Exec(
		`UPDATE core_tasks SET status='queued', attempt_count=0, last_error=NULL, lease_token=NULL
		 WHERE id=$1`, taskID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"task_id": taskID, "status": "queued"})
}

// handlePauseQueue / handleResumeQueue：队列暂停/恢复（system_flags 持久化）。
func (s *Server) handlePauseQueue(w http.ResponseWriter, r *http.Request) {
	_, _ = s.db.Exec(
		`INSERT INTO system_flags (key, value, updated_at) VALUES ('queue_paused', '1', now()::timestamp) ON CONFLICT (key) DO UPDATE SET value='1', updated_at=now()::timestamp
		 ON CONFLICT (key) DO UPDATE SET value='true', updated_at=now()::timestamp`)
	writeJSON(w, http.StatusOK, map[string]bool{"paused": true})
}

func (s *Server) handleResumeQueue(w http.ResponseWriter, r *http.Request) {
	_, _ = s.db.Exec(
		`INSERT INTO system_flags (key, value, updated_at) VALUES ('queue_paused', '0', now()::timestamp) ON CONFLICT (key) DO UPDATE SET value='0', updated_at=now()::timestamp
		 ON CONFLICT (key) DO UPDATE SET value='false', updated_at=now()::timestamp`)
	writeJSON(w, http.StatusOK, map[string]bool{"paused": false})
}
