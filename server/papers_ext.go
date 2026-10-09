package main

// papers_ext.go：Phase 1 剩余 papers 端点。
// LLM 调用走 Pi 网关（sidecar）；PyMuPDF 依赖端点暂经 Python 反代（Phase 3 移植）。

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// handleRecommended：GET /papers/recommended —— 反代 Python（LLM 推荐）。
func (s *Server) handleRecommended(w http.ResponseWriter, r *http.Request) {
	s.proxyLegacy(w, r)
}

// handleSearchMulti：POST /papers/search-multi —— 多渠道并行搜索。
// Phase 1 v0：反代 Python（渠道聚合器涉及 5 个 HTTP client 移植，Phase 3 收编）。
func (s *Server) handleSearchMulti(w http.ResponseWriter, r *http.Request) {
	s.proxyLegacy(w, r)
}

// handleSuggestChannels：GET /papers/suggest-channels —— 反代 Python。
func (s *Server) handleSuggestChannels(w http.ResponseWriter, r *http.Request) {
	s.proxyLegacy(w, r)
}

// handleProxyArxivPDF：GET /papers/proxy-arxiv-pdf/{arxiv_id} —— Go 原生 HTTP 代理。
func (s *Server) handleProxyArxivPDF(w http.ResponseWriter, r *http.Request) {
	arxivID := r.PathValue("arxiv_id")
	cleanID := arxivID
	if idx := strings.Index(cleanID, "v"); idx > 0 {
		cleanID = cleanID[:idx]
	}
	arxivURL := fmt.Sprintf("https://arxiv.org/pdf/%s.pdf", cleanID)

	httpClient := &http.Client{Timeout: 30 * time.Second}
	resp, err := httpClient.Get(arxivURL)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": fmt.Sprintf("arXiv 访问失败: %v", err)})
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": fmt.Sprintf("arXiv 论文不存在: %s", cleanID)})
		return
	}
	if resp.StatusCode != http.StatusOK {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": fmt.Sprintf("arXiv 访问失败: %d", resp.StatusCode)})
		return
	}

	w.Header().Set("Content-Type", "application/pdf")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Content-Disposition", fmt.Sprintf("inline; filename=%q", cleanID+".pdf"))
	w.Header().Set("Cache-Control", "public, max-age=3600")
	w.WriteHeader(http.StatusOK)
	_, _ = io.Copy(w, resp.Body)
}

// handleServePDF：GET /papers/{id}/pdf —— 从共享卷读取 PDF 文件流。
func (s *Server) handleServePDF(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	var pdfPath *string
	if err := s.db.QueryRow("SELECT pdf_path FROM papers WHERE id=$1", paperID).Scan(&pdfPath); err != nil || pdfPath == nil || *pdfPath == "" {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "论文没有 PDF 文件"})
		return
	}
	http.ServeFile(w, r, *pdfPath)
}

// handleDownloadPDF：POST /papers/{id}/download-pdf —— 触发 arXiv 下载（反代 Python 命令）。
func (s *Server) handleDownloadPDF(w http.ResponseWriter, r *http.Request) {
	s.proxyLegacy(w, r)
}

// handleSegments：GET /papers/{id}/segments —— 反代 Python（PyMuPDF 依赖）。
func (s *Server) handleSegments(w http.ResponseWriter, r *http.Request) {
	s.proxyLegacy(w, r)
}

