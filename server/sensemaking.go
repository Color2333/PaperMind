// Phase 6（上）：translate 5 + sensemaking 13 端点。
// 翻译经网关 LLM；sensemaking = 认知重构三幕（LLM 生成 + 会话持久化）。
package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	core "github.com/Color2333/PaperMind/core"
)

// ---------- translate ----------

// gatewayTranslate 单段翻译（Python translate_text 语义对齐）。
func (s *Server) gatewayTranslate(r *http.Request, text, targetLang string) (string, error) {
	prompt := fmt.Sprintf("Translate the following academic text to %s.\nMaintain the academic tone and technical terminology.\n\nText:\n%s\n\nTranslation:", targetLang, text)
	return s.gatewayChat(r.Context(), prompt)
}

// handleTranslateSelection POST /translate/selection —— 划词翻译（无状态）。
func (s *Server) handleTranslateSelection(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Text       string `json:"text"`
		TargetLang string `json:"target_lang"`
	}
	if err := readBody(r, &body); err != nil || strings.TrimSpace(body.Text) == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "text required"})
		return
	}
	if body.TargetLang == "" {
		body.TargetLang = "zh"
	}
	translation, err := s.gatewayTranslate(r, body.Text, body.TargetLang)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"original": body.Text, "translation": strings.TrimSpace(translation)})
}

// handleTranslateSegments POST /translate/segments —— 段落实时翻译（并发 5）。
func (s *Server) handleTranslateSegments(w http.ResponseWriter, r *http.Request) {
	targetLang := r.URL.Query().Get("target_lang")
	if targetLang == "" {
		targetLang = "zh"
	}
	var segments []struct {
		ID      string `json:"id"`
		Type    string `json:"type"`
		Content string `json:"content"`
	}
	if err := readBody(r, &segments); err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "invalid segments"})
		return
	}
	results := make([]map[string]any, len(segments))
	sem := make(chan struct{}, 5)
	var wg sync.WaitGroup
	for i, seg := range segments {
		wg.Add(1)
		results[i] = map[string]any{"id": seg.ID, "type": seg.Type, "content": seg.Content}
		go func(i int, content, segType string) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			if segType != "paragraph" {
				results[i]["translation"] = content
				return
			}
			t, err := s.gatewayTranslate(r, content, targetLang)
			if err != nil {
				return
			}
			results[i]["translation"] = strings.TrimSpace(t)
		}(i, seg.Content, seg.Type)
	}
	wg.Wait()
	writeJSON(w, http.StatusOK, map[string]any{"segments": results})
}

// handleBilingualPDFStart POST /translate/bilingual-pdf —— 提交翻译任务（layout 降级 fast）。
func (s *Server) handleBilingualPDFStart(w http.ResponseWriter, r *http.Request) {
	var body struct {
		PaperID    string `json:"paper_id"`
		TargetLang string `json:"target_lang"`
		Mode       string `json:"mode"`
	}
	if err := readBody(r, &body); err != nil || body.PaperID == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "paper_id required"})
		return
	}
	if body.TargetLang == "" {
		body.TargetLang = "zh"
	}
	if body.Mode == "" {
		body.Mode = "fast"
	}
	jobID, taskID, err := s.submitCoreTask("translate_bilingual_pdf", map[string]any{
		"paper_id": body.PaperID, "target_lang": body.TargetLang, "mode": body.Mode,
	}, 900)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleBilingualPDFCache GET /translate/bilingual-pdf/{paper_id} —— 翻译缓存查询。
