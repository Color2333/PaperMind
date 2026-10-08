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

// TestSQLiteApplyCsFeedAndCategories：CS 分类抓取 + 分类表同步（A 档）在 SQLite
// 方言下的真实写入——papers + csfeed:{code} 主题（enabled=false）+ 订阅运行
// 状态累加；cs_categories upsert 幂等。
func TestSQLiteApplyCsFeedAndCategories(t *testing.T) {
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
		`CREATE TABLE IF NOT EXISTS cs_categories (
			code TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, cached_at TEXT)`,
		`CREATE TABLE IF NOT EXISTS cs_feed_subscriptions (
			id TEXT PRIMARY KEY, category_code TEXT, daily_limit INTEGER DEFAULT 30,
			enabled INTEGER DEFAULT 1, status TEXT DEFAULT 'active', cool_down_until TEXT,
			last_run_at TEXT, last_run_count INTEGER DEFAULT 0, created_at TEXT)`,
	}
	for _, d := range ddl {
		if _, err := s.DB.Exec(d); err != nil {
			t.Fatalf("schema: %v", err)
		}
	}
	if _, err := s.DB.Exec(
		`INSERT INTO cs_feed_subscriptions (id, category_code) VALUES ('sub-1', 'cs.AI')`,
	); err != nil {
		t.Fatal(err)
	}

	// ---- 分类表同步（cs_feed_dispatch 的 proposal）----
	_, taskID, _, err := s.SubmitCoreTask("cs_feed_dispatch", `{}`, "cs:dispatch:1", 600)
	if err != nil {
		t.Fatal(err)
	}
	own, err := s.ClaimTask("exec-1", []string{"cs_feed_dispatch"})
	if err != nil || own == nil {
		t.Fatalf("claim: %v / %v", own, err)
	}
	cats := map[string]any{
		"proposal": map[string]any{
			"kind": "cs_categories_sync",
			"categories": []any{
				map[string]any{"code": "cs.AI", "name": "Artificial Intelligence", "description": "AI"},
				map[string]any{"code": "cs.LG", "name": "Machine Learning", "description": "ML"},
			},
		},
	}
	status, err := s.ApplyResult(taskID, "exec-1", own.LeaseToken, cats)
	if err != nil || !strings.Contains(status, "succeeded (synced=2)") {
		t.Fatalf("categories apply: %v / %q", err, status)
	}
	// 幂等重放
	_, taskIDc2, _, _ := s.SubmitCoreTask("cs_feed_dispatch", `{}`, "cs:dispatch:2", 600)
	ownc2, _ := s.ClaimTask("exec-1", []string{"cs_feed_dispatch"})
	if _, err = s.ApplyResult(taskIDc2, "exec-1", ownc2.LeaseToken, cats); err != nil {
		t.Fatalf("categories re-apply: %v", err)
	}
	var catCount int
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM cs_categories`).Scan(&catCount)
	if catCount != 2 {
		t.Fatalf("cs_categories upsert 产生重复: %d", catCount)
	}

	// ---- 分类抓取（cs_feed_fetch_category 的 proposal）----
	_, taskID2, _, err := s.SubmitCoreTask("cs_feed_fetch_category", `{"category_code":"cs.AI"}`, "cs:fetch:1", 600)
	if err != nil {
		t.Fatal(err)
	}
	own2, err := s.ClaimTask("exec-1", []string{"cs_feed_fetch_category"})
	if err != nil || own2 == nil {
		t.Fatalf("claim fetch: %v / %v", own2, err)
	}
	fetch := map[string]any{
		"proposal": map[string]any{
			"kind": "cs_feed_fetch", "category_code": "cs.AI",
			"papers": []any{
				map[string]any{"arxiv_id": "2601.00021", "title": "CS A", "abstract": "a", "source": "arxiv"},
				map[string]any{"arxiv_id": "2601.00022", "title": "CS B", "abstract": "b", "source": "arxiv"},
			},
		},
	}
	status, err = s.ApplyResult(taskID2, "exec-1", own2.LeaseToken, fetch)
	if err != nil || !strings.Contains(status, "succeeded (papers=2)") {
		t.Fatalf("cs fetch apply: %v / %q", err, status)
	}

	var topicID string
	var enabled int
	if err := s.DB.QueryRow(
		`SELECT id, enabled FROM topic_subscriptions WHERE name='csfeed:cs.AI'`,
	).Scan(&topicID, &enabled); err != nil {
		t.Fatalf("csfeed topic 未创建: %v", err)
	}
	if enabled != 0 {
		t.Fatal("csfeed topic 应为 enabled=false")
	}
	var links, lastRunCount, count int
	var lastRunAt string
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM paper_topics WHERE topic_id=$1`, topicID).Scan(&links)
	if links != 2 {
		t.Fatalf("paper_topics=%d", links)
	}
	if err := s.DB.QueryRow(
		`SELECT last_run_count, last_run_at FROM cs_feed_subscriptions WHERE id='sub-1'`,
	).Scan(&lastRunCount, &lastRunAt); err != nil {
		t.Fatalf("订阅状态未更新: %v", err)
	}
	if lastRunCount != 2 {
		t.Fatalf("last_run_count=%d（应为当日累加 2）", lastRunCount)
	}

	// 同日二次抓取：last_run_count 累加（4），papers/links 不重复
	_, taskID3, _, _ := s.SubmitCoreTask("cs_feed_fetch_category", `{"category_code":"cs.AI"}`, "cs:fetch:2", 600)
	own3, _ := s.ClaimTask("exec-1", []string{"cs_feed_fetch_category"})
	if _, err = s.ApplyResult(taskID3, "exec-1", own3.LeaseToken, fetch); err != nil {
		t.Fatalf("cs fetch re-apply: %v", err)
	}
	_ = s.DB.QueryRow(`SELECT last_run_count FROM cs_feed_subscriptions WHERE id='sub-1'`).Scan(&lastRunCount)
	if lastRunCount != 4 {
		t.Fatalf("同日 last_run_count=%d（应累加为 4）", lastRunCount)
	}
	_ = s.DB.QueryRow(`SELECT COUNT(*) FROM papers WHERE arxiv_id LIKE '2601.0002%'`).Scan(&count)
	if count != 2 {
		t.Fatalf("重复抓取产生重复论文: %d", count)
	}
}
