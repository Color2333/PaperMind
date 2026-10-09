// Phase 7 收尾：前端剩余 Python 依赖端点——similar/duplicates/reasoning/
// figures 服务、PDF 服务、search-multi、suggest-channels、daily 任务链提交。
// 全部 Go 原生，Python backend 退役前的最后移植面。
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"os"
	"strings"

	core "github.com/Color2333/PaperMind/core"
)

// ---------- 论文相似 / 重复 ----------

// handlePaperSimilar GET /papers/{paper_id}/similar —— embedding 余弦 top-K。
func (s *Server) handlePaperSimilar(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	topK := queryInt(r, "top_k", 5)
	var raw []byte
	if err := s.db.QueryRow(`SELECT embedding_vec FROM papers WHERE id=$1 AND embedding_vec IS NOT NULL`, paperID).Scan(&raw); err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"items": []any{}, "message": "该论文无向量，先运行 embed"})
		return
	}
	var vec []float64
	if json.Unmarshal(raw, &vec) != nil {
		writeJSON(w, http.StatusOK, map[string]any{"items": []any{}})
		return
	}
	rows, err := s.db.Query(
		`SELECT id, title, COALESCE(arxiv_id,''), embedding_vec FROM papers
		 WHERE id != $1 AND embedding_vec IS NOT NULL AND rejected = false LIMIT 800`, paperID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	type scored struct {
		id, title, arxivID string
		sim                float64
	}
	var cands []scored
	for rows.Next() {
		var c scored
		var vRaw []byte
		if rows.Scan(&c.id, &c.title, &c.arxivID, &vRaw) != nil {
			continue
		}
		var v []float64
		if json.Unmarshal(vRaw, &v) != nil {
			continue
		}
		c.sim = math.Round(cosineOf(vec, v)*1e4) / 1e4
		cands = append(cands, c)
	}
	for i := 0; i < len(cands); i++ {
		for j := i + 1; j < len(cands); j++ {
			if cands[j].sim > cands[i].sim {
				cands[i], cands[j] = cands[j], cands[i]
			}
		}
	}
	if len(cands) > topK {
		cands = cands[:topK]
	}
	items := []map[string]any{}
	for _, c := range cands {
		items = append(items, map[string]any{"id": c.id, "title": c.title, "arxiv_id": c.arxivID, "similarity": c.sim})
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "total": len(items)})
}

func cosineOf(a, b []float64) float64 {
	if len(a) == 0 || len(a) != len(b) {
		return 0
	}
	var dot, na, nb float64
	for i := range a {
		dot += a[i] * b[i]
		na += a[i] * a[i]
		nb += b[i] * b[i]
	}
	if na == 0 || nb == 0 {
		return 0
	}
	return dot / (math.Sqrt(na) * math.Sqrt(nb))
}

