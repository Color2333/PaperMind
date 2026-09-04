// Go-authority 持久化（P0-2 选 a：SkimPaper 切片 + 全量路由）。
//
// 双驱动：PostgreSQL（生产）或 SQLite（本地测试/开发）。
// DSN 含 "postgres" 或 "host=" 时用 PG，否则视为 SQLite 文件路径。
package core

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	_ "github.com/lib/pq"
	_ "modernc.org/sqlite"
)

// CoreStore 持有权威 Job/Task/Attempt 状态 + 领域查询。
type CoreStore struct {
	DB   *sql.DB
	isPG bool
}

// OpenCoreStore 打开权威存储——双驱动。
func OpenCoreStore(dsn string) (*CoreStore, error) {
	var db *sql.DB
	var err error
	if isPGDSN(dsn) {
		db, err = sql.Open("postgres", dsn)
		if err != nil {
			return nil, err
		}
		db.SetMaxOpenConns(10)
		db.SetMaxIdleConns(5)
	} else {
		db, err = sql.Open("sqlite", fmt.Sprintf(
			"file:%s?_pragma=busy_timeout(10000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(0)", dsn))
		if err != nil {
			return nil, err
		}
		db.SetMaxOpenConns(1)
	}
	s := &CoreStore{DB: db, isPG: isPGDSN(dsn)}
	if err := s.initSchema(); err != nil {
		db.Close()
		return nil, err
	}
	return s, nil
}

func (s *CoreStore) Close() error { return s.DB.Close() }

func isPGDSN(dsn string) bool {
	return strings.Contains(dsn, "postgres://") ||
		strings.Contains(dsn, "postgresql://") ||
		strings.Contains(dsn, "host=")
}

// nowExpr 方言感知的当前时间 SQL 表达式
func (s *CoreStore) nowExpr() string {
	if s.isPG {
		return "NOW()"
	}
	return "datetime('now')"
}

// nowParam Go 侧时间参数（字符串格式，跨方言可比）
func nowParam() string { return time.Now().UTC().Format("2006-01-02 15:04:05.000000") }