func (s *Server) handleBilingualPDFCache(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	targetLang := r.URL.Query().Get("target_lang")
	if targetLang == "" {
		targetLang = "zh"
	}
	mode := r.URL.Query().Get("mode")
	if mode == "" {
		mode = "fast"
	}
	var segments []byte
	var pdfPath sql.NullString
	err := s.db.QueryRow(
		`SELECT COALESCE(segments::text,''), COALESCE(bilingual_pdf_path,'')
		 FROM paper_translations WHERE paper_id=$1 AND target_lang=$2 AND mode=$3`,
		paperID, targetLang, mode).Scan(&segments, &pdfPath)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusOK, map[string]any{"cached": false})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if mode == "fast" {
		var segs []any
		_ = json.Unmarshal(segments, &segs)
		writeJSON(w, http.StatusOK, map[string]any{"cached": true, "segments": segs})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"cached": true,
		"pdf_url": fmt.Sprintf("/translate/bilingual-pdf/%s/file?target_lang=%s&mode=layout",
			paperID, targetLang),
	})
}

// handleBilingualPDFFile GET /translate/bilingual-pdf/{paper_id}/file —— 双语 PDF 下载。
func (s *Server) handleBilingualPDFFile(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	targetLang := r.URL.Query().Get("target_lang")
	if targetLang == "" {
		targetLang = "zh"
	}
	var pdfPath sql.NullString
	err := s.db.QueryRow(
		`SELECT bilingual_pdf_path FROM paper_translations
		 WHERE paper_id=$1 AND target_lang=$2 AND mode='layout'`,
		paperID, targetLang).Scan(&pdfPath)
	if err != nil || !pdfPath.Valid || pdfPath.String == "" {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "翻译文件不存在"})
		return
	}
	w.Header().Set("Content-Type", "application/pdf")
	w.Header().Set("Content-Disposition", fmt.Sprintf("inline; filename=\"%s_%s.pdf\"", paperID, targetLang))
	http.ServeFile(w, r, pdfPath.String)
}

// ---------- sensemaking ----------

// sensemakingSchemaDict user_schemas 行 → dict（Python _schema_dict 对齐）。
func sensemakingSchemaDict(id, userID, name string, researchTopics, challenges, beliefs, gaps []byte, academicLevel sql.NullString, version int) map[string]any {
	toList := func(raw []byte) []any {
		var out []any
		_ = json.Unmarshal(raw, &out)
		return out
	}
	return map[string]any{
		"id": id, "user_id": userID, "name": name,
		"research_topics": toList(researchTopics),
		"academic_level":  nullStr(academicLevel),
		"current_challenges": toList(challenges),
		"beliefs":         toList(beliefs),
		"knowledge_gaps":  toList(gaps),
		"version":         version,
	}
}

// handleCreateSchema POST /sensemaking/schemas。
func (s *Server) handleCreateSchema(w http.ResponseWriter, r *http.Request) {
	var body struct {
		UserID            string   `json:"user_id"`
		Name              string   `json:"name"`
		ResearchTopics    []string `json:"research_topics"`
		AcademicLevel     string   `json:"academic_level"`
		CurrentChallenges []string `json:"current_challenges"`
		Beliefs           []string `json:"beliefs"`
		KnowledgeGaps     []string `json:"knowledge_gaps"`
	}
	if err := readBody(r, &body); err != nil || body.Name == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "name required"})
		return
	}
	if body.UserID == "" {
		body.UserID = "default"
	}
	id := newUUID()
	topics, _ := json.Marshal(orSlice(body.ResearchTopics))
	challenges, _ := json.Marshal(orSlice(body.CurrentChallenges))
	beliefs, _ := json.Marshal(orSlice(body.Beliefs))
	gaps, _ := json.Marshal(orSlice(body.KnowledgeGaps))
	_, err := s.db.Exec(
		`INSERT INTO user_schemas (id, user_id, name, research_topics, academic_level, current_challenges, beliefs, knowledge_gaps, version, created_at, updated_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 1, NOW(), NOW())`,
		id, body.UserID, body.Name, string(topics), nullIfEmptyStr(body.AcademicLevel),
		string(challenges), string(beliefs), string(gaps))
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id": id, "user_id": body.UserID, "name": body.Name,
		"research_topics": orSlice(body.ResearchTopics),
		"academic_level":  nullIfEmptyStr(body.AcademicLevel),
		"current_challenges": orSlice(body.CurrentChallenges),
		"beliefs":         orSlice(body.Beliefs),
		"knowledge_gaps":  orSlice(body.KnowledgeGaps),
		"version":         1,
	})
}

