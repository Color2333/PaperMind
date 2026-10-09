package core

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// newSQLiteRunnerStore：临时 SQLite 文件库 + runner 链路所需领域表。
// （PG 存储测试无 PG 环境整体 skip；SQLite 是文件库生产形态，双方言路径均需覆盖。）
func newSQLiteRunnerStore(t *testing.T) *CoreStore {
	t.Helper()
	s, err := OpenCoreStore(t.TempDir() + "/runner.db")
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	ddl := []string{
		`CREATE TABLE IF NOT EXISTS papers (
			id TEXT PRIMARY KEY, title TEXT NOT NULL, abstract TEXT NOT NULL DEFAULT '',
			arxiv_id TEXT UNIQUE, read_status TEXT NOT NULL DEFAULT 'unread',
			metadata TEXT NOT NULL DEFAULT '{}', pdf_path TEXT, embedding_vec TEXT,
			source TEXT, source_id TEXT, publication_date TEXT, doi TEXT,
			favorited BOOLEAN NOT NULL DEFAULT 0, rejected BOOLEAN NOT NULL DEFAULT 0,
			created_at TEXT, updated_at TEXT)`,
		`CREATE TABLE IF NOT EXISTS analysis_reports (
			id TEXT PRIMARY KEY, paper_id TEXT NOT NULL UNIQUE,
			summary_md TEXT, deep_dive_md TEXT, key_insights TEXT NOT NULL DEFAULT '{}',
			skim_score REAL, created_at TEXT, updated_at TEXT)`,
		`CREATE TABLE IF NOT EXISTS prompt_traces (
			id TEXT PRIMARY KEY, paper_id TEXT, stage TEXT NOT NULL, provider TEXT NOT NULL,
			model TEXT NOT NULL, prompt_digest TEXT NOT NULL,
			input_tokens INTEGER, output_tokens INTEGER,
			input_cost_usd REAL, output_cost_usd REAL, total_cost_usd REAL,
			created_at TEXT)`,
	}
	for _, d := range ddl {
		if _, err := s.DB.Exec(d); err != nil {
			t.Fatalf("schema: %v", err)
		}
	}
	if _, err := s.DB.Exec(
		`INSERT INTO papers (id, title, abstract, arxiv_id, metadata, created_at, updated_at, favorited, rejected)
		 VALUES ('paper-1', 'Test paper', 'abstract content here', '2609.09999', '{}', datetime('now'), datetime('now'), 0, 0)`,
	); err != nil {
		t.Fatal(err)
	}
	return s
}

// TestRunnerSkimEndToEnd：claim → handler（mock 网关）→ apply 全链路。
// 断言：任务 succeeded + analysis_reports 落行 + papers.read_status 升级。
func TestRunnerSkimEndToEnd(t *testing.T) {
	store := newSQLiteRunnerStore(t)

	// mock Pi 网关：OpenAI 兼容 chat/completions 返回 skim JSON
	gw := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"choices":[{"message":{"content":"{\"one_liner\":\"提出新方法X\",\"innovations\":[\"创新A\"],\"keywords\":[\"kw1\"],\"title_zh\":\"测试标题\",\"abstract_zh\":\"测试摘要\",\"relevance_score\":0.8}"}}],"usage":{"prompt_tokens":100,"completion_tokens":50}}`))
	}))
	defer gw.Close()

	// mock embedding provider
	emb := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":[{"embedding":[0.1,0.2,0.3]}]}`))
	}))
	defer emb.Close()

	env := &HandlerEnv{
		Store:   store,
		Gateway: &GatewayClient{baseURL: gw.URL, token: "test", http: &http.Client{Timeout: 5 * time.Second}},
		Embed:   &EmbedClient{baseURL: emb.URL, apiKey: "test", model: "test-model", http: &http.Client{Timeout: 5 * time.Second}},
		Arxiv:   NewArxivClient(),
		Scholar: NewScholarClient(),
		PDFRoot: t.TempDir(),
	}

	runner := NewRunner(store, env, "test-executor")
	runner.Register("skim_paper", HandleSkimPaper)
	runner.Register("embed_paper", HandleEmbedPaper)
	runner.Register("upsert_paper", HandleUpsertPaper)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go runner.Start(ctx)

	// 提交 skim 任务
	_, taskID, created, err := store.SubmitCoreTask("skim_paper", `{"paper_id":"paper-1"}`, "", 60)
	if err != nil || !created {
		t.Fatalf("submit: err=%v created=%v", err, created)
	}

	// 轮询等待完成（runner tick 2s + 执行 <1s）
	deadline := time.Now().Add(15 * time.Second)
	status := ""
	for time.Now().Before(deadline) {
		ts, err := store.TaskStatus(taskID)
		if err != nil {
			t.Fatalf("task status: %v", err)
		}
		status = ts.Status
		if status == "succeeded" || status == "failed" || status == "dead_letter" {
			break
		}
		time.Sleep(300 * time.Millisecond)
	}
	if status != "succeeded" {
		t.Fatalf("task 终态 = %s（期望 succeeded）", status)
	}

	// apply 副作用断言：analysis_reports + read_status
	var summaryMD string
	var score float64
	if err := store.DB.QueryRow(
		`SELECT summary_md, skim_score FROM analysis_reports WHERE paper_id='paper-1'`,
	).Scan(&summaryMD, &score); err != nil {
		t.Fatalf("analysis_reports 缺失: %v", err)
	}
	if !strings.Contains(summaryMD, "提出新方法X") {
		t.Fatalf("summary_md 内容不符: %q", summaryMD)
	}
	if score < 0.79 || score > 0.81 {
		t.Fatalf("skim_score = %v（期望 0.8）", score)
	}
	var readStatus string
	if err := store.DB.QueryRow(`SELECT read_status FROM papers WHERE id='paper-1'`).Scan(&readStatus); err != nil {
		t.Fatal(err)
	}
	if readStatus != "skimmed" {
		t.Fatalf("read_status = %s（期望 skimmed）", readStatus)
	}

	// prompt_traces 成本观测随 apply 同事务落库
	var traceCount int
	if err := store.DB.QueryRow(`SELECT COUNT(*) FROM prompt_traces WHERE paper_id='paper-1' AND stage='skim'`).Scan(&traceCount); err != nil {
		t.Fatal(err)
	}
	if traceCount != 1 {
		t.Fatalf("prompt_traces skim = %d（期望 1）", traceCount)
	}
}

