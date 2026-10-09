// Phase 4 读面/生成面：pipelines 提交、RAG、任务追踪、content、writing。
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"
)

// ---------- pipelines（提交面，叶子任务由 Go worker 执行） ----------

// handleStartSkim POST /pipelines/skim/{paper_id}。
func (s *Server) handleStartSkim(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	jobID, taskID, err := s.submitCoreTask("skim_paper", map[string]any{"paper_id": paperID}, 900)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleStartSkimBatch POST /pipelines/skim-batch。
func (s *Server) handleStartSkimBatch(w http.ResponseWriter, r *http.Request) {
	var body struct {
		PaperIDs []string `json:"paper_ids"`
	}
	if err := readBody(r, &body); err != nil || len(body.PaperIDs) == 0 {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "paper_ids is required"})
		return
	}
	jobID, taskID, err := s.submitCoreTask("skim_papers_batch", map[string]any{"paper_ids": body.PaperIDs}, 3600)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleStartDeep POST /pipelines/deep/{paper_id}。
func (s *Server) handleStartDeep(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	jobID, taskID, err := s.submitCoreTask("deep_read_paper", map[string]any{"paper_id": paperID}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleStartEmbed POST /pipelines/embed/{paper_id}。
func (s *Server) handleStartEmbed(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	jobID, taskID, err := s.submitCoreTask("embed_paper", map[string]any{"paper_id": paperID}, 300)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// ---------- 任务追踪（/tasks/*） ----------

// taskView 统一观察面（与 Python get_task_info 形状对齐）。
func (s *Server) taskView(taskID string) (map[string]any, error) {
	var capability, status string
	var attemptCount, maxAttempts int
	var inputRef, resultRef sql.NullString
	var createdAt string
	err := s.db.QueryRow(
		`SELECT capability, status, attempt_count, max_attempts, COALESCE(input_ref::text,''),
		        COALESCE(result_ref::text,''), TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')
		 FROM core_tasks WHERE id=$1`, taskID,
	).Scan(&capability, &status, &attemptCount, &maxAttempts, &inputRef, &resultRef, &createdAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	finished := status == "succeeded" || status == "failed" || status == "dead_letter" || status == "cancelled"
	success := status == "succeeded"
	view := map[string]any{
		"task_id": taskID, "id": taskID, "capability": capability, "status": status,
		"attempt_count": attemptCount, "max_attempts": maxAttempts,
		"finished": finished, "success": success,
		"created_at": createdAt,
	}
	if resultRef.Valid && resultRef.String != "" && resultRef.String != "{}" {
		var res map[string]any
		if json.Unmarshal([]byte(resultRef.String), &res) == nil {
			// result_ref 里 proposal 已 apply——摘要键直出（前端轮询 /result 用）
			view["result"] = res
			if total, ok := res["total"].(float64); ok {
				view["inserted"] = int(total)
			}
			if ids, ok := res["inserted_ids"].([]any); ok {
				view["inserted_ids"] = ids
			}
		}
	}
	return view, nil
}

// handleTaskActive GET /tasks/active。
func (s *Server) handleTaskActive(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(
		`SELECT id, capability, status, TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')
		 FROM core_tasks WHERE status IN ('queued','leased','cancelling')
		 ORDER BY created_at DESC LIMIT 100`)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	tasks := []map[string]any{}
	for rows.Next() {
		var id, capability, status, createdAt string
		if rows.Scan(&id, &capability, &status, &createdAt) == nil {
			tasks = append(tasks, map[string]any{
				"task_id": id, "capability": capability, "status": status, "created_at": createdAt,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"tasks": tasks})
}

// handleTaskStatus GET /tasks/{task_id}。
func (s *Server) handleTaskStatus(w http.ResponseWriter, r *http.Request) {
	view, err := s.taskView(r.PathValue("task_id"))
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if view == nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Task not found"})
		return
	}
	writeJSON(w, http.StatusOK, view)
}

// handleTaskResult GET /tasks/{task_id}/result。
func (s *Server) handleTaskResult(w http.ResponseWriter, r *http.Request) {
	view, err := s.taskView(r.PathValue("task_id"))
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if view == nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Task not found"})
		return
	}
	if res, ok := view["result"].(map[string]any); ok {
		writeJSON(w, http.StatusOK, res)
		return
	}
	if finished, ok := view["finished"].(bool); ok && finished {
		writeJSON(w, http.StatusOK, map[string]any{})
		return
	}
	writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "Task not finished yet"})
}

// handleStartTopicWiki POST /tasks/wiki/topic —— 后台 wiki 生成任务提交。
func (s *Server) handleStartTopicWiki(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	if keyword == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "keyword is required"})
		return
	}
	limit := queryInt(r, "limit", 120)
	jobID, taskID, err := s.submitCoreTask("topic_wiki_save", map[string]any{"keyword": keyword, "limit": limit}, 900)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// ---------- RAG（检索 + 网关 LLM） ----------

