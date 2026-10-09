// 编排器处理器（fire-and-forget）：原 Python orchestration 池的 submit+wait
// 编排器在 Go 侧全部退化为"读库选目标 → 提交叶子任务 → 立即返回"——无等待
// 即无自死锁，进度经任务图观察面聚合（按叶子任务完成数）。
package core

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"
)

// submitLeaf 提交叶子任务的小包装。
func submitLeaf(e *HandlerEnv, capability string, input map[string]any, timeoutS int) (string, error) {
	_, taskID, _, err := e.Store.SubmitCoreTask(capability, mustJSON(input), "", timeoutS)
	return taskID, err
}

// HandleBatchProcessUnread batch_process_unread：未读论文逐篇提交 embed+skim。
func HandleBatchProcessUnread(_ context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	maxPapers := intOf(task.Input["max_papers"], 50)
	if maxPapers <= 0 {
		maxPapers = 50
	}
	rows, err := e.Store.DB.Query(
		`SELECT p.id FROM papers p
		 LEFT JOIN analysis_reports ar ON ar.paper_id = p.id
		 WHERE p.read_status='unread' AND (ar.summary_md IS NULL OR ar.id IS NULL)
		 ORDER BY p.created_at ASC LIMIT $1`, maxPapers)
	if err != nil {
		return nil, err
	}
	var ids []string
	for rows.Next() {
		var id string
		if rows.Scan(&id) == nil {
			ids = append(ids, id)
		}
	}
	rows.Close()
	submitted, skipped := 0, 0
	for _, pid := range ids {
		if _, err := submitLeaf(e, "embed_paper", map[string]any{"paper_id": pid}, 300); err != nil {
			skipped++
			continue
		}
		if _, err := submitLeaf(e, "skim_paper", map[string]any{"paper_id": pid}, 900); err != nil {
			skipped++
			continue
		}
		submitted++
	}
	log.Printf("[orch] batch_process_unread: submitted %d (skipped %d)", submitted, skipped)
	return map[string]any{"submitted": submitted, "skipped": skipped}, nil
}

// HandleSkimPapersBatch skim_papers_batch：指定论文逐篇提交 skim。
func HandleSkimPapersBatch(_ context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	ids := stringListOf(task.Input["paper_ids"])
	ok, failed := 0, 0
	for _, pid := range ids {
		if _, err := submitLeaf(e, "skim_paper", map[string]any{"paper_id": pid}, 900); err != nil {
			failed++
			continue
		}
		ok++
	}
	return map[string]any{"skimmed": ok, "failed": failed, "skipped": 0, "total": len(ids)}, nil
}

// HandleWeeklyGraphMaintenance weekly_graph_maintenance：逐主题引用同步 + 增量。
func HandleWeeklyGraphMaintenance(_ context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	rows, err := e.Store.DB.Query(`SELECT id, name FROM topic_subscriptions WHERE enabled = true`)
	if err != nil {
		return nil, err
	}
	type tid struct{ id, name string }
	var topics []tid
	for rows.Next() {
		var t tid
		if rows.Scan(&t.id, &t.name) == nil {
			topics = append(topics, t)
		}
	}
	rows.Close()
	submitted := 0
	for _, t := range topics {
		if _, err := submitLeaf(e, "sync_citations_topic", map[string]any{
			"topic_id": t.id, "paper_limit": 20, "edge_limit_per_paper": 6,
		}, 1800); err != nil {
			log.Printf("[orch] weekly topic %s submit failed: %v", t.name, err)
			continue
		}
		submitted++
	}
	if _, err := submitLeaf(e, "sync_citations_incremental", map[string]any{
		"paper_limit": 50, "edge_limit_per_paper": 6,
	}, 1800); err == nil {
		submitted++
	}
	log.Printf("[orch] weekly_graph_maintenance: submitted %d citation sync tasks", submitted)
	return map[string]any{"submitted": submitted}, nil
}

// HandleDailyIngestAndBrief daily_ingest_and_brief：到点主题抓取 + 简报任务链提交。
func HandleDailyIngestAndBrief(_ context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	// 1. 到点主题逐个提交 ingest（与 scheduler topicDue 同判定）
	submitted := 0
	if err := e.schedulerTopicDispatch(); err != nil {
		log.Printf("[orch] daily topic dispatch error: %v", err)
	}
	// 2. 简报任务
	if _, err := submitLeaf(e, "daily_brief_publish", map[string]any{}, 1800); err == nil {
		submitted++
	}
	return map[string]any{"submitted": submitted}, nil
}

