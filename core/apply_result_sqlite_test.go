package core

// SQLite 方言 apply 验证：PG 存储测试在无 PG 环境整体 skip，而 SQLite 是
// 文件库生产形态——此前 apply 层运行时 SQL 用 PG 方言 NOW()，在 modernc/sqlite
// 直接语法错误且无测试拦截。本测试用 OpenCoreStore(临时文件库) 验证
// applyIngestPapersResult 在 SQLite 下的真实写入（含 IEEE 合成键）。

import (
	"strings"
	"testing"
)

func TestSQLiteApplyIngestPapersIEEE(t *testing.T) {
	s, err := OpenCoreStore(t.TempDir() + "/core.db")
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer s.Close()

	ddl := []string{
		`CREATE TABLE IF NOT EXISTS papers (
			id TEXT PRIMARY KEY, title TEXT NOT NULL, abstract TEXT NOT NULL DEFAULT '',
			arxiv_id TEXT UNIQUE, read_status TEXT NOT NULL DEFAULT 'unread',
			metadata TEXT, pdf_path TEXT, source TEXT, source_id TEXT,
			publication_date TEXT, doi TEXT, created_at TEXT, updated_at TEXT)`,
		`CREATE TABLE IF NOT EXISTS topic_subscriptions (
			id TEXT PRIMARY KEY, name TEXT NOT NULL, query TEXT NOT NULL,
			enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT)`,
		`CREATE TABLE IF NOT EXISTS paper_topics (
			id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, topic_id TEXT NOT NULL,
			UNIQUE(paper_id, topic_id))`,
		`CREATE TABLE IF NOT EXISTS collection_actions (
			id TEXT PRIMARY KEY, action_type TEXT NOT NULL, title TEXT NOT NULL, query TEXT,
			topic_id TEXT, paper_count INTEGER NOT NULL DEFAULT 0, created_at TEXT)`,
		`CREATE TABLE IF NOT EXISTS action_papers (
			id TEXT PRIMARY KEY, action_id TEXT NOT NULL, paper_id TEXT NOT NULL,
			UNIQUE(action_id, paper_id))`,
	}
	for _, d := range ddl {
		if _, err := s.DB.Exec(d); err != nil {
			t.Fatalf("schema: %v", err)
		}
	}

	_, taskID, _, err := s.SubmitCoreTask("ingest_ieee", `{"query":"federated learning"}`, "ingest:ieee:1", 600)
	if err != nil {
		t.Fatalf("submit: %v", err)
	}
	own, err := s.ClaimTask("exec-1", []string{"ingest_ieee"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v / %v", own, err)
	}
	proposal := map[string]any{
		"proposal": map[string]any{
			"kind": "ingest_papers", "query": "federated learning",
			"topic_id": "", "action_type": "auto_collect",
			"action_title": "IEEE 收集：federated learning",
			"papers": []any{
				map[string]any{
					"arxiv_id": "ieee:10185093", "title": "FedPaper", "abstract": "a",
					"source": "ieee", "source_id": "10185093", "doi": "10.1109/x.2024.1",
					"publication_date": "2024-06-01",
				},
				map[string]any{
					"arxiv_id": "2601.00011", "title": "ArxivPaper", "abstract": "b",
					"source": "arxiv",
				},
			},
		},
	}
	status, err := s.ApplyResult(taskID, "exec-1", own.LeaseToken, proposal)
	if err != nil {
		t.Fatalf("apply: %v", err)
	}
	if !strings.Contains(status, "succeeded (papers=2)") {
		t.Fatalf("status=%q", status)
	}

	var sourceID, doi string
	if err := s.DB.QueryRow(
		`SELECT source_id, doi FROM papers WHERE arxiv_id='ieee:10185093'`,
	).Scan(&sourceID, &doi); err != nil {
		t.Fatalf("IEEE 合成键论文未落库: %v", err)
	}
	if sourceID != "10185093" || doi != "10.1109/x.2024.1" {
		t.Fatalf("source_id=%q doi=%q", sourceID, doi)
	}
	var count int
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM collection_actions`).Scan(&count)
	if count != 1 {
		t.Fatalf("collection_actions=%d", count)
	}

	// 幂等重放：同 proposal 二次 apply 无重复
	_, taskID2, _, _ := s.SubmitCoreTask("ingest_ieee", `{"query":"federated learning"}`, "ingest:ieee:2", 600)
	own2, err := s.ClaimTask("exec-1", []string{"ingest_ieee"})
	if err != nil || own2 == nil {
		t.Fatalf("re-claim: %v", err)
	}
	if _, err = s.ApplyResult(taskID2, "exec-1", own2.LeaseToken, proposal); err != nil {
		t.Fatalf("re-apply: %v", err)
	}
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM papers WHERE arxiv_id IN ('ieee:10185093','2601.00011')`).Scan(&count)
	if count != 2 {
		t.Fatalf("重复 apply 产生重复论文: %d", count)
	}
}