func orSlice(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

// handleGetSchema GET /sensemaking/schemas/{schema_id}。
func (s *Server) handleGetSchema(w http.ResponseWriter, r *http.Request) {
	var id, userID, name string
	var topics, challenges, beliefs, gaps []byte
	var level sql.NullString
	var version int
	err := s.db.QueryRow(
		`SELECT id, user_id, name, research_topics, academic_level, current_challenges, beliefs, knowledge_gaps, version
		 FROM user_schemas WHERE id=$1`, r.PathValue("schema_id"),
	).Scan(&id, &userID, &name, &topics, &level, &challenges, &beliefs, &gaps, &version)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Schema not found"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, sensemakingSchemaDict(id, userID, name, topics, challenges, beliefs, gaps, level, version))
}

// handleListSchemas GET /sensemaking/schemas?user_id=。
func (s *Server) handleListSchemas(w http.ResponseWriter, r *http.Request) {
	userID := r.URL.Query().Get("user_id")
	query := `SELECT id, user_id, name, research_topics, academic_level, current_challenges, beliefs, knowledge_gaps, version FROM user_schemas`
	args := []any{}
	if userID != "" {
		query += ` WHERE user_id=$1`
		args = append(args, userID)
	}
	rows, err := s.db.Query(query, args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, uID, name string
		var topics, challenges, beliefs, gaps []byte
		var level sql.NullString
		var version int
		if rows.Scan(&id, &uID, &name, &topics, &level, &challenges, &beliefs, &gaps, &version) == nil {
			items = append(items, sensemakingSchemaDict(id, uID, name, topics, challenges, beliefs, gaps, level, version))
		}
	}
	writeJSON(w, http.StatusOK, items)
}

// sensemakingSessionDict 会话行 → dict（Python _session_dict 对齐）。
func sensemakingSessionDict(id, paperID, schemaID string, act1, act2, act3 []byte, status string, history []byte, createdAt, updatedAt string, completedAt sql.NullString) map[string]any {
	toObj := func(raw []byte) any {
		var out any
		_ = json.Unmarshal(raw, &out)
		return out
	}
	out := map[string]any{
		"id": id, "paper_id": paperID, "user_schema_id": schemaID,
		"act1_comprehension": toObj(act1), "act2_collision": toObj(act2),
		"act3_reconstruction": toObj(act3), "status": status,
		"conversation_history": toObj(history),
		"created_at": createdAt, "updated_at": updatedAt,
		"completed_at": nullStr(completedAt),
	}
	return out
}

const sessionCols = `id, paper_id, user_schema_id, COALESCE(act1_comprehension::text,'null'), COALESCE(act2_collision::text,'null'), COALESCE(act3_reconstruction::text,'null'), status, COALESCE(conversation_history::text,'[]'), TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"'), TO_CHAR(updated_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"'), TO_CHAR(completed_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')`

func scanSession(row *sql.Row) (map[string]any, error) {
	var id, paperID, schemaID, status, createdAt, updatedAt string
	var act1, act2, act3, history []byte
	var completed sql.NullString
	err := row.Scan(&id, &paperID, &schemaID, &act1, &act2, &act3, &status, &history, &createdAt, &updatedAt, &completed)
	if err != nil {
		return nil, err
	}
	return sensemakingSessionDict(id, paperID, schemaID, act1, act2, act3, status, history, createdAt, updatedAt, completed), nil
}

// handleCreateSenseSession POST /sensemaking/sessions。
func (s *Server) handleCreateSenseSession(w http.ResponseWriter, r *http.Request) {
	var body struct {
		PaperID      string `json:"paper_id"`
		UserSchemaID string `json:"user_schema_id"`
	}
	if err := readBody(r, &body); err != nil || body.PaperID == "" || body.UserSchemaID == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "paper_id/user_schema_id required"})
		return
	}
	var exists string
	if err := s.db.QueryRow(`SELECT id FROM user_schemas WHERE id=$1`, body.UserSchemaID).Scan(&exists); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "UserSchema not found"})
		return
	}
	id := newUUID()
	_, err := s.db.Exec(
		`INSERT INTO sensemaking_sessions (id, paper_id, user_schema_id, status, conversation_history, created_at, updated_at)
		 VALUES ($1, $2, $3, 'in_progress', '[]', NOW(), NOW())`,
		id, body.PaperID, body.UserSchemaID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id": id, "paper_id": body.PaperID, "user_schema_id": body.UserSchemaID,
		"status": "in_progress", "conversation_history": []any{},
	})
}