// HandleDailyReportWorkflow daily_report_workflow：精读链 + 简报 + 邮件（全 fire-and-forget）。
func HandleDailyReportWorkflow(_ context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	// 高分未精读论文 → deep_read（前 2 篇，与 Python max_deep_reads 对齐）
	rows, err := e.Store.DB.Query(
		`SELECT p.id FROM papers p
		 JOIN analysis_reports ar ON ar.paper_id = p.id
		 WHERE p.read_status='skimmed' AND ar.deep_dive_md IS NULL
		   AND (p.metadata->>'pdf_unavailable') IS DISTINCT FROM 'true'
		 ORDER BY COALESCE(ar.skim_score,0) DESC LIMIT 2`)
	if err == nil {
		var ids []string
		for rows.Next() {
			var id string
			if rows.Scan(&id) == nil {
				ids = append(ids, id)
			}
		}
		rows.Close()
		for _, pid := range ids {
			_, _ = submitLeaf(e, "deep_read_paper", map[string]any{"paper_id": pid}, 1800)
		}
	}
	// 简报（含邮件收件人逻辑在 handler 内）
	if _, err := submitLeaf(e, "daily_brief_publish", map[string]any{}, 1800); err != nil {
		return nil, err
	}
	return map[string]any{"submitted": true, "note": "deep_read + brief chain submitted"}, nil
}

// HandleDailyReportSendOnly daily_report_send_only：直接生成简报并发邮件。
func HandleDailyReportSendOnly(ctx context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	recipient, _ := task.Input["recipient"].(string)
	if recipient == "" {
		recipient = e.briefRecipientFromConfig()
	}
	if recipient == "" {
		return nil, fmt.Errorf("未配置收件人（recipient 参数或 daily_report_configs）")
	}
	html, _ := e.BuildDailyBrief(ctx, 30)
	effectKey := "brief_mail:" + recipient + ":" + userDateStr()
	if HasEffect(e.Store, effectKey) {
		return map[string]any{"sent": false, "skipped": true, "effect_key": effectKey}, nil
	}
	if !e.SMTPSend(recipient, "PaperMind Daily Report", html) {
		return map[string]any{"sent": false, "error": "SMTP 未配置或发送失败"}, nil
	}
	RegisterEffect(e.Store, effectKey, "mail_send", task.TaskID)
	return map[string]any{"sent": true, "effect_key": effectKey}, nil
}

// SMTPSend env.SMTP 包装（nil 安全）。
func (e *HandlerEnv) SMTPSend(recipient, subject, html string) bool {
	return SendEmailHTML(e.SMTP, recipient, subject, html)
}

// schedulerTopicDispatch 把 scheduler.go 的到点主题提交逻辑复用为编排器步骤。
func (e *HandlerEnv) schedulerTopicDispatch() error {
	now := timeNowUTC()
	rows, err := e.Store.DB.Query(
		`SELECT id, name, COALESCE(schedule_frequency,'daily'), COALESCE(schedule_time_utc,21)
		 FROM topic_subscriptions WHERE enabled = true`)
	if err != nil {
		return err
	}
	type topic struct {
		id, name, freq string
		timeUTC        int
	}
	var due []topic
	for rows.Next() {
		var t topic
		if rows.Scan(&t.id, &t.name, &t.freq, &t.timeUTC) == nil {
			if topicDue(t.freq, t.timeUTC, now.Hour(), int(now.Weekday())) {
				due = append(due, t)
			}
		}
	}
	rows.Close()
	for _, t := range due {
		var query string
		var maxResults, daysBack int
		var enableDateFilter bool
		err := e.Store.DB.QueryRow(
			`SELECT query, max_results_per_run, enable_date_filter, date_filter_days
			 FROM topic_subscriptions WHERE id=$1 AND enabled = true`, t.id,
		).Scan(&query, &maxResults, &enableDateFilter, &daysBack)
		if err != nil {
			continue
		}
		if !enableDateFilter {
			daysBack = 0
		}
		input := map[string]any{
			"query": strings.TrimSpace(query), "max_results": clampInt(maxResults, 1, 200),
			"topic_id": t.id, "days_back": clampInt(daysBack, 0, 3650),
			"action_type": "auto_collect",
		}
		if _, err := submitLeaf(e, "ingest_arxiv_query", input, 900); err != nil {
			log.Printf("[orch] topic %s ingest submit failed: %v", t.name, err)
		}
	}
	return nil
}

// timeNowUTC 当前 UTC 时间（orchestrators/scheduler 共用）。
func timeNowUTC() time.Time { return time.Now().UTC() }
