package core

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// newTestStore：临时 SQLite + 领域表最小 schema（与 Python migrations 对齐）
func newTestStore(t *testing.T) *CoreStore {
	t.Helper()
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "test.db")
	s, err := OpenCoreStore(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	// 领域表最小 schema（列名/类型与 Python models 对齐）
	if _, err := s.DB.Exec(`
CREATE TABLE IF NOT EXISTS papers (
	id TEXT PRIMARY KEY,
	title TEXT NOT NULL,
	abstract TEXT NOT NULL DEFAULT '',
	arxiv_id TEXT UNIQUE,
	read_status TEXT NOT NULL DEFAULT 'unread',
	"metadata" TEXT,
	pdf_path TEXT,
	embedding_vec TEXT,
	updated_at TEXT
);
CREATE TABLE IF NOT EXISTS analysis_reports (
	id TEXT PRIMARY KEY,
	paper_id TEXT NOT NULL UNIQUE REFERENCES papers(id) ON DELETE CASCADE,
	summary_md TEXT,
	deep_dive_md TEXT,
	key_insights TEXT NOT NULL DEFAULT '{}',
	skim_score REAL,
	created_at TEXT NOT NULL DEFAULT (datetime('now')),
	updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS prompt_traces (
	id TEXT PRIMARY KEY,
	paper_id TEXT REFERENCES papers(id) ON DELETE SET NULL,
	stage TEXT NOT NULL,
	provider TEXT NOT NULL,
	model TEXT NOT NULL,
	prompt_digest TEXT NOT NULL,
	input_tokens INTEGER,
	output_tokens INTEGER,
	input_cost_usd REAL,
	output_cost_usd REAL,
	total_cost_usd REAL,
	created_at TEXT NOT NULL DEFAULT (datetime('now'))
);`); err != nil {
		t.Fatal(err)
	}
	// 种论文
	if _, err := s.DB.Exec(
		`INSERT INTO papers (id, title, abstract, arxiv_id) VALUES (?, 'Test paper', 'abstract', '2609.09999')`,
		"paper-1",
	); err != nil {
		t.Fatal(err)
	}
	return s
}

func skimProposal() map[string]any {
	return map[string]any{
		"proposal": map[string]any{
			"kind":     "skim_paper",
			"paper_id": "paper-1",
			"skim": map[string]any{
				"one_liner":       "提出新方法 X",
				"innovations":     []any{"创新 A", "创新 B"},
				"keywords":        []any{"kw1"},
				"title_zh":        "测试论文",
				"abstract_zh":     "摘要译文",
				"relevance_score": 0.9,
			},
			"trace": map[string]any{
				"stage": "skim", "provider": "test", "model": "mock-model",
				"prompt_digest": "abc", "input_tokens": 10, "output_tokens": 5,
				"input_cost_usd": 0.0, "output_cost_usd": 0.0, "total_cost_usd": 0.0,
			},
		},
	}
}

func TestApplySkimResultSingleTransaction(t *testing.T) {
	s := newTestStore(t)
	jobID, taskID, _, err := s.SubmitCoreTask("skim_paper", `{"paper_id":"paper-1"}`, "skim:test:1", 600)
	if err != nil {
		t.Fatal(err)
	}
	// 领取（签发 lease）
	own, err := s.ClaimTask("exec-1", []string{"skim_paper"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v / %v", own, err)
	}

	proposal := skimProposal()
	status, err := s.ApplyResult(taskID, "exec-1", own.LeaseToken, proposal)
	if err != nil {
		t.Fatal(err)
	}
	if status != "succeeded" {
		t.Fatalf("status=%s", status)
	}

	// 领域变化已提交（同一事务）
	var summaryMD string
	if err := s.DB.QueryRow(
		`SELECT summary_md FROM analysis_reports WHERE paper_id='paper-1'`,
	).Scan(&summaryMD); err != nil {
		t.Fatalf("analysis_reports 缺失（apply-result 未生效）: %v", err)
	}
	if want := "- 一句话: 提出新方法 X"; len(summaryMD) < len(want) {
		t.Fatalf("summary_md 异常: %q", summaryMD)
	}
	var readStatus string
	var metadataJSON string
	_ = s.DB.QueryRow(
		`SELECT read_status, "metadata" FROM papers WHERE id='paper-1'`,
	).Scan(&readStatus, &metadataJSON)
	if readStatus != "skimmed" {
		t.Fatalf("read_status=%s", readStatus)
	}
	var meta map[string]any
	_ = json.Unmarshal([]byte(metadataJSON), &meta)
	if meta["title_zh"] != "测试论文" {
		t.Fatalf("metadata 合并失败: %v", meta)
	}
	var traceCount int
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM prompt_traces WHERE stage='skim'`).Scan(&traceCount)
	if traceCount != 1 {
		t.Fatalf("prompt_traces=%d", traceCount)
	}
	// 终态
	var taskStatus string
	_ = s.DB.QueryRow(`SELECT status FROM core_tasks WHERE id=?`, taskID).Scan(&taskStatus)
	if taskStatus != "succeeded" {
		t.Fatalf("task=%s", taskStatus)
	}
	_ = jobID
}

func TestApplySkimResultFencingRejectsStaleLease(t *testing.T) {
	s := newTestStore(t)
	_, taskID, _, _ := s.SubmitCoreTask("skim_paper", `{"paper_id":"paper-1"}`, "skim:test:2", 600)
	own, _ := s.ClaimTask("exec-1", []string{"skim_paper"})

	// 模拟 lease 过期回收后新 attempt
	_, _ = s.DB.Exec(`UPDATE core_tasks SET status='queued', lease_token=NULL, lease_expires_at=NULL WHERE id=?`, taskID)
	own2, err := s.ClaimTask("exec-2", []string{"skim_paper"})
	if err != nil || own2 == nil {
		t.Fatalf("re-claim: %v", err)
	}

	// 旧 lease 的 proposal → 409 语义（fencing 拒绝）
	_, err = s.ApplyResult(taskID, "exec-1", own.LeaseToken, skimProposal())
	if err == nil {
		t.Fatal("旧 lease 的 apply 应被拒绝")
	}
	// 领域表无变化（回滚验证）
	var count int
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM analysis_reports`).Scan(&count)
	if count != 0 {
		t.Fatalf("被拒绝的 apply 不得留下领域状态（事务应回滚），analysis_reports=%d", count)
	}
	// 新 lease 的 apply 成功
	if _, err = s.ApplyResult(taskID, "exec-2", own2.LeaseToken, skimProposal()); err != nil {
		t.Fatal(err)
	}
}

