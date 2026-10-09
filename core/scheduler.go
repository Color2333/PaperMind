// 调度器：reconciler（lease 收敛）+ 主题/CS 订阅定时抓取 + 闲时补偿。
//
// 设计要点：Python 的编排器任务层（submit + poll 子任务，须独立 orchestration
// 池防自死锁）在此整体消失——scheduler 直接提交叶子任务后立即返回，执行由
// runner 的资源类别信号量承载。原子性由幂等提交 + 任务层重试承接。
package core

import (
	"context"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"
)

// Scheduler 周期调度器。
type Scheduler struct {
	store *CoreStore
}

// NewScheduler 构建调度器。
func NewScheduler(store *CoreStore) *Scheduler {
	return &Scheduler{store: store}
}

// Start 阻塞运行全部调度循环直至 ctx 取消。
func (s *Scheduler) Start(ctx context.Context) {
	go s.reconcileLoop(ctx)      // 60s：过期 lease 回收 + dead_letter 兜底
	go s.topicDispatchLoop(ctx)  // 每小时：到点主题抓取
	go s.csFeedDispatchLoop(ctx) // 每小时：CS 分类表同步 + 到点订阅抓取
	go s.idleLoop(ctx)           // 10min：未读批处理 + skimmed 精读补偿
	go s.dailyBriefLoop(ctx)     // 每日：简报生成（cron 读 daily_report_configs）
	go s.weeklyGraphLoop(ctx)    // 每周日 22:00 UTC：引用图维护
	go s.heartbeatLoop(ctx)      // 60s：worker_heartbeat.json（system/worker 观察面）
	<-ctx.Done()
}

// heartbeatLoop 写心跳文件（pm_data 共享卷，system/worker 读 ts 判时效）。
func (s *Scheduler) heartbeatLoop(ctx context.Context) {
	path := envOr("WORKER_HEARTBEAT_FILE", "/app/data/worker_heartbeat.json")
	ticker := time.NewTicker(60 * time.Second)
	defer ticker.Stop()
	write := func() {
		payload := fmt.Sprintf(`{"ts":%d,"error":null}`, time.Now().Unix())
		tmp := path + ".tmp"
		if err := os.WriteFile(tmp, []byte(payload), 0o644); err != nil {
			return
		}
		_ = os.Rename(tmp, path)
	}
	write()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			write()
		}
	}
}

// reconcileLoop 过期 lease 回收（ReclaimExpired 由 core 主进程也可调用，
// worker 内独立兜底）。
func (s *Scheduler) reconcileLoop(ctx context.Context) {
	ticker := time.NewTicker(60 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		reclaimed, err := s.store.ReclaimExpired(60)
		if err != nil {
			log.Printf("[scheduler] reclaim error: %v", err)
			continue
		}
		if len(reclaimed) > 0 {
			log.Printf("[scheduler] reclaimed %d expired tasks", len(reclaimed))
		}
	}
}

// ---------- 每日简报（原 brief_job cron） ----------

// parseDailyCronHour 从 cron 表达式取小时（"0 4 * * *" → 4）；解析失败默认 4。
func parseDailyCronHour(cron string) int {
	fields := strings.Fields(strings.TrimSpace(cron))
	if len(fields) >= 2 {
		if h, err := strconv.Atoi(fields[1]); err == nil && h >= 0 && h < 24 {
			return h
		}
	}
	return 4
}

func (s *Scheduler) dailyBriefLoop(ctx context.Context) {
	ticker := time.NewTicker(10 * time.Minute)
	defer ticker.Stop()
	lastFired := ""
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		now := time.Now().UTC()
		dayKey := now.Format("2006-01-02") + "T" + strconv.Itoa(now.Hour())
		if dayKey == lastFired {
			continue
		}
		// cron 从配置读（默认 04:00 UTC = 北京 12:00）
		hour := 4
		var cronExpr string
		var sendEmail bool
		if err := s.store.DB.QueryRow(
			`SELECT COALESCE(cron_expression,''), COALESCE(send_email_report,false) FROM daily_report_configs LIMIT 1`,
		).Scan(&cronExpr, &sendEmail); err == nil && cronExpr != "" {
			hour = parseDailyCronHour(cronExpr)
		}
		if now.Hour() != hour {
			continue
		}
		lastFired = dayKey
		input := "{}"
		if sendEmail {
			input = `{"recipient":""}` // recipient 空串触发配置读取
		}
		if _, _, _, err := s.store.SubmitCoreTask("daily_brief_publish", input, "", 1800); err != nil {
			log.Printf("[scheduler] daily_brief submit failed: %v", err)
			continue
		}
		log.Printf("[scheduler] daily_brief submitted (hour=%d)", hour)
	}
}