// handleGetSenseSession GET /sensemaking/sessions/{session_id}。
func (s *Server) handleGetSenseSession(w http.ResponseWriter, r *http.Request) {
	row := s.db.QueryRow(`SELECT `+sessionCols+` FROM sensemaking_sessions WHERE id=$1`, r.PathValue("session_id"))
	out, err := scanSession(row)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Session not found"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// handleListSenseSessions GET /sensemaking/sessions?paper_id=&user_schema_id=。
func (s *Server) handleListSenseSessions(w http.ResponseWriter, r *http.Request) {
	paperID := r.URL.Query().Get("paper_id")
	schemaID := r.URL.Query().Get("user_schema_id")
	query := `SELECT ` + sessionCols + ` FROM sensemaking_sessions`
	args := []any{}
	if paperID != "" {
		query += fmt.Sprintf(` WHERE paper_id=$%d`, len(args)+1)
		args = append(args, paperID)
	}
	if schemaID != "" {
		if len(args) > 0 {
			query += ` AND`
		} else {
			query += ` WHERE`
		}
		query += fmt.Sprintf(` user_schema_id=$%d`, len(args)+1)
		args = append(args, schemaID)
	}
	query += ` ORDER BY created_at DESC`
	rows, err := s.db.Query(query, args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, pID, sID, status, createdAt, updatedAt string
		var act1, act2, act3, history []byte
		var completed sql.NullString
		if rows.Scan(&id, &pID, &sID, &act1, &act2, &act3, &status, &history, &createdAt, &updatedAt, &completed) == nil {
			items = append(items, sensemakingSessionDict(id, pID, sID, act1, act2, act3, status, history, createdAt, updatedAt, completed))
		}
	}
	writeJSON(w, http.StatusOK, items)
}

// makeActHandler 显式绑定 act 字面路由（PathValue 无通配）。
func (s *Server) makeActHandler(act string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.updateAct(w, r, act)
	}
}

// makeActGenerateHandler act 生成路由绑定。
func (s *Server) makeActGenerateHandler(act string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.generateAct(w, r, act)
	}
}

// handleUpdateAct PATCH /sensemaking/sessions/{session_id}/act{1|2|3}。
func (s *Server) handleUpdateAct(w http.ResponseWriter, r *http.Request) {
	act := r.PathValue("act")
	s.updateAct(w, r, act)
}

func (s *Server) updateAct(w http.ResponseWriter, r *http.Request, act string) {
	sessionID := r.PathValue("session_id")
	var data map[string]any
	if err := readBody(r, &data); err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "invalid body"})
		return
	}
	dataJSON, _ := json.Marshal(data)
	var res sql.Result
	var err error
	switch act {
	case "act1":
		res, err = s.db.Exec(`UPDATE sensemaking_sessions SET act1_comprehension=$1::jsonb, updated_at=NOW() WHERE id=$2`, string(dataJSON), sessionID)
	case "act2":
		res, err = s.db.Exec(`UPDATE sensemaking_sessions SET act2_collision=$1::jsonb, updated_at=NOW() WHERE id=$2`, string(dataJSON), sessionID)
	case "act3":
		res, err = s.db.Exec(`UPDATE sensemaking_sessions SET act3_reconstruction=$1::jsonb, status='completed', completed_at=NOW(), updated_at=NOW() WHERE id=$2`, string(dataJSON), sessionID)
	default:
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "unknown act"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Session not found"})
		return
	}
	s.handleGetSenseSession(w, r)
}