// handleRagAsk POST /rag/ask（ask-iterative 同 shape，轮数固定 1——
// 多轮质量自评在网关单次调用下收益有限，保留端点兼容）。
func (s *Server) handleRagAsk(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Question string `json:"question"`
		TopK     int    `json:"top_k"`
	}
	if err := readBody(r, &body); err != nil || strings.TrimSpace(body.Question) == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "question is required"})
		return
	}
	topK := body.TopK
	if topK <= 0 {
		topK = 5
	}
	answer, cited, evidence, err := s.ragAsk(r.Context(), body.Question, topK)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"answer": answer, "cited_paper_ids": cited, "evidence": evidence,
	})
}

// ragAsk 词法+语义混合检索 → 上下文拼装 → 网关 skim 模型作答。
func (s *Server) ragAsk(ctx context.Context, question string, topK int) (string, []string, []map[string]any, error) {
	pattern := "%" + question + "%"
	rows, err := s.db.Query(
		`SELECT p.id, p.title, COALESCE(p.abstract,''),
		        COALESCE(ar.summary_md,''), COALESCE(ar.deep_dive_md,'')
		 FROM papers p
		 LEFT JOIN analysis_reports ar ON ar.paper_id = p.id
		 WHERE LOWER(p.title) LIKE LOWER($1) OR LOWER(p.abstract) LIKE LOWER($1)
		 ORDER BY p.created_at DESC LIMIT $2`, pattern, topK+3)
	if err != nil {
		return "", nil, nil, err
	}
	defer rows.Close()
	type cand struct {
		id, title, abstract, summary, deep string
	}
	var cands []cand
	for rows.Next() {
		var c cand
		if rows.Scan(&c.id, &c.title, &c.abstract, &c.summary, &c.deep) == nil {
			cands = append(cands, c)
		}
	}
	if len(cands) == 0 {
		return "当前知识库没有足够上下文。", []string{}, []map[string]any{}, nil
	}
	if len(cands) > topK {
		cands = cands[:topK]
	}
	var ctxParts []string
	cited := []string{}
	evidence := []map[string]any{}
	for _, c := range cands {
		analysis := c.summary
		if len(analysis) > 1200 {
			analysis = analysis[:1200]
		}
		ctxParts = append(ctxParts, c.title+"\n"+truncateRunes(c.abstract, 500)+"\n"+analysis)
		snippet := truncateRunes(c.abstract, 260) + "\n" + truncateRunes(c.summary, 320)
		cited = append(cited, c.id)
		evidence = append(evidence, map[string]any{
			"paper_id": c.id, "title": c.title,
			"snippet": strings.TrimSpace(snippet), "source": "abstract+analysis",
		})
	}
	// build_rag_prompt 对齐
	var joined []string
	for i, p := range ctxParts {
		joined = append(joined, fmt.Sprintf("[ctx%d] %s", i+1, p))
	}
	prompt := "请基于上下文回答问题，输出严格 JSON：" +
		`{"answer":"...", "confidence":0.0}` + "\n" +
		fmt.Sprintf("问题: %s\n上下文:\n%s", question, strings.Join(joined, "\n\n"))
	parsed, res, err := s.gateway.CompleteJSON(ctx, "skim", prompt)
	if err != nil {
		return "", nil, nil, err
	}
	_ = res
	answer := strOf(parsed["answer"])
	if answer == "" {
		answer = "未能生成回答，请重试。"
	}
	return answer, cited, evidence, nil
}