// ---------- 每周图谱维护（原 weekly_graph_job cron） ----------

func (s *Scheduler) weeklyGraphLoop(ctx context.Context) {
	ticker := time.NewTicker(30 * time.Minute)
	defer ticker.Stop()
	lastFired := ""
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		now := time.Now().UTC()
		// 周日 22:00 UTC（= 北京周一 06:00，与 Python weekly_cron 默认一致）
		if now.Weekday() != time.Sunday || now.Hour() != 22 {
			continue
		}
		weekKey := now.Format("2006-W02") // 近似周标识，防同周重复
		if weekKey == lastFired {
			continue
		}
		lastFired = weekKey
		if _, _, _, err := s.store.SubmitCoreTask("weekly_graph_maintenance", "{}", "", 3600); err != nil {
			log.Printf("[scheduler] weekly_graph submit failed: %v", err)
			continue
		}
		log.Printf("[scheduler] weekly_graph_maintenance submitted")
	}
}

// ---------- 主题调度（原 topic_dispatch 编排器内联为循环） ----------

// topicDue 判断主题当前整点是否到点（Python _should_run 移植）。
func topicDue(freq string, timeUTC, hour, weekday int) bool {
	switch freq {
	case "hourly":
		return true
	case "twice_daily":
		return hour == timeUTC || hour == (timeUTC+12)%24
	case "weekdays":
		return weekday < 5 && hour == timeUTC
	case "weekly":
		return weekday == 0 && hour == timeUTC
	default: // daily
		return hour == timeUTC
	}
}

func (s *Scheduler) topicDispatchLoop(ctx context.Context) {
	ticker := time.NewTicker(10 * time.Minute)
	defer ticker.Stop()
	lastFired := "" // "2006-01-02T15" 防同小时重复触发
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		now := time.Now().UTC()
		hourKey := now.Format("2006-01-02T15")
		if hourKey == lastFired {
			continue
		}
		rows, err := s.store.DB.Query(
			`SELECT id, name, COALESCE(schedule_frequency,'daily'), COALESCE(schedule_time_utc,21)
			 FROM topic_subscriptions WHERE enabled = true`)
		if err != nil {
			log.Printf("[scheduler] topic query error: %v", err)
			continue
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
		if len(due) == 0 {
			continue
		}
		lastFired = hourKey
		triggered := 0
		for _, t := range due {
			if err := s.submitTopicFetch(t.id); err != nil {
				log.Printf("[scheduler] topic %s fetch submit failed: %v", t.name, err)
				continue
			}
			triggered++
		}
		log.Printf("[scheduler] topic_dispatch: %d/%d due topics triggered", triggered, len(due))
	}
}

// submitTopicFetch 读主题配置并提交 ingest_arxiv_query 叶子任务。
func (s *Scheduler) submitTopicFetch(topicID string) error {
	var query string
	var maxResults, daysBack int
	var enableDateFilter bool
	err := s.store.DB.QueryRow(
		`SELECT query, max_results_per_run, enable_date_filter, date_filter_days
		 FROM topic_subscriptions WHERE id=$1 AND enabled = true`, topicID,
	).Scan(&query, &maxResults, &enableDateFilter, &daysBack)
	if err != nil {
		return err
	}
	if !enableDateFilter {
		daysBack = 0
	}
	inputJSON := mustJSON(map[string]any{
		"query": query, "max_results": clampInt(maxResults, 1, 200),
		"topic_id": topicID, "days_back": clampInt(daysBack, 0, 3650),
		"action_type": "auto_collect",
	})
	_, _, _, err = s.store.SubmitCoreTask("ingest_arxiv_query", inputJSON, "", 900)
	return err
}

// ---------- CS 分类调度（原 cs_feed_dispatch 的调度侧） ----------

func (s *Scheduler) csFeedDispatchLoop(ctx context.Context) {
	ticker := time.NewTicker(10 * time.Minute)
	defer ticker.Stop()
	lastFired := ""
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		now := time.Now().UTC()
		hourKey := now.Format("2006-01-02T15")
		if hourKey == lastFired {
			continue
		}
		// 提交 cs_feed_dispatch 任务（分类同步 proposal + 到点订阅抓取提交，
		// 复用 A 档 applyCsCategoriesSyncResult 落分类表）
		if _, _, _, err := s.store.SubmitCoreTask("cs_feed_dispatch", "{}", "", 1200); err != nil {
			log.Printf("[scheduler] cs_feed_dispatch submit failed: %v", err)
			continue
		}
		lastFired = hourKey
		log.Printf("[scheduler] cs_feed_dispatch submitted")
	}
}

