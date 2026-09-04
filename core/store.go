// Go-authority 持久化（第三轮 REVIEW P0-2 选 a：SkimPaper 纵向切片）。
//
// Go Core 持有 Job/Task/Attempt 权威状态（core_jobs/core_tasks/core_attempts，
// 与领域表同一 SQLite 文件），apply-result 在**单一事务**内提交：
// 领域变化（analysis_reports/papers/prompt_traces）+ fencing 校验 + Task 终态。
// Python Executor 只返回结构化 proposal——不直写领域表。
//
// 依赖：modernc.org/sqlite（纯 Go，无 cgo）。领域表 schema 由 Python migrations
// 创建；core_* 表由 Go 自建（CREATE TABLE IF NOT EXISTS）。
package core

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"

	_ "github.com/lib/pq"
)

// CoreStore 持有权威 Job/Task/Attempt 状态（SQLite，同一 papermind.db）。
type CoreStore struct {
	DB *sql.DB
}

// OpenCoreStore 打开 PostgreSQL 权威存储（PG 并发安全，无需单连接限制）。
func OpenCoreStore(pgDSN string) (*CoreStore, error) {
	db, err := sql.Open("postgres", pgDSN)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	s := &CoreStore{DB: db}
	if err := s.initSchema(); err != nil {
		db.Close()
		return nil, err
	}
	return s, nil
}

func (s *CoreStore) Close() error { return s.DB.Close() }

func (s *CoreStore) initSchema() error {
	_, err := s.DB.Exec(`
CREATE TABLE IF NOT EXISTS core_jobs (
	id TEXT PRIMARY KEY,
	kind TEXT NOT NULL,
	capability TEXT NOT NULL,
	payload JSONB NOT NULL DEFAULT '{}',
	idempotency_key TEXT UNIQUE,
	status TEXT NOT NULL DEFAULT 'queued',
	created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
	started_at TIMESTAMPTZ,
	finished_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS core_tasks (
	id TEXT PRIMARY KEY,
	job_id TEXT NOT NULL REFERENCES core_jobs(id),
	capability TEXT NOT NULL,
	input_ref JSONB NOT NULL DEFAULT '{}',
	status TEXT NOT NULL DEFAULT 'queued',
	attempt_count INTEGER NOT NULL DEFAULT 0,
	max_attempts INTEGER NOT NULL DEFAULT 3,
	timeout_s INTEGER NOT NULL DEFAULT 600,
	lease_token TEXT,
	lease_expires_at TIMESTAMPTZ,
	last_error TEXT,
	result_ref JSONB,
	seq INTEGER NOT NULL DEFAULT 0,
	created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_core_tasks_job ON core_tasks(job_id, status);
CREATE TABLE IF NOT EXISTS core_attempts (
	id TEXT PRIMARY KEY,
	task_id TEXT NOT NULL REFERENCES core_tasks(id),
	attempt_no INTEGER NOT NULL,
	executor_id TEXT NOT NULL,
	fencing_token INTEGER NOT NULL,
	status TEXT NOT NULL DEFAULT 'running',
	error_class TEXT,
	error_message TEXT,
	started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
	finished_at TIMESTAMPTZ
);`)
	return err
}

func nowISO() string { return time.Now().UTC().Format(time.RFC3339Nano) }

// sqliteTime：SQLite NOW() 同格式（ReclaimExpired 的字符串比较依赖一致性）
func sqliteTime() string { return time.Now().UTC().Format("2006-01-02 15:04:05") }

func sqliteTimePlus(seconds int) string {
	return time.Now().UTC().Add(time.Duration(seconds) * time.Second).Format("2006-01-02 15:04:05")
}

func newCoreID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func mustJSON(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return "{}"
	}
	return string(b)
}

func nullIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// ---------- Job/Task 创建（skim 切片：单任务 Job） ----------