// handleGenerateAct POST /sensemaking/sessions/{session_id}/act{1|2|3}/generate。
func (s *Server) handleGenerateAct(w http.ResponseWriter, r *http.Request) {
	act := r.PathValue("act")
	s.generateAct(w, r, act)
}

func (s *Server) generateAct(w http.ResponseWriter, r *http.Request, act string) {
	sessionID := r.PathValue("session_id")
	// 上下文加载：论文 + schema + 前序 act
	var paperID, schemaID string
	var act1Raw, act2Raw []byte
	err := s.db.QueryRow(
		`SELECT paper_id, user_schema_id, COALESCE(act1_comprehension::text,'null'), COALESCE(act2_collision::text,'null')
		 FROM sensemaking_sessions WHERE id=$1`, sessionID,
	).Scan(&paperID, &schemaID, &act1Raw, &act2Raw)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Session not found"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	var paperTitle, paperAbstract, fullText string
	var schemaRaw []byte
	pubExpr := `COALESCE(publication_date,'')`
	_ = pubExpr
	if err := s.db.QueryRow(
		`SELECT p.title, COALESCE(p.abstract,'') FROM papers p WHERE p.id=$1`, paperID,
	).Scan(&paperTitle, &paperAbstract); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Paper not found"})
		return
	}
	// 全文摘录（PDF 文本层，可选）
	if pdfPath := s.paperPDFPath(paperID); pdfPath != "" {
		fullText = core.ExtractPDFTextPublic(pdfPath, 8)
		if len(fullText) > 6000 {
			fullText = fullText[:6000]
		}
	}
	if err := s.db.QueryRow(
		`SELECT research_topics || COALESCE(beliefs,'[]'::jsonb) || COALESCE(knowledge_gaps,'[]'::jsonb) FROM user_schemas WHERE id=$1`, schemaID,
	).Scan(&schemaRaw); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "UserSchema not found"})
		return
	}
	schemaText := string(schemaRaw)

	var prompt string
	var fallback map[string]any
	switch act {
	case "act1":
		prompt = fmt.Sprintf(`你是一位学术认知教练，引导用户「理解」一篇论文。请基于论文内容和用户的研究背景，生成结构化理解结果。

## 输出要求
请输出严格的 JSON 对象：
{"summary": "用中文概括论文核心贡献与思路（200-400字，需结合用户的研究背景定向解读）", "key_findings": ["关键发现1", "关键发现2", "关键发现3"]}

## 用户认知背景:
%s

## 论文标题: %s

## 摘要:
%s

## 全文摘录:
%s
`, schemaText, paperTitle, paperAbstract, fullText)
		fallback = map[string]any{"summary": "生成失败，请重试", "key_findings": []any{}}
	case "act2":
		act1Text := string(act1Raw)
		prompt = fmt.Sprintf(`你是一位认知碰撞引导者。基于用户对论文的理解（Act1）和用户已有的认知（信念、知识盲区），找出论文观点与用户认知之间的冲突，并生成值得深究的疑问。

## 输出要求
请输出严格的 JSON 对象：
{"conflicts": ["冲突点1：论文X vs 用户认知Y"], "questions": ["值得深究的疑问1"]}

## 用户认知背景:
%s

## Act1 理解结果:
%s

## 论文标题: %s

## 摘要:
%s

## 全文摘录:
%s
`, schemaText, act1Text, paperTitle, paperAbstract, truncateRunes(fullText, 4000))
		fallback = map[string]any{"conflicts": []any{}, "questions": []any{}}
	case "act3":
		prompt = fmt.Sprintf(`你是一位认知重构引导者。基于 Act1 的理解与 Act2 的碰撞，帮助用户对比读论文前后的认知变化，形成新认知。

## 输出要求
请输出严格的 JSON 对象：
{"before": "读论文前的认知状态（100-200字）", "after": "读论文后的新认知（100-200字）", "delta": "认知变化的核心描述（80-150字）", "one_change": "一句话概括最重要的认知转变"}

## 用户认知背景:
%s

## Act1 理解结果:
%s

## Act2 碰撞结果:
%s

## 论文标题: %s
`, schemaText, string(act1Raw), string(act2Raw), paperTitle)
		fallback = map[string]any{"before": "", "after": "", "delta": "", "one_change": "生成失败，请重试"}
	default:
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "unknown act"})
		return
	}

	parsed, _, err := s.GW().CompleteJSON(r.Context(), "deep", prompt)
	if err != nil || parsed == nil {
		parsed = fallback
	}
	var dataJSON []byte
	switch act {
	case "act1":
		// 前端契约：act1 包 comprehension 包装层
		wrapped := map[string]any{"comprehension": map[string]any{
			"summary": strOf(parsed["summary"]),
			"key_findings": orSliceAny(parsed["key_findings"]),
		}}
		dataJSON, _ = json.Marshal(wrapped)
	case "act2":
		wrapped := map[string]any{"collision": map[string]any{
			"conflicts": orSliceAny(parsed["conflicts"]),
			"questions": orSliceAny(parsed["questions"]),
		}}
		dataJSON, _ = json.Marshal(wrapped)
	case "act3":
		// act3 裸无包装层
		dataJSON, _ = json.Marshal(map[string]any{
			"before": strOf(parsed["before"]), "after": strOf(parsed["after"]),
			"delta": strOf(parsed["delta"]), "one_change": strOf(parsed["one_change"]),
		})
	}
	// 落库
	var res sql.Result
	if act == "act1" {
		res, err = s.db.Exec(`UPDATE sensemaking_sessions SET act1_comprehension=$1::jsonb, updated_at=NOW() WHERE id=$2`, string(dataJSON), sessionID)
	} else if act == "act2" {
		res, err = s.db.Exec(`UPDATE sensemaking_sessions SET act2_collision=$1::jsonb, updated_at=NOW() WHERE id=$2`, string(dataJSON), sessionID)
	} else {
		res, err = s.db.Exec(`UPDATE sensemaking_sessions SET act3_reconstruction=$1::jsonb, status='completed', completed_at=NOW(), updated_at=NOW() WHERE id=$2`, string(dataJSON), sessionID)
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	_ = res
	s.handleGetSenseSession(w, r)
}

