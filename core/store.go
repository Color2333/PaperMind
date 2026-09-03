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

	_ "modernc.org/sqlite"
)

// CoreStore 持有权威 Job/Task/Attempt 状态（SQLite，同一 papermind.db）。
type CoreStore struct {
	DB *sql.DB
}

// OpenCoreStore 打开（或创建）权威存储；busy_timeout + WAL 与 Python 并发共存。
func OpenCoreStore(sqlitePath string) (*CoreStore, error) {
	dsn := fmt.Sprintf(
		"file:%s?_pragma=busy_timeout(10000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(0)",
		sqlitePath,
	)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, err
	}
	// SQLite 单写者：Go 侧限 1 连接，配合 busy_timeout 与 Python 进程串行化
	db.SetMaxOpenConns(1)
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
	payload TEXT NOT NULL DEFAULT '{}',
	idempotency_key TEXT UNIQUE,
	status TEXT NOT NULL DEFAULT 'queued',
	created_at TEXT NOT NULL,
	started_at TEXT,
	finished_at TEXT
);
CREATE TABLE IF NOT EXISTS core_tasks (
	id TEXT PRIMARY KEY,
	job_id TEXT NOT NULL REFERENCES core_jobs(id),
	capability TEXT NOT NULL,
	input_ref TEXT NOT NULL DEFAULT '{}',
	status TEXT NOT NULL DEFAULT 'queued',
	attempt_count INTEGER NOT NULL DEFAULT 0,
	max_attempts INTEGER NOT NULL DEFAULT 3,
	timeout_s INTEGER NOT NULL DEFAULT 600,
	lease_token TEXT,
	lease_expires_at TEXT,
	last_error TEXT,
	result_ref TEXT,
	seq INTEGER NOT NULL DEFAULT 0,
	created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_core_tasks_job ON core_tasks(job_id, status);
CREATE TABLE IF NOT EXISTS core_attempts (
	id TEXT PRIMARY KEY,
	task_id TEXT NOT NULL REFERENCES core_tasks(id),
	attempt_no INTEGER NOT NULL,
	executor_id TEXT NOT NULL,
	fencing_token INTEGER NOT NULL,
	status TEXT NOT NULL DEFAULT 'running',
	started_at TEXT NOT NULL,
	finished_at TEXT
);
`)
	return err
}

func nowISO() string { return time.Now().UTC().Format(time.RFC3339Nano) }

// sqliteTime：SQLite datetime('now') 同格式（ReclaimExpired 的字符串比较依赖一致性）
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

// SubmitSkimJob 创建 skim Job + Task（queued）。幂等：idempotency_key 命中返回既有。
func (s *CoreStore) SubmitSkimJob(paperID, idempotencyKey string, timeoutS int) (jobID, taskID string, created bool, err error) {
	if timeoutS <= 0 {
		timeoutS = 900
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

	if _, err = tx.Exec(
		`INSERT INTO core_jobs (id, kind, capability, payload, idempotency_key, status, created_at)
		 VALUES (?, 'SkimPaper', 'skim_paper', ?, ?, 'queued', ?)`,
		jobID, mustJSON(map[string]string{"paper_id": paperID}), nullIfEmpty(idempotencyKey), now,
	); err != nil {
		return "", "", false, err
	}
	if _, err = tx.Exec(
		`INSERT INTO core_tasks (id, job_id, capability, input_ref, status, max_attempts, timeout_s, created_at)
		 VALUES (?, ?, 'skim_paper', ?, 'queued', 2, ?, ?)`,
		taskID, jobID, mustJSON(map[string]string{"paper_id": paperID}), timeoutS, now,
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
	if !want["skim_paper"] {
		return nil, nil
	}

	rows, err := s.DB.Query(
		`SELECT id, timeout_s FROM core_tasks WHERE status='queued' ORDER BY created_at LIMIT 10`)
	if err != nil {
		return nil, err
	}
	type candidate struct {
		id       string
		timeoutS int
	}
	var candidates []candidate
	for rows.Next() {
		var c candidate
		if err = rows.Scan(&c.id, &c.timeoutS); err != nil {
			rows.Close()
			return nil, err
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
			Capability:    "skim_paper",
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
	var payloadAny map[string]any
	_ = json.Unmarshal([]byte(payload), &payloadAny)
	return map[string]any{
		"id": jobID, "kind": kind, "status": status,
		"payload": payloadAny, "tasks": tasks, "authority": "go_core",
	}, nil
}