// SubmitCoreTask 创建单任务 Job（通用：capability + input_ref）。幂等：idempotency_key。
// 仅接受已迁移到 Go authority 的 capability（白名单见 server handleSubmitJob）。
func (s *CoreStore) SubmitCoreTask(capability, inputRefJSON, idempotencyKey string, timeoutS int) (jobID, taskID string, created bool, err error) {
	if timeoutS <= 0 {
		timeoutS = 1800
	}
	now := nowISO()
	if idempotencyKey != "" {
		var existingJob, existingTask string
		err = s.DB.QueryRow(
			`SELECT j.id, t.id FROM core_jobs j JOIN core_tasks t ON t.job_id = j.id
			 WHERE j.idempotency_key = ? LIMIT 1`, idempotencyKey,
		).Scan(&existingJob, &existingTask)
		if err == nil {
			return existingJob, existingTask, false, nil
		}
		if err != sql.ErrNoRows {
			return "", "", false, err
		}
	}

	jobID, taskID = newCoreID(), newCoreID()
	tx, err := s.DB.Begin()
	if err != nil {
		return "", "", false, err
	}
	defer tx.Rollback()

	jobKind := "CoreTask"
	if capability == "skim_paper" {
		jobKind = "SkimPaper"
	} else if capability == "deep_read_paper" {
		jobKind = "StartDeepRead"
	} else if capability == "embed_paper" {
		jobKind = "StartEmbedding"
	}
	if _, err = tx.Exec(
		`INSERT INTO core_jobs (id, kind, capability, payload, idempotency_key, status, created_at)
		 VALUES (?, ?, ?, ?, ?, 'queued', ?)`,
		jobID, jobKind, capability, inputRefJSON, nullIfEmpty(idempotencyKey), now,
	); err != nil {
		return "", "", false, err
	}
	if _, err = tx.Exec(
		`INSERT INTO core_tasks (id, job_id, capability, input_ref, status, max_attempts, timeout_s, created_at)
		 VALUES (?, ?, ?, ?, 'queued', 2, ?, ?)`,
		taskID, jobID, capability, inputRefJSON, timeoutS, now,
	); err != nil {
		return "", "", false, err
	}
	return jobID, taskID, true, tx.Commit()
}

// ---------- Claim（CAS：queued → leased，attempt 即 fencing token） ----------

// ClaimTask 领取一个 queued 的 skim 任务：签发 lease + attempt + fencing。
// 无可领取任务（或 capability 不匹配）返回 nil。
func (s *CoreStore) ClaimTask(executorID string, capabilities []string) (*Task, error) {
	want := map[string]bool{}
	for _, c := range capabilities {
		want[c] = true
	}
	// 跨进程 pause：system_flags 与 Python durable 共用同一 DB——Go claim 同样遵守
	var paused string
	if err := s.DB.QueryRow(`SELECT value FROM system_flags WHERE key='queue_paused'`).Scan(&paused); err == nil && paused == "1" {
		return nil, nil
	}
	rows, err := s.DB.Query(
		`SELECT id, capability, timeout_s FROM core_tasks WHERE status='queued' ORDER BY created_at LIMIT 10`)
	if err != nil {
		return nil, err
	}
	type candidate struct {
		id         string
		capability string
		timeoutS   int
	}
	var candidates []candidate
	for rows.Next() {
		var c candidate
		if err = rows.Scan(&c.id, &c.capability, &c.timeoutS); err != nil {
			rows.Close()
			return nil, err
		}
		if !want[c.capability] {
			continue
		}
		candidates = append(candidates, c)
	}
	rows.Close()

	for _, c := range candidates {
		leaseToken := newCoreID() // Go 侧生成并回传 Executor（fencing 凭证）
		var fencing int
		err = s.DB.QueryRow(
			`UPDATE core_tasks SET status='leased', attempt_count=attempt_count+1,
			 lease_token=?, lease_expires_at=?
			 WHERE id=? AND status='queued'
			 RETURNING attempt_count`,
			leaseToken, sqliteTimePlus(c.timeoutS), c.id,
		).Scan(&fencing)
		if err == sql.ErrNoRows {
			continue // 被并发领取——尝试下一个
		}
		if err != nil {
			return nil, err
		}
		var jobID string
		if err = s.DB.QueryRow(`SELECT job_id FROM core_tasks WHERE id=?`, c.id).Scan(&jobID); err != nil {
			return nil, err
		}
		tx, err := s.DB.Begin()
		if err != nil {
			return nil, err
		}
		defer tx.Rollback()
		attemptID := newCoreID()
		now := nowISO()
		if _, err = tx.Exec(
			`INSERT INTO core_attempts (id, task_id, attempt_no, executor_id, fencing_token, status, started_at)
			 VALUES (?, ?, ?, ?, ?, 'running', ?)`,
			attemptID, c.id, fencing, executorID, fencing, now,
		); err != nil {
			return nil, err
		}
		if _, err = tx.Exec(
			`UPDATE core_jobs SET status='running', started_at=COALESCE(started_at, ?) WHERE id=? AND status='queued'`,
			now, jobID,
		); err != nil {
			return nil, err
		}
		if err = tx.Commit(); err != nil {
			return nil, err
		}

		var inputJSON string
		if err = s.DB.QueryRow(`SELECT input_ref FROM core_tasks WHERE id=?`, c.id).Scan(&inputJSON); err != nil {
			return nil, err
		}
		var input map[string]any
		_ = json.Unmarshal([]byte(inputJSON), &input)
		return &Task{
			TaskID:        c.id,
			AttemptID:     fmt.Sprintf("%s:%d", c.id, fencing),
			Capability:    c.capability,
			Input:         input,
			ResourceClass: "llm",
			TimeoutS:      c.timeoutS,
			AttemptNo:     fencing,
			FencingToken:  fencing,
			LeaseToken:    leaseToken,
		}, nil
	}
	return nil, nil
}