func TestClaimConcurrentSingleWinner(t *testing.T) {
	s := newTestStore(t)
	_, _, _, _ = s.SubmitCoreTask("skim_paper", `{"paper_id":"paper-1"}`, "skim:test:3", 600)

	winner := make(chan bool, 2)
	for i := 0; i < 2; i++ {
		go func() {
			task, err := s.ClaimTask("exec-race", []string{"skim_paper"})
			winner <- task != nil && err == nil
		}()
	}
	wins := 0
	for i := 0; i < 2; i++ {
		if <-winner {
			wins++
		}
	}
	if wins != 1 {
		t.Fatalf("并发 claim 应恰好一个赢家，got %d", wins)
	}
	_ = os.Remove(filepath.Join(t.TempDir(), "unused"))
}

func TestApplyDeepReadResultReadStatusUpgradeOnly(t *testing.T) {
	s := newTestStore(t)
	_, taskID, _, _ := s.SubmitCoreTask("deep_read_paper", `{"paper_id":"paper-1"}`, "dr:1", 600)
	own, err := s.ClaimTask("exec-1", []string{"deep_read_paper"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v", err)
	}
	// skim 的 task，但提交 deep_read proposal——capability 分派按 core_tasks 行
	// （此处验证 read_status 只升不降语义：unread → deep_read）
	deepProposal := map[string]any{
		"proposal": map[string]any{
			"kind":     "deep_read_paper",
			"paper_id": "paper-1",
			"deep": map[string]any{
				"method_summary":      "M",
				"experiments_summary": "E",
				"ablation_summary":    "A",
				"reviewer_risks":      []any{"R"},
			},
			"trace": map[string]any{
				"stage": "deep_dive", "paper_id": "paper-1",
				"provider": "test", "model": "mock", "prompt_digest": "d",
			},
		},
	}
	if _, err = s.ApplyResult(taskID, "exec-1", own.LeaseToken, deepProposal); err != nil {
		t.Fatal(err)
	}
	var readStatus, deepMD string
	_ = s.DB.QueryRow(`SELECT read_status FROM papers WHERE id='paper-1'`).Scan(&readStatus)
	_ = s.DB.QueryRow(`SELECT deep_dive_md FROM analysis_reports WHERE paper_id='paper-1'`).Scan(&deepMD)
	if readStatus != "deep_read" {
		t.Fatalf("read_status=%s（unread 应可直升 deep_read）", readStatus)
	}
	if deepMD == "" {
		t.Fatal("deep_dive_md 未写入")
	}
}

func TestApplyEmbedResult(t *testing.T) {
	s := newTestStore(t)
	_, taskID, _, _ := s.SubmitCoreTask("embed_paper", `{"paper_id":"paper-1"}`, "em:1", 600)
	own, err := s.ClaimTask("exec-1", []string{"embed_paper"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v", err)
	}
	embedProposal := map[string]any{
		"proposal": map[string]any{
			"kind":     "embed_paper",
			"paper_id": "paper-1",
			"vector":   []any{0.1, 0.2, 0.3},
		},
	}
	if _, err = s.ApplyResult(taskID, "exec-1", own.LeaseToken, embedProposal); err != nil {
		t.Fatal(err)
	}
	var embedding string
	if err = s.DB.QueryRow(`SELECT embedding_vec FROM papers WHERE id='paper-1'`).Scan(&embedding); err != nil {
		t.Fatal(err)
	}
	var vec []float64
	if err = json.Unmarshal([]byte(embedding), &vec); err != nil {
		t.Fatalf("embedding 解析: %v", err)
	}
	if len(vec) != 3 || vec[0] != 0.1 {
		t.Fatalf("embedding 内容异常: %v", vec)
	}
}
