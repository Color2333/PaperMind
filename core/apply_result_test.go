package core

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// newTestStore：临时 SQLite + 领域表最小 schema（与 Python migrations 对齐）
func newTestStore(t *testing.T) *CoreStore {
	t.Helper()
	s := newPGTestStore(t)
	// 领域表最小 schema（PG 方言）
	if _, err := s.DB.Exec(`
CREATE TABLE IF NOT EXISTS papers (
	id TEXT PRIMARY KEY,
	title TEXT NOT NULL,
	abstract TEXT NOT NULL DEFAULT '',
	arxiv_id TEXT UNIQUE,
	read_status TEXT NOT NULL DEFAULT 'unread',
	metadata JSONB,
	pdf_path TEXT,
	embedding_vec JSONB,
	updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS analysis_reports (
	id TEXT PRIMARY KEY,
	paper_id TEXT NOT NULL UNIQUE REFERENCES papers(id) ON DELETE CASCADE,
	summary_md TEXT,
	deep_dive_md TEXT,
	key_insights JSONB NOT NULL DEFAULT '{}',
	skim_score REAL,
	created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
	updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
	created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);`); err != nil {
		t.Fatal(err)
	}
	if _, err := s.DB.Exec(
		`INSERT INTO papers (id, title, abstract, arxiv_id) VALUES ('paper-1', 'Test paper', 'abstract', '2609.09999')`,
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

func runIDOfClaim(t *testing.T, s *CoreStore, claimID string) string {
	t.Helper()
	var runID string
	if err := s.DB.QueryRow(`SELECT run_id FROM claims WHERE id=?`, claimID).Scan(&runID); err != nil {
		t.Fatal(err)
	}
	return runID
}

func TestApplyExtractClaimsResult(t *testing.T) {
	s := newTestStore(t)
	// 补 claims/evidence/research_events/source_versions/research_runs schema
	if _, err := s.DB.Exec(`
CREATE TABLE IF NOT EXISTS claims (
	id TEXT PRIMARY KEY,
	research_question_id TEXT,
	statement TEXT NOT NULL,
	statement_zh TEXT,
	origin TEXT NOT NULL DEFAULT 'papermind',
	status TEXT NOT NULL DEFAULT 'draft',
	certainty TEXT,
	run_id TEXT,
	created_at TEXT NOT NULL DEFAULT (NOW()),
	updated_at TEXT NOT NULL DEFAULT (NOW())
);
CREATE TABLE IF NOT EXISTS evidence (
	id TEXT PRIMARY KEY,
	claim_id TEXT NOT NULL REFERENCES claims(id),
	source_version_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	stance TEXT NOT NULL,
	locator TEXT NOT NULL DEFAULT '{}',
	quote TEXT,
	fingerprint TEXT NOT NULL UNIQUE,
	run_id TEXT,
	created_at TEXT NOT NULL DEFAULT (NOW())
);
CREATE TABLE IF NOT EXISTS research_runs (
	id TEXT PRIMARY KEY,
	kind TEXT NOT NULL,
	trigger TEXT NOT NULL DEFAULT 'manual',
	paper_ids TEXT NOT NULL DEFAULT '[]',
	model_policy TEXT NOT NULL DEFAULT '{}',
	status TEXT NOT NULL DEFAULT 'succeeded',
	started_at TEXT NOT NULL DEFAULT (NOW())
);
CREATE TABLE IF NOT EXISTS research_events (
	id TEXT PRIMARY KEY,
	type TEXT NOT NULL,
	aggregate_type TEXT NOT NULL,
	aggregate_id TEXT NOT NULL,
	actor TEXT NOT NULL DEFAULT 'system',
	run_id TEXT,
	payload TEXT NOT NULL DEFAULT '{}',
	occurred_at TEXT NOT NULL DEFAULT (NOW())
);
CREATE TABLE IF NOT EXISTS source_versions (
	id TEXT PRIMARY KEY,
	paper_id TEXT NOT NULL,
	version_label INTEGER NOT NULL,
	content_hash TEXT NOT NULL,
	detected_by TEXT NOT NULL DEFAULT 'ingest',
	is_current INTEGER NOT NULL DEFAULT 1,
	created_at TEXT NOT NULL DEFAULT (NOW())
);`); err != nil {
		t.Fatal(err)
	}

	_, taskID, _, _ := s.SubmitCoreTask("extract_claims", `{"paper_id":"paper-1"}`, "claims:t:1", 600)
	own, err := s.ClaimTask("exec-1", []string{"extract_claims"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v", err)
	}
	if own.Capability != "extract_claims" {
		t.Fatalf("capability=%s", own.Capability)
	}

	proposal := map[string]any{
		"proposal": map[string]any{
			"kind":     "extract_claims",
			"paper_id": "paper-1",
			"items": []any{
				map[string]any{
					"statement":    "The method X reduces DER by 12%",
					"quote":        "reduces DER by 12%",
					"locator":      map[string]any{"section": "1"},
					"certainty":    "conditional",
					"statement_zh": "方法 X 减少 DER 12%",
				},
			},
			"trace": map[string]any{
				"stage": "claim_extraction", "paper_id": "paper-1",
				"provider": "test", "model": "mock", "prompt_digest": "d",
			},
			"run_meta": map[string]any{
				"model_policy": map[string]any{"provider": "test", "model": "mock"},
			},
		},
	}
	status, err := s.ApplyResult(taskID, "exec-1", own.LeaseToken, proposal)
	if err != nil {
		t.Fatal(err)
	}
	if status == "" {
		t.Fatal("status 为空")
	}

	// claim 写入验证
	var claimID, claimStatus string
	if err = s.DB.QueryRow(
		`SELECT id, status FROM claims WHERE statement LIKE '%DER%'`,
	).Scan(&claimID, &claimStatus); err != nil {
		t.Fatalf("claim 未写入: %v", err)
	}
	if claimStatus != "draft" {
		t.Fatalf("papermind claim 应 draft，got %s", claimStatus)
	}
	// evidence 写入 + fingerprint 非空
	var fingerprint string
	if err = s.DB.QueryRow(
		`SELECT fingerprint FROM evidence WHERE claim_id=?`, claimID,
	).Scan(&fingerprint); err != nil {
		t.Fatalf("evidence 未写入: %v", err)
	}
	if len(fingerprint) != 64 {
		t.Fatalf("fingerprint 长度异常: %d", len(fingerprint))
	}
	// research_events outbox：claim_proposed + evidence_extracted + source_version_detected
	var eventCount int
	_ = s.DB.QueryRow(
		`SELECT COUNT(*) FROM research_events WHERE aggregate_id = ? OR run_id = ?`,
		claimID, runIDOfClaim(t, s, claimID),
	).Scan(&eventCount)
	if eventCount < 2 {
		t.Fatalf("outbox 事件不足: %d", eventCount)
	}

	// 二次提交（re-attempt）：quote 幂等——不重复写入
	_, taskID2, _, _ := s.SubmitCoreTask("extract_claims", `{"paper_id":"paper-1"}`, "claims:t:2", 600)
	own2, err := s.ClaimTask("exec-1", []string{"extract_claims"})
	if err != nil || own2 == nil {
		t.Fatalf("re-claim: %v", err)
	}
	if _, err = s.ApplyResult(taskID2, "exec-1", own2.LeaseToken, proposal); err != nil {
		t.Fatal(err)
	}
	var claimCount int
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM claims WHERE statement LIKE '%DER%'`).Scan(&claimCount)
	if claimCount != 1 {
		t.Fatalf("re-attempt 不得重复 claim，got %d", claimCount)
	}
}

// TestApplyTerminalOnlyResult：B 档通用路径——领域写入由 handler 承载，
// Go 权威面单事务落 fencing + 终态 + result_ref 原样存储；无领域表写入。
func TestApplyTerminalOnlyResult(t *testing.T) {
	s := newTestStore(t)
	_, taskID, _, err := s.SubmitCoreTask("sync_citations_topic", `{"topic_id":"t1"}`, "cite:t:1", 600)
	if err != nil {
		t.Fatal(err)
	}
	own, err := s.ClaimTask("exec-1", []string{"sync_citations_topic"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v / %v", own, err)
	}

	result := map[string]any{"papers_synced": 5.0, "edges_created": 12.0}
	status, err := s.ApplyResult(taskID, "exec-1", own.LeaseToken, result)
	if err != nil {
		t.Fatalf("B 档 complete 不应被拒绝: %v", err)
	}
	if status != "succeeded" {
		t.Fatalf("status=%s", status)
	}

	// result_ref 原样存储
	var resultRef string
	if err := s.DB.QueryRow(`SELECT result_ref FROM core_tasks WHERE id=?`, taskID).Scan(&resultRef); err != nil {
		t.Fatal(err)
	}
	var stored map[string]any
	if err := json.Unmarshal([]byte(resultRef), &stored); err != nil {
		t.Fatal(err)
	}
	if stored["papers_synced"] != 5.0 {
		t.Fatalf("result_ref 原样存储失败: %v", stored)
	}

	// fencing：迟到/重复提交被拒绝
	if _, err := s.ApplyResult(taskID, "exec-1", own.LeaseToken, result); err == nil {
		t.Fatal("已完成任务的二次 apply 应被 fencing 拒绝")
	}
}

// TestApplyDownloadSourcePdfPath：Python handler 真实下载后回传 pdf_path 形态。
func TestApplyDownloadSourcePdfPath(t *testing.T) {
	s := newTestStore(t)
	if _, err := s.DB.Exec(
		`INSERT INTO papers (id, title, arxiv_id, abstract, read_status, created_at, updated_at)
		 VALUES ('p-dl', '下载测试', '2601.00001', '', 'unread', NOW(), NOW())`,
	); err != nil {
		t.Fatal(err)
	}
	_, taskID, _, _ := s.SubmitCoreTask("download_source", `{"arxiv_id":"2601.00001"}`, "dl:t:1", 600)
	own, err := s.ClaimTask("exec-1", []string{"download_source"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v / %v", own, err)
	}
	proposal := map[string]any{
		"proposal": map[string]any{
			"kind": "download_source", "arxiv_id": "2601.00001", "pdf_path": "/data/pdfs/2601.00001.pdf",
		},
	}
	if _, err := s.ApplyResult(taskID, "exec-1", own.LeaseToken, proposal); err != nil {
		t.Fatal(err)
	}
	var pdfPath string
	if err := s.DB.QueryRow(`SELECT pdf_path FROM papers WHERE id='p-dl'`).Scan(&pdfPath); err != nil {
		t.Fatal(err)
	}
	if pdfPath != "/data/pdfs/2601.00001.pdf" {
		t.Fatalf("pdf_path=%s", pdfPath)
	}
}

// TestApplyUpsertPaperMetadataMerge：重复 ingest 不得覆盖 skim 派生字段。
func TestApplyUpsertPaperMetadataMerge(t *testing.T) {
	s := newTestStore(t)
	if _, err := s.DB.Exec(
		`INSERT INTO papers (id, title, arxiv_id, abstract, read_status, metadata, created_at, updated_at)
		 VALUES ('p-merge', '旧标题', '2601.00002', '旧摘要', 'skimmed', '{"title_zh":"已有中文标题","keywords":["a"]}', NOW(), NOW())`,
	); err != nil {
		t.Fatal(err)
	}
	_, taskID, _, _ := s.SubmitCoreTask("upsert_paper", `{"arxiv_id":"2601.00002"}`, "up:t:1", 600)
	own, err := s.ClaimTask("exec-1", []string{"upsert_paper"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v / %v", own, err)
	}
	proposal := map[string]any{
		"proposal": map[string]any{
			"kind": "upsert_paper", "arxiv_id": "2601.00002",
			"title": "新标题", "abstract": "新摘要",
			"metadata": map[string]any{"categories": []any{"cs.LG"}},
		},
	}
	if _, err := s.ApplyResult(taskID, "exec-1", own.LeaseToken, proposal); err != nil {
		t.Fatal(err)
	}
	var metadataJSON string
	if err := s.DB.QueryRow(`SELECT "metadata" FROM papers WHERE id='p-merge'`).Scan(&metadataJSON); err != nil {
		t.Fatal(err)
	}
	var meta map[string]any
	_ = json.Unmarshal([]byte(metadataJSON), &meta)
	if meta["title_zh"] != "已有中文标题" {
		t.Fatalf("skim 派生字段被覆盖: %v", meta)
	}
	if meta["categories"] == nil {
		t.Fatalf("ingest metadata 未合并: %v", meta)
	}
	// result_ref 携带 paper_id（下游节点输出绑定依赖）
	var resultRef string
	_ = s.DB.QueryRow(`SELECT result_ref FROM core_tasks WHERE id=?`, taskID).Scan(&resultRef)
	if !strings.Contains(resultRef, "p-merge") {
		t.Fatalf("result_ref 缺少 paper_id: %s", resultRef)
	}
}

// TestApplyIngestPapersResult：批量入库 A 档——papers upsert + topic 自动创建 +
// paper_topics + collection_actions 单事务；result_ref 携带 inserted_ids。
func TestApplyIngestPapersResult(t *testing.T) {
	s := newTestStore(t)
	// 补 ingest 相关最小 schema（列级增量，幂等）
	for _, ddl := range []string{
		`ALTER TABLE papers ADD COLUMN IF NOT EXISTS source TEXT`,
		`ALTER TABLE papers ADD COLUMN IF NOT EXISTS source_id TEXT`,
		`ALTER TABLE papers ADD COLUMN IF NOT EXISTS publication_date DATE`,
		`CREATE TABLE IF NOT EXISTS topic_subscriptions (
			id TEXT PRIMARY KEY, name TEXT NOT NULL, query TEXT NOT NULL,
			enabled BOOLEAN NOT NULL DEFAULT true,
			created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())`,
		`CREATE TABLE IF NOT EXISTS paper_topics (
			id TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
			topic_id TEXT NOT NULL, UNIQUE(paper_id, topic_id))`,
		`CREATE TABLE IF NOT EXISTS collection_actions (
			id TEXT PRIMARY KEY, action_type TEXT NOT NULL, title TEXT NOT NULL, query TEXT,
			topic_id TEXT, paper_count INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ DEFAULT NOW())`,
		`CREATE TABLE IF NOT EXISTS action_papers (
			id TEXT PRIMARY KEY, action_id TEXT NOT NULL REFERENCES collection_actions(id) ON DELETE CASCADE,
			paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE, UNIQUE(action_id, paper_id))`,
	} {
		if _, err := s.DB.Exec(ddl); err != nil {
			t.Fatalf("schema: %v", err)
		}
	}

	_, taskID, _, err := s.SubmitCoreTask("ingest_arxiv_query", `{"query":"transformer"}`, "ingest:t:1", 600)
	if err != nil {
		t.Fatal(err)
	}
	own, err := s.ClaimTask("exec-1", []string{"ingest_arxiv_query"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v / %v", own, err)
	}

	proposal := map[string]any{
		"proposal": map[string]any{
			"kind": "ingest_papers", "query": "transformer",
			"topic_name": "e2e-topic", "action_type": "manual_collect",
			"action_title": "收集：transformer",
			"papers": []any{
				map[string]any{"arxiv_id": "2601.00011", "title": "Paper A", "abstract": "a", "source": "arxiv"},
				map[string]any{"arxiv_id": "2601.00012", "title": "Paper B", "abstract": "b", "source": "arxiv"},
			},
		},
	}
	status, err := s.ApplyResult(taskID, "exec-1", own.LeaseToken, proposal)
	if err != nil {
		t.Fatalf("apply: %v", err)
	}
	if !strings.Contains(status, "succeeded") {
		t.Fatalf("status=%s", status)
	}

	// papers 落库 + topic 自动创建 + 关联
	var paperCount int
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM papers WHERE arxiv_id IN ('2601.00011','2601.00012')`).Scan(&paperCount)
	if paperCount != 2 {
		t.Fatalf("papers=%d", paperCount)
	}
	var topicID string
	if err := s.DB.QueryRow(`SELECT id FROM topic_subscriptions WHERE name='e2e-topic'`).Scan(&topicID); err != nil {
		t.Fatalf("topic 未自动创建: %v", err)
	}
	var enabled bool
	_ = s.DB.QueryRow(`SELECT enabled FROM topic_subscriptions WHERE name='e2e-topic'`).Scan(&enabled)
	if enabled {
		t.Fatal("自动创建的 topic 应为 enabled=false")
	}
	var linkCount int
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM paper_topics WHERE topic_id=$1`, topicID).Scan(&linkCount)
	if linkCount != 2 {
		t.Fatalf("paper_topics=%d", linkCount)
	}
	// collection_actions + action_papers
	var actionCount, linkPaperCount int
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM collection_actions WHERE action_type='manual_collect'`).Scan(&actionCount)
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM action_papers ap JOIN collection_actions ca ON ca.id=ap.action_id WHERE ca.query='transformer'`).Scan(&linkPaperCount)
	if actionCount != 1 || linkPaperCount != 2 {
		t.Fatalf("actions=%d action_papers=%d", actionCount, linkPaperCount)
	}
	// result_ref 携带 inserted_ids
	var resultRef string
	_ = s.DB.QueryRow(`SELECT result_ref FROM core_tasks WHERE id=?`, taskID).Scan(&resultRef)
	if !strings.Contains(resultRef, "inserted_ids") {
		t.Fatalf("result_ref 缺 inserted_ids: %s", resultRef)
	}

	// 幂等：同 arxiv_id 二次提交不产生重复行
	_, taskID2, _, _ := s.SubmitCoreTask("ingest_arxiv_query", `{"query":"transformer"}`, "ingest:t:2", 600)
	own2, err := s.ClaimTask("exec-1", []string{"ingest_arxiv_query"})
	if err != nil || own2 == nil {
		t.Fatalf("re-claim: %v", err)
	}
	if _, err = s.ApplyResult(taskID2, "exec-1", own2.LeaseToken, proposal); err != nil {
		t.Fatal(err)
	}
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM papers WHERE arxiv_id IN ('2601.00011','2601.00012')`).Scan(&paperCount)
	if paperCount != 2 {
		t.Fatalf("重复提交产生重复论文: %d", paperCount)
	}
}