// ---------- Job graph（观察面） ----------

// JobGraph 返回 Job + Tasks 快照（core 表）。
func (s *CoreStore) JobGraph(jobID string) (map[string]any, error) {
	var kind, status, payload string
	var createdAt sql.NullString
	err := s.DB.QueryRow(
		`SELECT kind, status, payload, created_at FROM core_jobs WHERE id=?`, jobID,
	).Scan(&kind, &status, &payload, &createdAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.Query(
		`SELECT id, capability, status, attempt_count, max_attempts, last_error
		 FROM core_tasks WHERE job_id=? ORDER BY seq, created_at`, jobID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	tasks := []map[string]any{}
	for rows.Next() {
		var id, capability, status string
		var attemptCount, maxAttempts int
		var lastError sql.NullString
		if err = rows.Scan(&id, &capability, &status, &attemptCount, &maxAttempts, &lastError); err != nil {
			return nil, err
		}
		le := ""
		if lastError.Valid {
			le = lastError.String
		}
		tasks = append(tasks, map[string]any{
			"id": id, "capability": capability, "status": status,
			"attempt_count": attemptCount, "max_attempts": maxAttempts,
			"last_error": le,
		})
	}
	attempts := []map[string]any{}
	aRows, err := s.DB.Query(
		`SELECT a.id, a.task_id, a.attempt_no, a.executor_id, a.status, a.started_at, a.finished_at
		 FROM core_attempts a JOIN core_tasks t ON t.id = a.task_id WHERE t.job_id=? ORDER BY a.started_at`, jobID,
	)
	if err == nil {
		for aRows.Next() {
			var id, taskID, executorID, aStatus, startedAt string
			var finishedAt sql.NullString
			var attemptNo int
			if err = aRows.Scan(&id, &taskID, &attemptNo, &executorID, &aStatus, &startedAt, &finishedAt); err == nil {
				fin := ""
				if finishedAt.Valid {
					fin = finishedAt.String
				}
				attempts = append(attempts, map[string]any{
					"id": id, "task_id": taskID, "attempt_no": attemptNo,
					"executor_id": executorID, "status": aStatus,
					"started_at": startedAt, "finished_at": fin,
				})
			}
		}
		aRows.Close()
	}
	var payloadAny map[string]any
	_ = json.Unmarshal([]byte(payload), &payloadAny)
	return map[string]any{
		"id": jobID, "kind": kind, "status": status,
		"payload": payloadAny, "tasks": tasks, "attempts": attempts, "authority": "go_core",
	}, nil
}

// ---------- 领域查询（Web API 路由用——database/sql 直查 PG）----------

// GetPaper 查询单篇论文。
func (s *CoreStore) GetPaper(paperID string) (map[string]any, error) {
	row := s.DB.QueryRow(
		`SELECT id, title, arxiv_id, abstract, read_status, metadata, pdf_path, created_at
		 FROM papers WHERE id=$1`, paperID)
	var id, title, readStatus string
	var arxivID, abstract, pdfPath sql.NullString
	var metadata []byte
	var createdAt time.Time
	if err := row.Scan(&id, &title, &arxivID, &abstract, &readStatus, &metadata, &pdfPath, &createdAt); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, err
	}
	meta := map[string]any{}
	_ = json.Unmarshal(metadata, &meta)
	return map[string]any{
		"id": id, "title": title, "arxiv_id": arxivID.String,
		"abstract": abstract.String, "read_status": readStatus,
		"metadata_json": meta, "pdf_path": pdfPath.String,
		"created_at": createdAt.Format(time.RFC3339),
	}, nil
}

// ListPapers 查询论文列表。
func (s *CoreStore) ListPapers(limit, offset int) ([]map[string]any, error) {
	rows, err := s.DB.Query(
		`SELECT id, title, arxiv_id, abstract, read_status, created_at
		 FROM papers ORDER BY created_at DESC LIMIT $1 OFFSET $2`, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, title, readStatus string
		var arxivID, abstract sql.NullString
		var createdAt time.Time
		if err = rows.Scan(&id, &title, &arxivID, &abstract, &readStatus, &createdAt); err != nil {
			return nil, err
		}
		items = append(items, map[string]any{
			"id": id, "title": title, "arxiv_id": arxivID.String,
			"abstract": abstract.String, "read_status": readStatus,
			"created_at": createdAt.Format(time.RFC3339),
		})
	}
	return items, nil
}

// SearchPapers 按关键词搜索论文。
func (s *CoreStore) SearchPapers(query string, limit int) ([]map[string]any, error) {
	pattern := "%" + query + "%"
	rows, err := s.DB.Query(
		`SELECT id, title, arxiv_id, abstract, read_status, created_at
		 FROM papers WHERE LOWER(title) LIKE LOWER($1) OR LOWER(abstract) LIKE LOWER($1)
		 ORDER BY created_at DESC LIMIT $2`, pattern, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, title, readStatus string
		var arxivID, abstract sql.NullString
		var createdAt time.Time
		if err = rows.Scan(&id, &title, &arxivID, &abstract, &readStatus, &createdAt); err != nil {
			return nil, err
		}
		items = append(items, map[string]any{
			"id": id, "title": title, "arxiv_id": arxivID.String,
			"abstract": abstract.String, "read_status": readStatus,
			"created_at": createdAt.Format(time.RFC3339),
		})
	}
	return items, nil
}

// GetResearchQuestion 查询研究问题。
func (s *CoreStore) GetResearchQuestion(qID string) (map[string]any, error) {
	row := s.DB.QueryRow(
		`SELECT id, title, question, status, created_at, updated_at
		 FROM research_questions WHERE id=$1`, qID)
	var id, title, question, status string
	var createdAt, updatedAt time.Time
	if err := row.Scan(&id, &title, &question, &status, &createdAt, &updatedAt); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, err
	}
	return map[string]any{
		"id": id, "title": title, "question": question,
		"status": status, "created_at": createdAt.Format(time.RFC3339),
		"updated_at": updatedAt.Format(time.RFC3339),
	}, nil
}