// ---------- 闲时补偿（原 idle_processor 编排器内联为循环） ----------

// inFlightPaperIDs 指定 capability 仍在排队/执行中的 paper_id 集合（防重提）。
func (s *Scheduler) inFlightPaperIDs(capability string) map[string]bool {
	out := map[string]bool{}
	rows, err := s.store.DB.Query(
		`SELECT input_ref->>'paper_id' FROM core_tasks
		 WHERE capability=$1 AND status IN ('queued','leased','cancelling')`, capability)
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var pid *string
		if rows.Scan(&pid) == nil && pid != nil {
			out[*pid] = true
		}
	}
	return out
}

// queueDepth 当前排队任务数（闲时判定：队列为空才补偿）。
func (s *Scheduler) queueDepth() int {
	var n int
	if err := s.store.DB.QueryRow(
		`SELECT COUNT(*) FROM core_tasks WHERE status='queued'`).Scan(&n); err != nil {
		return -1 // 查询失败按繁忙处理
	}
	return n
}

func (s *Scheduler) idleLoop(ctx context.Context) {
	ticker := time.NewTicker(10 * time.Minute)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		if s.queueDepth() > 0 {
			continue // 队列非空——不算空闲
		}
		s.compensateUnread()
		s.compensateStuckSkimmed()
	}
}

// compensateUnread 未读论文批处理补偿：逐篇提交 embed + skim（在途去重）。
func (s *Scheduler) compensateUnread() {
	const batchLimit = 5
	inFlightEmbed := s.inFlightPaperIDs("embed_paper")
	inFlightSkim := s.inFlightPaperIDs("skim_paper")
	rows, err := s.store.DB.Query(
		`SELECT p.id FROM papers p
		 LEFT JOIN analysis_reports ar ON ar.paper_id = p.id
		 WHERE p.read_status='unread' AND (ar.summary_md IS NULL OR ar.id IS NULL)
		 ORDER BY p.created_at ASC LIMIT $1`, batchLimit*2)
	if err != nil {
		return
	}
	var ids []string
	for rows.Next() {
		var id string
		if rows.Scan(&id) == nil {
			ids = append(ids, id)
		}
	}
	rows.Close()

	submitted := 0
	for _, pid := range ids {
		if submitted >= batchLimit {
			break
		}
		if inFlightEmbed[pid] || inFlightSkim[pid] {
			continue
		}
		inputJSON := mustJSON(map[string]any{"paper_id": pid})
		if _, _, _, err := s.store.SubmitCoreTask("embed_paper", inputJSON, "", 300); err != nil {
			continue
		}
		if _, _, _, err := s.store.SubmitCoreTask("skim_paper", inputJSON, "", 900); err != nil {
			continue
		}
		inFlightEmbed[pid], inFlightSkim[pid] = true, true
		submitted++
	}
	if submitted > 0 {
		log.Printf("[scheduler] idle batch: submitted embed+skim for %d unread papers", submitted)
	}
}

// compensateStuckSkimmed 已 skim 但卡住未精读的论文补偿（Critical #6；
// pdf_unavailable 永久排除——否则 404 死信每轮重提）。
func (s *Scheduler) compensateStuckSkimmed() {
	const quota = 2
	inFlight := s.inFlightPaperIDs("deep_read_paper")
	rows, err := s.store.DB.Query(
		`SELECT p.id FROM papers p
		 JOIN analysis_reports ar ON ar.paper_id = p.id
		 WHERE p.read_status='skimmed' AND ar.summary_md IS NOT NULL AND ar.deep_dive_md IS NULL
		   AND (p.metadata->>'pdf_unavailable') IS DISTINCT FROM 'true'
		 ORDER BY p.created_at ASC LIMIT $1`, quota*2)
	if err != nil {
		return
	}
	var ids []string
	for rows.Next() {
		var id string
		if rows.Scan(&id) == nil {
			ids = append(ids, id)
		}
	}
	rows.Close()

	submitted := 0
	for _, pid := range ids {
		if submitted >= quota {
			break
		}
		if inFlight[pid] {
			continue
		}
		inputJSON := mustJSON(map[string]any{"paper_id": pid})
		if _, _, _, err := s.store.SubmitCoreTask("deep_read_paper", inputJSON, "", 1800); err != nil {
			continue
		}
		inFlight[pid] = true
		submitted++
	}
	if submitted > 0 {
		log.Printf("[scheduler] idle compensation: submitted %d deep_read for stuck skimmed papers", submitted)
	}
}
