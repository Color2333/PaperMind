package core

import (
	"database/sql"
	"os"
	"testing"
)

// TestMain 如果设置了 PAPER_TEST_PG_DSN 则用 PG 跑测试，否则 skip（需 docker compose up postgres）
func newPGTestStore(t *testing.T) *CoreStore {
	t.Helper()
	dsn := os.Getenv("PAPER_TEST_PG_DSN")
	if dsn == "" {
		dsn = "host=localhost port=5432 dbname=papermind_test user=papermind password=papermind sslmode=disable"
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Skipf("PG 不可用（跳过存储测试）: %v", err)
	}
	if err = db.Ping(); err != nil {
		db.Close()
		t.Skipf("PG 不可用（跳过存储测试）: %v", err)
	}
	// 清理 core_* 表（测试隔离）
	for _, table := range []string{"core_attempts", "core_tasks", "core_jobs"} {
		db.Exec(`DROP TABLE IF EXISTS ` + table)
	}
	s := &CoreStore{DB: db}
	if err := s.initSchema(); err != nil {
		db.Close()
		t.Skipf("PG schema init: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}