func plusParam(seconds int) string {
	return time.Now().UTC().Add(time.Duration(seconds) * time.Second).Format("2006-01-02 15:04:05.000000")
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

func stringOr(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func jsonInt(v any) any {
	if f, ok := v.(float64); ok {
		return int(f)
	}
	return v
}

func jsonFloat(v any) any {
	if f, ok := v.(float64); ok {
		return f
	}
	return nil
}

func jsonStringList(v any) []string {
	if list, ok := v.([]any); ok {
		out := make([]string, 0, len(list))
		for _, item := range list {
			if s, ok := item.(string); ok {
				out = append(out, s)
			}
		}
		return out
	}
	return nil
}

func bulletList(items []string) string {
	out := ""
	for _, item := range items {
		out += fmt.Sprintf("  - %s\n", item)
	}
	return out
}

// ---------- initSchema（双方言）----------

func (s *CoreStore) initSchema() error {
	var ddl string
	if s.isPG {
		ddl = `CREATE TABLE IF NOT EXISTS core_jobs (
	id TEXT PRIMARY KEY, kind TEXT NOT NULL, capability TEXT NOT NULL,
	payload JSONB NOT NULL DEFAULT '{}', idempotency_key TEXT UNIQUE,
	status TEXT NOT NULL DEFAULT 'queued', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
	started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS core_tasks (
	id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES core_jobs(id),
	capability TEXT NOT NULL, input_ref JSONB NOT NULL DEFAULT '{}',
	status TEXT NOT NULL DEFAULT 'queued', attempt_count INTEGER NOT NULL DEFAULT 0,
	max_attempts INTEGER NOT NULL DEFAULT 3, timeout_s INTEGER NOT NULL DEFAULT 600,
	lease_token TEXT, lease_expires_at TIMESTAMPTZ, last_error TEXT,
	result_ref JSONB, seq INTEGER NOT NULL DEFAULT 0,
	created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS ix_core_tasks_job ON core_tasks(job_id, status);
CREATE TABLE IF NOT EXISTS core_attempts (
	id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES core_tasks(id),
	attempt_no INTEGER NOT NULL, executor_id TEXT NOT NULL,
	fencing_token INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'running',
	error_class TEXT, error_message TEXT,
	started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), finished_at TIMESTAMPTZ);`
	} else {
		ddl = `CREATE TABLE IF NOT EXISTS core_jobs (
	id TEXT PRIMARY KEY, kind TEXT NOT NULL, capability TEXT NOT NULL,
	payload TEXT NOT NULL DEFAULT '{}', idempotency_key TEXT UNIQUE,
	status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL,
	started_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS core_tasks (
	id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES core_jobs(id),
	capability TEXT NOT NULL, input_ref TEXT NOT NULL DEFAULT '{}',
	status TEXT NOT NULL DEFAULT 'queued', attempt_count INTEGER NOT NULL DEFAULT 0,
	max_attempts INTEGER NOT NULL DEFAULT 3, timeout_s INTEGER NOT NULL DEFAULT 600,
	lease_token TEXT, lease_expires_at TEXT, last_error TEXT,
	result_ref TEXT, seq INTEGER NOT NULL DEFAULT 0,
	created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_core_tasks_job ON core_tasks(job_id, status);
CREATE TABLE IF NOT EXISTS core_attempts (
	id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES core_tasks(id),
	attempt_no INTEGER NOT NULL, executor_id TEXT NOT NULL,
	fencing_token INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'running',
	error_class TEXT, error_message TEXT,
	started_at TEXT NOT NULL, finished_at TEXT);`
	}
	_, err := s.DB.Exec(ddl)
	return err
}

// ---------- Submit（通用）----------

func (s *CoreStore) SubmitCoreTask(capability, inputRefJSON, idempotencyKey string, timeoutS int) (jobID, taskID string, created bool, err error) {
	if timeoutS <= 0 {
		timeoutS = 1800
	}
	if idempotencyKey != "" {
		var ej, et string
		err = s.DB.QueryRow(
			`SELECT j.id, t.id FROM core_jobs j JOIN core_tasks t ON t.job_id = j.id
			 WHERE j.idempotency_key = $1 LIMIT 1`, idempotencyKey,
		).Scan(&ej, &et)
		if err == nil {
			return ej, et, false, nil
		}
		if err != sql.ErrNoRows {
			return "", "", false, err
		}
	}
	jobID, taskID = newCoreID(), newCoreID()
	jobKind := "CoreTask"
	switch capability {
	case "skim_paper":
		jobKind = "SkimPaper"
	case "deep_read_paper":
		jobKind = "StartDeepRead"
	case "embed_paper":
		jobKind = "StartEmbedding"
	}
	now := nowParam()
	tx, err := s.DB.Begin()
	if err != nil {
		return "", "", false, err
	}
	defer tx.Rollback()
	if _, err = tx.Exec(
		`INSERT INTO core_jobs (id, kind, capability, payload, idempotency_key, status, created_at)
		 VALUES ($1, $2, $3, $4, $5, 'queued', $6)`,
		jobID, jobKind, capability, mustJSON(map[string]string{"paper_id": stringOrJSON(inputRefJSON)}), nullIfEmpty(idempotencyKey), now,
	); err != nil {
		return "", "", false, err
	}
	if _, err = tx.Exec(
		`INSERT INTO core_tasks (id, job_id, capability, input_ref, status, max_attempts, timeout_s, created_at)
		 VALUES ($1, $2, $3, $4, 'queued', 2, $5, $6)`,
		taskID, jobID, capability, inputRefJSON, timeoutS, now,
	); err != nil {
		return "", "", false, err
	}
	return jobID, taskID, true, tx.Commit()
}

func stringOrJSON(raw string) string {
	var m map[string]any
	if err := json.Unmarshal([]byte(raw), &m); err == nil {
		if pid, ok := m["paper_id"].(string); ok {
			return pid
		}
	}
	return raw
}

// ---------- Claim（CAS + pause 检查）----------

func (s *CoreStore) ClaimTask(executorID string, capabilities []string) (*Task, error) {
	want := map[string]bool{}
	for _, c := range capabilities {
		want[c] = true
	}
	// 跨进程 pause
	var paused string
	if err := s.DB.QueryRow(`SELECT value FROM system_flags WHERE key='queue_paused'`).Scan(&paused); err == nil && paused == "1" {
		return nil, nil
	}
	rows, err := s.DB.Query(
		`SELECT id, capability, timeout_s FROM core_tasks WHERE status='queued' ORDER BY created_at LIMIT 10`)
	if err != nil {
		return nil, err
	}
	type cand struct {
		id, capability string
		timeoutS       int
	}
	var cands []cand
	for rows.Next() {
		var c cand
		if err = rows.Scan(&c.id, &c.capability, &c.timeoutS); err != nil {
			rows.Close()
			return nil, err
		}
		if want[c.capability] {
			cands = append(cands, c)
		}
	}
	rows.Close()

	for _, c := range cands {
		leaseToken := newCoreID()
		var fencing int
		now := nowParam()
		expires := plusParam(c.timeoutS)
		err = s.DB.QueryRow(
			`UPDATE core_tasks SET status='leased', attempt_count=attempt_count+1,
			 lease_token=$1, lease_expires_at=$2
			 WHERE id=$3 AND status='queued' RETURNING attempt_count`,
			leaseToken, expires, c.id,
		).Scan(&fencing)
		if err != nil {
			continue
		}
		var jobID string
		s.DB.QueryRow(`SELECT job_id FROM core_tasks WHERE id=?`, c.id).Scan(&jobID)
		attemptID := newCoreID()
		if _, err = s.DB.Exec(
			`INSERT INTO core_attempts (id, task_id, attempt_no, executor_id, fencing_token, status, started_at)
			 VALUES ($1, $2, $3, $4, $5, 'running', $6)`,
			attemptID, c.id, fencing, executorID, fencing, now,
		); err != nil {
			return nil, err
		}
		s.DB.Exec(`UPDATE core_jobs SET status='running', started_at=COALESCE(started_at, $1) WHERE id=$2 AND status='queued'`, now, jobID)

		var inputJSON string
		s.DB.QueryRow(`SELECT input_ref FROM core_tasks WHERE id=?`, c.id).Scan(&inputJSON)
		var input map[string]any
		_ = json.Unmarshal([]byte(inputJSON), &input)
		return &Task{
			TaskID: c.id, AttemptID: fmt.Sprintf("%s:%d", c.id, fencing),
			Capability: c.capability, Input: input,
			ResourceClass: "llm", TimeoutS: c.timeoutS,
			AttemptNo: fencing, FencingToken: fencing, LeaseToken: leaseToken,
		}, nil
	}
	return nil, nil
}

// ---------- Heartbeat ----------

func (s *CoreStore) HeartbeatTask(taskID, executorID, leaseToken string) (bool, bool, error) {
	var status string
	var leaseTokenDB sql.NullString
	err := s.DB.QueryRow(`SELECT status, lease_token FROM core_tasks WHERE id=?`, taskID).Scan(&status, &leaseTokenDB)
	if err != nil {
		return false, false, err
	}
	if status != "leased" || !leaseTokenDB.Valid || leaseTokenDB.String != leaseToken {
		return false, false, nil
	}
	var timeoutS int
	s.DB.QueryRow(`SELECT timeout_s FROM core_tasks WHERE id=?`, taskID).Scan(&timeoutS)
	if _, err = s.DB.Exec(
		`UPDATE core_tasks SET lease_expires_at=$1 WHERE id=?`, plusParam(timeoutS), taskID,
	); err != nil {
		return false, false, err
	}
	var jobStatus string
	jobID := ""
	s.DB.QueryRow(`SELECT job_id FROM core_tasks WHERE id=?`, taskID).Scan(&jobID)
	if jobID != "" {
		s.DB.QueryRow(`SELECT status FROM core_jobs WHERE id=?`, jobID).Scan(&jobStatus)
	}
	return true, jobStatus == "cancelling", nil
}

// ---------- Job graph / list ----------

func (s *CoreStore) JobGraph(jobID string) (map[string]any, error) {
	var kind, status, payload string
	err := s.DB.QueryRow(`SELECT kind, status, payload FROM core_jobs WHERE id=$1`, jobID).Scan(&kind, &status, &payload)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.Query(
		`SELECT id, capability, status, attempt_count, max_attempts, last_error
		 FROM core_tasks WHERE job_id=$1 ORDER BY seq`, jobID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	tasks := []map[string]any{}
	for rows.Next() {
		var id, cap, st string
		var ac, ma int
		var le sql.NullString
		if err = rows.Scan(&id, &cap, &st, &ac, &ma, &le); err != nil {
			return nil, err
		}
		lastErr := ""
		if le.Valid {
			lastErr = le.String
		}
		tasks = append(tasks, map[string]any{
			"id": id, "capability": cap, "status": st,
			"attempt_count": ac, "max_attempts": ma, "last_error": lastErr,
		})
	}
	attempts := []map[string]any{}
	aRows, err := s.DB.Query(
		`SELECT a.id, a.task_id, a.attempt_no, a.executor_id, a.status
		 FROM core_attempts a JOIN core_tasks t ON t.id = a.task_id
		 WHERE t.job_id=$1 ORDER BY a.started_at`, jobID)
	if err == nil {
		for aRows.Next() {
			var id, tid, eid, st string
			var ano int
			if err = aRows.Scan(&id, &tid, &ano, &eid, &st); err == nil {
				attempts = append(attempts, map[string]any{
					"id": id, "task_id": tid, "attempt_no": ano,
					"executor_id": eid, "status": st,
				})
			}
		}
		aRows.Close()
	}
	var payloadAny map[string]any
	_ = json.Unmarshal([]byte(payload), &payloadAny)
	return map[string]any{
		"id": jobID, "kind": kind, "status": status,
		"payload": payloadAny, "tasks": tasks, "attempts": attempts,
		"authority": "go_core",
	}, nil
}

func (s *CoreStore) JobsList(limit int) ([]map[string]any, error) {
	rows, err := s.DB.Query(
		`SELECT id, kind, status, created_at FROM core_jobs ORDER BY created_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, kind, status, createdAt string
		if err = rows.Scan(&id, &kind, &status, &createdAt); err != nil {
			return nil, err
		}
		items = append(items, map[string]any{
			"id": id, "kind": kind, "status": status,
			"created_at": createdAt, "authority": "go_core",
		})
	}
	return items, nil
}

func (s *CoreStore) OwnsTask(taskID string) bool {
	var one string
	return s.DB.QueryRow(`SELECT id FROM core_tasks WHERE id=?`, taskID).Scan(&one) == nil
}

func (s *CoreStore) OwnsJob(jobID string) bool {
	var one string
	return s.DB.QueryRow(`SELECT id FROM core_jobs WHERE id=?`, jobID).Scan(&one) == nil
}

func (s *CoreStore) CancelJob(jobID string) (map[string]int, error) {
	now := nowParam()
	counts := map[string]int{"cancelled": 0, "cancel_requested": 0}
	s.DB.Exec(`UPDATE core_tasks SET status='cancelled', lease_token=NULL, lease_expires_at=NULL WHERE job_id=$1 AND status='queued'`, jobID)
	r1, _ := s.DB.Exec(`UPDATE core_tasks SET status='cancelled', last_error='cancelled by user' WHERE job_id=$1 AND status IN ('leased','running')`, jobID)
	if n, err := r1.RowsAffected(); err == nil {
		counts["cancel_requested"] = int(n)
	}
	s.DB.Exec(`UPDATE core_jobs SET status='cancelled', finished_at=$1 WHERE id=$2 AND status IN ('running','queued')`, now, jobID)
	s.DB.Exec(`UPDATE core_attempts SET status='cancelled', finished_at=$1 WHERE task_id IN (SELECT id FROM core_tasks WHERE job_id=$2) AND status='running'`, now, jobID)
	return counts, nil
}

// ---------- 领域查询 ----------

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