// ListClaims 查询研究问题下的 claims。
func (s *CoreStore) ListClaims(questionID string, statuses []string) ([]map[string]any, error) {
	query := `SELECT id, statement, statement_zh, origin, status, certainty, run_id
	          FROM claims WHERE research_question_id=$1`
	args := []any{questionID}
	if len(statuses) > 0 {
		query += ` AND status = ANY($2)`
		args = append(args, statuses)
	}
	query += ` ORDER BY created_at DESC`
	rows, err := s.DB.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, statement, origin, status string
		var statementZh, certainty, runID sql.NullString
		if err = rows.Scan(&id, &statement, &statementZh, &origin, &status, &certainty, &runID); err != nil {
			return nil, err
		}
		items = append(items, map[string]any{
			"id": id, "statement": statement, "statement_zh": statementZh.String,
			"origin": origin, "status": status,
			"certainty": certainty.String, "run_id": runID.String,
		})
	}
	return items, nil
}

// GetClaimEvidence 查询单条 claim 的全部证据。
func (s *CoreStore) GetClaimEvidence(claimID string) ([]map[string]any, error) {
	rows, err := s.DB.Query(
		`SELECT id, source_version_id, kind, stance, locator, quote, fingerprint
		 FROM evidence WHERE claim_id=$1`, claimID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, svID, kind, stance, fingerprint string
		var locator json.RawMessage
		var quote sql.NullString
		if err = rows.Scan(&id, &svID, &kind, &stance, &locator, &quote, &fingerprint); err != nil {
			return nil, err
		}
		items = append(items, map[string]any{
			"id": id, "source_version_id": svID, "kind": kind, "stance": stance,
			"locator": json.RawMessage(locator), "quote": quote.String, "fingerprint": fingerprint,
		})
	}
	return items, nil
}

// GetResearchDiff 查询研究状态变更时间线。
func (s *CoreStore) GetResearchDiff(questionID string) ([]map[string]any, error) {
	rows, err := s.DB.Query(
		`SELECT re.id, re.type, re.aggregate_id, re.actor, re.payload, re.occurred_at
		 FROM research_events re
		 JOIN claims c ON c.id = re.aggregate_id
		 WHERE c.research_question_id = $1 AND re.type IN (
		   'claim_proposed','claim_confirmed','claim_revised',
		   'claim_invalidated','evidence_extracted')
		 ORDER BY re.occurred_at DESC`, questionID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, evType, aggID, actor, occurredAt string
		var payload json.RawMessage
		if err = rows.Scan(&id, &evType, &aggID, &actor, &payload, &occurredAt); err != nil {
			return nil, err
		}
		items = append(items, map[string]any{
			"id": id, "diff_kind": evType, "aggregate_id": aggID,
			"actor": actor, "payload": json.RawMessage(payload),
			"occurred_at": occurredAt,
		})
	}
	return items, nil
}