func truncateRunes(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

// ---------- content（wiki / generated / brief / trends / today） ----------

// handleWikiPaper GET /wiki/paper/{paper_id} —— 论文 Wiki 生成（同步 LLM）+ 落库。
func (s *Server) handleWikiPaper(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	env := s.workerEnv()
	markdown, metadata, err := env.PaperWikiMarkdown(r.Context(), paperID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	var title string
	_ = s.db.QueryRow(`SELECT COALESCE(title,'') FROM papers WHERE id=$1`, paperID).Scan(&title)
	contentID := s.saveGeneratedContent("paper_wiki", "Paper Wiki: "+truncateRunes(title, 60), markdown, metadata)
	writeJSON(w, http.StatusOK, map[string]any{
		"paper_id": paperID, "title": title, "markdown": markdown,
		"content_id": contentID, "cached": false,
	})
}

// handleWikiTopic GET /wiki/topic —— 主题 Wiki 生成（同步 LLM）+ 落库。
func (s *Server) handleWikiTopic(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	if keyword == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "keyword is required"})
		return
	}
	limit := queryInt(r, "limit", 120)
	env := s.workerEnv()
	var topicID string
	_ = s.db.QueryRow(`SELECT id FROM topic_subscriptions WHERE name=$1`, keyword).Scan(&topicID)
	markdown, metadata, err := env.TopicWikiMarkdown(r.Context(), keyword, topicID, limit)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	contentID := s.saveGeneratedContent("topic_wiki", "Topic Wiki: "+keyword, markdown, metadata)
	writeJSON(w, http.StatusOK, map[string]any{
		"keyword": keyword, "markdown": markdown, "content_id": contentID,
	})
}

// saveGeneratedContent generated_contents 插入（幂等不做——HTTP 语义直插）。
func (s *Server) saveGeneratedContent(contentType, title, markdown string, metadata map[string]any) string {
	id := newUUID()
	if metadata == nil {
		metadata = map[string]any{}
	}
	metaJSON, _ := json.Marshal(metadata)
	_, err := s.db.Exec(
		`INSERT INTO generated_contents (id, content_type, title, markdown, metadata_json, created_at)
		 VALUES ($1, $2, $3, $4, $5, NOW())`,
		id, contentType, title, markdown, string(metaJSON))
	if err != nil {
		return ""
	}
	return id
}