// handlePaperDuplicates GET /papers/{paper_id}/duplicates —— 相似度 > 0.92 疑似重复。
func (s *Server) handlePaperDuplicates(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	var raw []byte
	if err := s.db.QueryRow(`SELECT embedding_vec FROM papers WHERE id=$1 AND embedding_vec IS NOT NULL`, paperID).Scan(&raw); err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"duplicates": []any{}, "count": 0, "note": "无 embedding，无法检测"})
		return
	}
	var vec []float64
	if json.Unmarshal(raw, &vec) != nil {
		writeJSON(w, http.StatusOK, map[string]any{"duplicates": []any{}, "count": 0})
		return
	}
	rows, err := s.db.Query(
		`SELECT id, title, COALESCE(arxiv_id,''), embedding_vec FROM papers
		 WHERE id != $1 AND embedding_vec IS NOT NULL LIMIT 800`, paperID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	dups := []map[string]any{}
	for rows.Next() {
		var id, title, arxivID string
		var vRaw []byte
		if rows.Scan(&id, &title, &arxivID, &vRaw) != nil {
			continue
		}
		var v []float64
		if json.Unmarshal(vRaw, &v) != nil {
			continue
		}
		sim := cosineOf(vec, v)
		if sim >= 0.92 {
			dups = append(dups, map[string]any{
				"id": id, "title": title, "arxiv_id": arxivID,
				"similarity": math.Round(sim*1e4) / 1e4,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"duplicates": dups, "count": len(dups)})
}

// ---------- 图表服务（image_analyses + 文件） ----------

// handlePaperFigures GET /papers/{paper_id}/figures。
func (s *Server) handlePaperFigures(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	rows, err := s.db.Query(
		`SELECT id, page_number, image_index, COALESCE(image_type,'figure'), COALESCE(caption,''),
		        COALESCE(description,''), COALESCE(image_path,'')
		 FROM image_analyses WHERE paper_id=$1 ORDER BY page_number, image_index`, paperID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, imgType, caption, description, imagePath string
		var page, idx int
		if rows.Scan(&id, &page, &idx, &imgType, &caption, &description, &imagePath) == nil {
			var imageURL any
			if imagePath != "" {
				if _, err := os.Stat(imagePath); err == nil {
					imageURL = fmt.Sprintf("/papers/%s/figures/%s/image", paperID, id)
				}
			}
			items = append(items, map[string]any{
				"id": id, "page_number": page, "image_index": idx,
				"image_type": imgType, "caption": caption,
				"description": description, "has_image": imageURL != nil,
				"image_url": imageURL,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "total": len(items)})
}

// handleAnalyzeFiguresTask POST /papers/{paper_id}/figures/analyze —— 提交分析任务。
func (s *Server) handleAnalyzeFiguresTask(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	var body struct {
		MaxFigures int `json:"max_figures"`
	}
	_ = readBody(r, &body)
	if body.MaxFigures <= 0 {
		body.MaxFigures = 12
	}
	jobID, taskID, err := s.submitCoreTask("analyze_figures", map[string]any{
		"paper_id": paperID, "max_figures": body.MaxFigures,
	}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// ---------- reasoning / PDF 服务 ----------

// handlePaperReasoning POST /papers/{paper_id}/reasoning —— LLM 推理链。
func (s *Server) handlePaperReasoning(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	var body struct {
		Question string `json:"question"`
	}
	if err := readBody(r, &body); err != nil || strings.TrimSpace(body.Question) == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "question required"})
		return
	}
	var title, abstract, deep string
	err := s.db.QueryRow(
		`SELECT p.title, COALESCE(p.abstract,''), COALESCE(ar.deep_dive_md,'')
		 FROM papers p LEFT JOIN analysis_reports ar ON ar.paper_id = p.id
		 WHERE p.id=$1`, paperID).Scan(&title, &abstract, &deep)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "论文不存在"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	prompt := fmt.Sprintf("你是研究推理助手。请针对用户问题，基于论文内容进行结构化推理（中文，Markdown）：\n\n论文: %s\n摘要: %s\n精读: %s\n\n问题: %s",
		title, truncateRunes(abstract, 800), truncateRunes(deep, 2000), body.Question)
	result, err := s.gatewayChat(r.Context(), prompt)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"paper_id": paperID, "question": body.Question, "reasoning": result})
}

// handlePaperPDF GET /papers/{paper_id}/pdf —— 论文 PDF 文件服务。
func (s *Server) handlePaperPDF(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	pdfPath := s.paperPDFPath(paperID)
	if pdfPath == "" {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "论文没有 PDF"})
		return
	}
	if _, err := os.Stat(pdfPath); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "PDF 文件不存在"})
		return
	}
	w.Header().Set("Content-Type", "application/pdf")
	http.ServeFile(w, r, pdfPath)
}

// handleDownloadPaperPDF POST /papers/{paper_id}/download-pdf —— 提交下载任务。
func (s *Server) handleDownloadPaperPDF(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	var arxivID string
	if err := s.db.QueryRow(`SELECT COALESCE(arxiv_id,'') FROM papers WHERE id=$1`, paperID).Scan(&arxivID); err != nil || arxivID == "" {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "论文不存在或无 arXiv ID"})
		return
	}
	jobID, taskID, err := s.submitCoreTask("download_source", map[string]any{"arxiv_id": arxivID}, 300)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleRecommendedGo GET /papers/recommended —— 多兴趣推荐（已读质心×未读余弦）。
func (s *Server) handleRecommendedGo(w http.ResponseWriter, r *http.Request) {
	topK := queryInt(r, "top_k", 10)
	env := s.workerEnv()
	items := env.Recommendations(topK)
	if items == nil {
		items = []core.RecommendationItem{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "total": len(items)})
}

// ---------- search-multi / suggest-channels ----------