// handleAIExplain：POST /papers/{id}/ai/explain —— 调 Pi 网关 LLM。
func (s *Server) handleAIExplain(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	var body struct {
		Text   string `json:"text"`
		Action string `json:"action"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "bad json"})
		return
	}
	body.Text = strings.TrimSpace(body.Text)
	if body.Text == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "text is required"})
		return
	}

	prompts := map[string]string{
		"explain":   fmt.Sprintf("你是学术论文解读专家。请用中文简洁解释以下学术文本的含义，包括专业术语解释和核心意思。如果是公式，解释公式的含义和各变量。\n\n文本：%s", truncStr(body.Text, 2000)),
		"translate": fmt.Sprintf("请将以下学术文本翻译为流畅的中文，保留专业术语的英文原文（括号标注）。\n\n文本：%s", truncStr(body.Text, 2000)),
		"summarize": fmt.Sprintf("请用中文简要总结以下内容的核心观点（3-5 句话）：\n\n%s", truncStr(body.Text, 3000)),
	}
	prompt, ok := prompts[body.Action]
	if !ok {
		prompt = prompts["explain"]
	}

	// 调 Pi 网关 LLM
	gwURL := envOr("GATEWAY_URL", "http://gateway:8080") + "/v1/chat/completions"
	gwTok := envOr("PAPERMIND_GATEWAY_TOKEN", "pm-gateway-internal")
	payload := map[string]any{
		"model":    "skim",
		"messages": []map[string]string{{"role": "user", "content": prompt}},
	}
	payloadBytes, _ := json.Marshal(payload)
	req, _ := http.NewRequestWithContext(r.Context(), "POST", gwURL, strings.NewReader(string(payloadBytes)))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+gwTok)

	httpClient := &http.Client{Timeout: 60 * time.Second}
	resp, err := httpClient.Do(req)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": fmt.Sprintf("网关调用失败: %v", err)})
		return
	}
	defer resp.Body.Close()
	var gwResp struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err = json.NewDecoder(resp.Body).Decode(&gwResp); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	result := ""
	if len(gwResp.Choices) > 0 {
		result = gwResp.Choices[0].Message.Content
	}
	// trace（成本记录经 Python 侧 prompt_traces）
	_, _ = s.db.Exec(
		`INSERT INTO prompt_traces (id, paper_id, stage, provider, model, prompt_digest, input_tokens, output_tokens, total_tokens, created_at)
		 VALUES (gen_random_uuid()::text, $1, 'pdf_reader_ai', 'gateway', 'skim', $2, 0, 0, 0, now()::timestamp)`,
		paperID, fmt.Sprintf("%s:%s", body.Action, truncStr(body.Text, 80)),
	)
	writeJSON(w, http.StatusOK, map[string]any{"action": body.Action, "result": result})
}

// handleFigures：GET /papers/{id}/figures。
func (s *Server) handleFigures(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	rows, err := s.db.Query(
		`SELECT id, image_index, COALESCE(image_type,''), COALESCE(caption,''),
			COALESCE(description,''), image_path IS NOT NULL
		 FROM image_analyses WHERE paper_id=$1 ORDER BY image_index`, paperID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, imageType, caption, description string
		var imageIndex int
		var hasImage bool
		if err := rows.Scan(&id, &imageIndex, &imageType, &caption, &description, &hasImage); err != nil {
			continue
		}
		item := map[string]any{
			"id": id, "image_index": imageIndex, "image_type": imageType,
			"caption": caption, "description": description, "has_image": hasImage,
			"image_url": (*string)(nil),
		}
		if hasImage {
			item["image_url"] = fmt.Sprintf("/papers/%s/figures/%s/image", paperID, id)
		}
		items = append(items, item)
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

// handleFigureImage：GET /papers/{id}/figures/{fid}/image —— 文件流。
func (s *Server) handleFigureImage(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	figureID := r.PathValue("figure_id")
	var imgPath *string
	if err := s.db.QueryRow(
		"SELECT image_path FROM image_analyses WHERE id=$1 AND paper_id=$2",
		figureID, paperID,
	).Scan(&imgPath); err != nil || imgPath == nil || *imgPath == "" {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "图片不存在"})
		return
	}
	http.ServeFile(w, r, *imgPath)
}

// handleAnalyzeFigures：POST /papers/{id}/figures/analyze —— 提交任务到 Go Core。
func (s *Server) handleAnalyzeFigures(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	maxFigures := atoiOr(r.URL.Query().Get("max_figures"), 10)
	if maxFigures < 1 || maxFigures > 30 {
		maxFigures = 10
	}
	jobID, taskID, err := s.submitCoreTask("analyze_figures", map[string]any{
		"paper_id": paperID, "max_figures": maxFigures,
	}, 600)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID, "task_id": taskID})
}

// handleSimilar：GET /papers/{id}/similar —— 反代 Python（embedding 相似度）。
func (s *Server) handleSimilar(w http.ResponseWriter, r *http.Request) {
	s.proxyLegacy(w, r)
}

// handleDuplicates：GET /papers/{id}/duplicates —— 反代 Python。
func (s *Server) handleDuplicates(w http.ResponseWriter, r *http.Request) {
	s.proxyLegacy(w, r)
}

// handleReasoning：POST /papers/{id}/reasoning —— 反代 Python。
func (s *Server) handleReasoning(w http.ResponseWriter, r *http.Request) {
	s.proxyLegacy(w, r)
}

// handleIngestIEEE：POST /papers/ingest/ieee —— 提交 ingest_ieee 任务到 Go Core。
func (s *Server) handleIngestIEEE(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query().Get("query")
	if query == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "query required"})
		return
	}
	maxResults := atoiOr(r.URL.Query().Get("max_results"), 20)
	topicID := r.URL.Query().Get("topic_id")
	inputRef := map[string]any{
		"query": query, "max_results": maxResults, "action_type": "manual_collect",
	}
	if topicID != "" {
		inputRef["topic_id"] = topicID
	}
	jobID, taskID, err := s.submitCoreTask("ingest_ieee", inputRef, 600)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID})
}

// submitCoreTask：向 Go Core 提交任务（直连 PG，不经 HTTP）。
func (s *Server) submitCoreTask(capability string, inputRef map[string]any, timeoutS int) (jobID, taskID string, err error) {
	inputJSON, _ := json.Marshal(inputRef)
	err = s.db.QueryRow(
		`INSERT INTO core_jobs (id, kind, capability, payload, idempotency_key, status, created_at)
		 VALUES (gen_random_uuid()::text, $1, $2, '{}', NULL, 'queued', now()::timestamp)
		 RETURNING id`,
		"CoreTask", capability,
	).Scan(&jobID)
	if err != nil {
		return "", "", err
	}
	err = s.db.QueryRow(
		`INSERT INTO core_tasks (id, job_id, capability, input_ref, status, attempt_count, max_attempts, timeout_s, seq, created_at)
		 VALUES (gen_random_uuid()::text, $1, $2, $3, 'queued', 0, 2, $4, 0, now()::timestamp)
		 RETURNING id`,
		jobID, capability, string(inputJSON), timeoutS,
	).Scan(&taskID)
	return jobID, taskID, err
}

func truncStr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