// TestRunnerEmbedEndToEnd：embedding 向量落库。
func TestRunnerEmbedEndToEnd(t *testing.T) {
	store := newSQLiteRunnerStore(t)
	emb := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":[{"embedding":[0.5,0.5,0.5]}]}`))
	}))
	defer emb.Close()

	env := &HandlerEnv{
		Store:   store,
		Gateway: &GatewayClient{baseURL: "http://unused", token: "t", http: &http.Client{Timeout: 5 * time.Second}},
		Embed:   &EmbedClient{baseURL: emb.URL, apiKey: "test", model: "test", http: &http.Client{Timeout: 5 * time.Second}},
		Arxiv:   NewArxivClient(),
		Scholar: NewScholarClient(),
		PDFRoot: t.TempDir(),
	}
	runner := NewRunner(store, env, "test-executor")
	runner.Register("embed_paper", HandleEmbedPaper)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go runner.Start(ctx)

	_, taskID, _, err := store.SubmitCoreTask("embed_paper", `{"paper_id":"paper-1"}`, "", 60)
	if err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(15 * time.Second)
	status := ""
	for time.Now().Before(deadline) {
		ts, _ := store.TaskStatus(taskID)
		status = ts.Status
		if status == "succeeded" || status == "failed" || status == "dead_letter" {
			break
		}
		time.Sleep(300 * time.Millisecond)
	}
	if status != "succeeded" {
		t.Fatalf("embed 终态 = %s", status)
	}
	var raw string
	if err := store.DB.QueryRow(`SELECT embedding_vec FROM papers WHERE id='paper-1'`).Scan(&raw); err != nil {
		t.Fatalf("embedding_vec 缺失: %v", err)
	}
	if !strings.Contains(raw, "0.5") {
		t.Fatalf("embedding_vec 内容不符: %q", raw)
	}
}

// TestRunnerFailureRetries：handler 失败 → FailTask → 重试语义。
func TestRunnerFailureRetries(t *testing.T) {
	store := newSQLiteRunnerStore(t)
	env := &HandlerEnv{
		Store:   store,
		Gateway: &GatewayClient{baseURL: "http://127.0.0.1:1", token: "t", http: &http.Client{Timeout: 1 * time.Second}},
		Embed:   &EmbedClient{},
		Arxiv:   NewArxivClient(),
		Scholar: NewScholarClient(),
		PDFRoot: t.TempDir(),
	}
	runner := NewRunner(store, env, "test-executor")
	runner.Register("skim_paper", HandleSkimPaper)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go runner.Start(ctx)

	_, taskID, _, err := store.SubmitCoreTask("skim_paper", `{"paper_id":"paper-1"}`, "", 60)
	if err != nil {
		t.Fatal(err)
	}
	// 网关不可达 → 失败；max_attempts=3 内应有 attempt 记录
	deadline := time.Now().Add(20 * time.Second)
	status := ""
	for time.Now().Before(deadline) {
		ts, _ := store.TaskStatus(taskID)
		status = ts.Status
		if ts.AttemptCount >= 2 || status == "dead_letter" {
			break
		}
		time.Sleep(300 * time.Millisecond)
	}
	ts, _ := store.TaskStatus(taskID)
	if ts.AttemptCount < 2 {
		t.Fatalf("失败后 attempt_count = %d（期望 >=2，status=%s）", ts.AttemptCount, status)
	}
	if ts.LastError == "" {
		t.Fatal("last_error 为空")
	}
}