// handleSearchMulti POST /papers/search-multi —— arXiv + S2 聚合（IEEE/OpenAlex
// 无 key 时自动跳过，与 Python 渠道降级语义一致）。
func (s *Server) handleSearchMulti(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Query      string `json:"query"`
		MaxResults int    `json:"max_results"`
		Channels   []string `json:"channels"`
	}
	if err := readBody(r, &body); err != nil || strings.TrimSpace(body.Query) == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "query required"})
		return
	}
	if body.MaxResults <= 0 {
		body.MaxResults = 10
	}
	ctx := r.Context()
	env := s.workerEnv()
	channels := map[string]any{}
	// arxiv
	if channelEnabled(body.Channels, "arxiv") {
		if papers, err := env.Arxiv.FetchLatest(ctx, body.Query, body.MaxResults, 0, 0, "relevance"); err == nil {
			items := make([]map[string]any, len(papers))
			for i, p := range papers {
				items[i] = map[string]any{
					"arxiv_id": p.ArxivID, "title": p.Title, "abstract": p.Abstract,
					"publication_date": p.PublicationDate, "metadata": p.Metadata,
				}
			}
			channels["arxiv"] = items
		} else {
			channels["arxiv"] = map[string]any{"error": err.Error()}
		}
	}
	// semantic_scholar（标题检索）
	if channelEnabled(body.Channels, "semantic_scholar") {
		channels["semantic_scholar"] = s.searchS2(ctx, body.Query, body.MaxResults)
	}
	writeJSON(w, http.StatusOK, map[string]any{"query": body.Query, "channels": channels})
}

func channelEnabled(channels []string, name string) bool {
	if len(channels) == 0 {
		return true
	}
	for _, c := range channels {
		if c == name {
			return true
		}
	}
	return false
}

// searchS2 S2 标题检索（graph/v1/paper/search，含退避）。
func (s *Server) searchS2(ctx contextInterface, query string, limit int) any {
	env := s.workerEnv()
	items, err := env.Scholar.SearchPapers(ctx, query, limit)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	if items == nil {
		items = []map[string]any{}
	}
	return items
}

// contextInterface context.Context 别名（可读性）。
type contextInterface = context.Context

// handleSuggestChannels GET /papers/suggest-channels —— LLM 关键词建议。
func (s *Server) handleSuggestChannels(w http.ResponseWriter, r *http.Request) {
	description := r.URL.Query().Get("description")
	if strings.TrimSpace(description) == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "description required"})
		return
	}
	prompt := fmt.Sprintf("请为以下研究方向描述生成 5-8 个英文学术检索关键词（arXiv 检索用），输出严格 JSON：{\"suggestions\":[\"keyword1\",\"keyword2\"]}\n\n研究方向: %s", description)
	parsed, _, err := s.GW().CompleteJSON(r.Context(), "skim", prompt)
	if err != nil || parsed == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "LLM 生成失败"})
		return
	}
	suggestions := []string{}
	if list, ok := parsed["suggestions"].([]any); ok {
		for _, x := range list {
			if v := strOf(x); v != "" {
				suggestions = append(suggestions, v)
			}
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"suggestions": suggestions})
}

// ---------- daily 任务链提交（原 Python commands/daily） ----------

// handleDailyRunOnce POST /jobs/daily/run-once。
func (s *Server) handleDailyRunOnce(w http.ResponseWriter, r *http.Request) {
	jobID, taskID, err := s.submitCoreTask("daily_ingest_and_brief", map[string]any{}, 3600)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleWeeklyRunOnce POST /jobs/graph/weekly-run-once。
func (s *Server) handleWeeklyRunOnce(w http.ResponseWriter, r *http.Request) {
	jobID, taskID, err := s.submitCoreTask("weekly_graph_maintenance", map[string]any{}, 3600)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleBatchProcessUnread POST /jobs/batch-process-unread。
func (s *Server) handleBatchProcessUnreadTask(w http.ResponseWriter, r *http.Request) {
	maxPapers := queryInt(r, "max_papers", 50)
	jobID, taskID, err := s.submitCoreTask("batch_process_unread", map[string]any{"max_papers": maxPapers}, 5400)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleDailyReportRunOnce POST /jobs/daily-report/run-once。
func (s *Server) handleDailyReportRunOnce(w http.ResponseWriter, r *http.Request) {
	jobID, taskID, err := s.submitCoreTask("daily_report_workflow", map[string]any{}, 5400)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleDailyReportSendOnly POST /jobs/daily-report/send-only。
func (s *Server) handleDailyReportSendOnly(w http.ResponseWriter, r *http.Request) {
	recipient := r.URL.Query().Get("recipient")
	jobID, taskID, err := s.submitCoreTask("daily_report_send_only", map[string]any{"recipient": recipient}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleDailyReportGenerateOnly POST /jobs/daily-report/generate-only。
func (s *Server) handleDailyReportGenerateOnly(w http.ResponseWriter, r *http.Request) {
	jobID, taskID, err := s.submitCoreTask("daily_brief_publish", map[string]any{}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}