func orSliceAny(v any) []any {
	if list, ok := v.([]any); ok {
		return list
	}
	return []any{}
}

// handleCreateInteraction POST /sensemaking/interactions。
func (s *Server) handleCreateInteraction(w http.ResponseWriter, r *http.Request) {
	var body struct {
		UserSchemaID   string         `json:"user_schema_id"`
		PaperID        string         `json:"paper_id"`
		InteractionType string        `json:"interaction_type"`
		CognitiveDelta map[string]any `json:"cognitive_delta"`
	}
	if err := readBody(r, &body); err != nil || body.UserSchemaID == "" || body.PaperID == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "user_schema_id/paper_id required"})
		return
	}
	deltaJSON := "{}"
	if body.CognitiveDelta != nil {
		b, _ := json.Marshal(body.CognitiveDelta)
		deltaJSON = string(b)
	}
	id := newUUID()
	_, err := s.db.Exec(
		`INSERT INTO schema_paper_interactions (id, user_schema_id, paper_id, interaction_type, cognitive_delta, created_at)
		 VALUES ($1, $2, $3, $4, $5::jsonb, NOW())`,
		id, body.UserSchemaID, body.PaperID, body.InteractionType, deltaJSON)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": id, "status": "created"})
}

// paperPDFPath 论文 PDF 路径（无则空串）。
func (s *Server) paperPDFPath(paperID string) string {
	var pdfPath sql.NullString
	if err := s.db.QueryRow(`SELECT pdf_path FROM papers WHERE id=$1`, paperID).Scan(&pdfPath); err != nil {
		return ""
	}
	if !pdfPath.Valid {
		return ""
	}
	return pdfPath.String
}

// timeNowPtr 当前时间指针（占位防未用 import）。
var _ = time.Now