// handleGeneratedList GET /generated/list?type=&limit=。
func (s *Server) handleGeneratedList(w http.ResponseWriter, r *http.Request) {
	contentType := r.URL.Query().Get("type")
	limit := queryInt(r, "limit", 50)
	query := `SELECT id, content_type, title, TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')
	          FROM generated_contents`
	args := []any{}
	if contentType != "" {
		query += ` WHERE content_type = $1`
		args = append(args, contentType)
	}
	query += fmt.Sprintf(` ORDER BY created_at DESC LIMIT $%d`, len(args)+1)
	args = append(args, limit)
	rows, err := s.db.Query(query, args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, ct, title, createdAt string
		if rows.Scan(&id, &ct, &title, &createdAt) == nil {
			items = append(items, map[string]any{
				"id": id, "content_type": ct, "title": title, "created_at": createdAt,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "total": len(items)})
}

// handleGeneratedDetail GET /generated/{content_id}。
func (s *Server) handleGeneratedDetail(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("content_id")
	var contentType, title, markdown string
	var metadata []byte
	var createdAt time.Time
	err := s.db.QueryRow(
		`SELECT content_type, COALESCE(title,''), COALESCE(markdown,''), COALESCE(metadata_json,'{}'::jsonb), created_at
		 FROM generated_contents WHERE id=$1`, id,
	).Scan(&contentType, &title, &markdown, &metadata, &createdAt)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Content not found"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	var meta map[string]any
	_ = json.Unmarshal(metadata, &meta)
	writeJSON(w, http.StatusOK, map[string]any{
		"id": id, "content_type": contentType, "title": title,
		"markdown": markdown, "metadata_json": meta,
		"created_at": createdAt.UTC().Format(time.RFC3339),
	})
}

// handleGeneratedDelete DELETE /generated/{content_id}。
func (s *Server) handleGeneratedDelete(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("content_id")
	res, err := s.db.Exec(`DELETE FROM generated_contents WHERE id=$1`, id)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Content not found"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"deleted": id})
}

// handleBriefDaily POST /brief/daily —— 提交每日简报任务。
func (s *Server) handleBriefDaily(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Recipient string `json:"recipient"`
	}
	_ = readBody(r, &body)
	jobID, taskID, err := s.submitCoreTask("daily_brief_publish", map[string]any{"recipient": body.Recipient}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleTrendsHot GET /trends/hot。
func (s *Server) handleTrendsHot(w http.ResponseWriter, r *http.Request) {
	days := queryInt(r, "days", 7)
	topK := queryInt(r, "top_k", 15)
	env := s.workerEnv()
	writeJSON(w, http.StatusOK, map[string]any{"items": env.HotKeywords(days, topK)})
}

// handleTrendsEmerging GET /trends/emerging —— 近期 vs 早期关键词对比。
func (s *Server) handleTrendsEmerging(w http.ResponseWriter, r *http.Request) {
	days := queryInt(r, "days", 14)
	if days < 7 {
		days = 7
	}
	half := days / 2
	now := time.Now().UTC()
	recentCutoff := now.AddDate(0, 0, -half).Format("2006-01-02 15:04:05.000000")
	oldCutoff := now.AddDate(0, 0, -days).Format("2006-01-02 15:04:05.000000")
	counts := func(since, until string) map[string]int {
		out := map[string]int{}
		rows, err := s.db.Query(
			`SELECT metadata FROM papers WHERE created_at >= $1 AND created_at < $2 LIMIT 500`, since, until)
		if err != nil {
			return out
		}
		defer rows.Close()
		for rows.Next() {
			var raw []byte
			if rows.Scan(&raw) != nil {
				continue
			}
			var m map[string]any
			if json.Unmarshal(raw, &m) != nil {
				continue
			}
			if kws, ok := m["keywords"].([]any); ok {
				for _, k := range kws {
					if kw := strings.ToLower(strOf(k)); kw != "" {
						out[kw]++
					}
				}
			}
		}
		return out
	}
	recent := counts(recentCutoff, now.Format("2006-01-02 15:04:05.000000"))
	older := counts(oldCutoff, recentCutoff)
	type trend struct {
		Keyword string `json:"keyword"`
		Recent  int    `json:"recent_count"`
		Old     int    `json:"previous_count"`
		Delta   int    `json:"delta"`
	}
	var rising, falling []trend
	for kw, rc := range recent {
		oc := older[kw]
		t := trend{kw, rc, oc, rc - oc}
		if t.Delta > 0 {
			rising = append(rising, t)
		}
	}
	for kw, oc := range older {
		rc := recent[kw]
		if rc == 0 {
			falling = append(falling, trend{kw, rc, oc, rc - oc})
		}
	}
	// 按 delta 排序取前 10
	sortTrends := func(ts []trend) {
		for i := 0; i < len(ts); i++ {
			for j := i + 1; j < len(ts); j++ {
				if absInt(ts[j].Delta) > absInt(ts[i].Delta) {
					ts[i], ts[j] = ts[j], ts[i]
				}
			}
		}
		if len(ts) > 10 {
			ts = ts[:10]
		}
	}
	sortTrends(rising)
	sortTrends(falling)
	writeJSON(w, http.StatusOK, map[string]any{"rising": rising, "falling": falling})
}

func absInt(v int) int {
	if v < 0 {
		return -v
	}
	return v
}

// handleToday GET /today —— 今日研究速览。
func (s *Server) handleToday(w http.ResponseWriter, r *http.Request) {
	env := s.workerEnv()
	sum := env.TodaySummary()
	recs := env.Recommendations(5)
	hot := env.HotKeywords(7, 8)
	writeJSON(w, http.StatusOK, map[string]any{
		"today_new": sum.TodayNew, "week_new": sum.WeekNew,
		"total_papers": sum.TotalPapers,
		"recommendations": recs, "hot_keywords": hot,
	})
}

// ---------- writing（LLM 经网关） ----------

var writingTemplates = []map[string]any{
	{"id": "literature_review", "name": "文献综述", "description": "按主题梳理相关工作的方法与结论"},
	{"id": "abstract", "name": "摘要润色", "description": "优化学术摘要的结构与表达"},
	{"id": "rebuttal", "name": "审稿回复", "description": "针对审稿意见组织逐条回复"},
	{"id": "email", "name": "学术邮件", "description": "导师/合作者沟通邮件草拟"},
}

// handleWritingTemplates GET /writing/templates。
func (s *Server) handleWritingTemplates(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"items": writingTemplates})
}

// handleWritingProcess POST /writing/process。
func (s *Server) handleWritingProcess(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Action  string `json:"action"`
		Content string `json:"content"`
		Topic   string `json:"topic"`
	}
	if err := readBody(r, &body); err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "invalid body"})
		return
	}
	text := strings.TrimSpace(body.Content)
	if text == "" {
		text = strings.TrimSpace(body.Topic)
	}
	if text == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "content 或 topic 不能为空"})
		return
	}
	result, err := s.gatewayChat(r.Context(), writingPromptFor(body.Action, text))
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"action": body.Action, "result": result})
}

func writingPromptFor(action, text string) string {
	return fmt.Sprintf("你是学术写作助手。请对以下文本执行「%s」操作，用中文输出结果，保持学术规范：\n\n%s", action, truncateRunes(text, 6000))
}

// handleWritingRefine POST /writing/refine —— 多轮消息润色。
func (s *Server) handleWritingRefine(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Messages []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
	}
	if err := readBody(r, &body); err != nil || len(body.Messages) == 0 {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "messages required"})
		return
	}
	var sb strings.Builder
	for _, m := range body.Messages {
		fmt.Fprintf(&sb, "[%s] %s\n", m.Role, m.Content)
	}
	result, err := s.gatewayChat(r.Context(), "你是学术写作助手。请基于以下对话继续润色/回复，用中文，保持学术规范：\n\n"+sb.String())
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"result": result})
}

// handleWritingProcessMultimodal POST /writing/process-multimodal。
func (s *Server) handleWritingProcessMultimodal(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Action      string `json:"action"`
		Content     string `json:"content"`
		ImageBase64 string `json:"image_base64"`
	}
	if err := readBody(r, &body); err != nil || body.ImageBase64 == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "image_base64 required"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 120*time.Second)
	defer cancel()
	res, err := s.gateway.ChatVision(ctx, "deep", writingPromptFor(body.Action, body.Content), body.ImageBase64, "image/png", 2048)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"action": body.Action, "result": res.Content})
}

// ---------- 共享小件 ----------

// gatewayChat 网关单轮补全（writing 等简单场景）。
func (s *Server) gatewayChat(ctx context.Context, prompt string) (string, error) {
	res, err := s.gateway.Chat(ctx, "deep", prompt, 2048)
	if err != nil {
		return "", err
	}
	return res.Content, nil
}

// readBody JSON body 读取。
func readBody(r *http.Request, v any) error {
	raw, err := io.ReadAll(io.LimitReader(r.Body, 32<<20))
	if err != nil {
		return err
	}
	if len(raw) == 0 {
		return nil
	}
	return json.Unmarshal(raw, v)
}

var uuidV4Re = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

// strOf any→string（JSON 解出字段）。
func strOf(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
