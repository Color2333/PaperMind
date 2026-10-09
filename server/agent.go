// Phase 4 agent：/agent/* —— Pi 引擎（spawn pm --json）SSE 桥 + 会话持久化
// + pending actions + conversations CRUD。与 Python host.py 语义逐字段对齐。
package main

import (
	"bufio"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

const sseHeaders = "text/event-stream"

// writeSSE 单事件输出（make_sse 对齐：event: x\ndata: {...}\n\n）。
func writeSSE(w http.ResponseWriter, flusher http.Flusher, event string, data any) {
	payload, _ := json.Marshal(data)
	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, payload)
	if flusher != nil {
		flusher.Flush()
	}
}

// ---------- 引擎选择与模型物化 ----------

// handleAgentEngine GET /agent/engine。
func (s *Server) handleAgentEngine(w http.ResponseWriter, r *http.Request) {
	pmOK := pmBinary() != ""
	forced := strings.ToLower(strings.TrimSpace(envOr("PAPERMIND_AGENT_ENGINE", "pi")))
	engine := "pi"
	if !pmOK || forced == "python" {
		engine = "python"
	}
	var modelSkim, provider string
	err := s.db.QueryRow(
		`SELECT model_skim, provider FROM llm_provider_configs WHERE is_active = true LIMIT 1`,
	).Scan(&modelSkim, &provider)
	if err != nil {
		// env 回退（与 Python _llm_config_from_settings 语义一致）
		provider = envOr("LLM_PROVIDER", "xiaomi")
		modelSkim = envOr("LLM_MODEL_SKIM", "mimo-v2.5")
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"engine": engine, "pm_available": pmOK, "forced": forced,
		"chat_model": modelSkim, "provider": provider,
	})
}

// pmBinary pm 可执行文件定位（PAPERMIND_PM_BIN → PATH）。
func pmBinary() string {
	if v := envOr("PAPERMIND_PM_BIN", ""); v != "" {
		if _, err := os.Stat(v); err == nil {
			return v
		}
	}
	if p, err := exec.LookPath("pm"); err == nil {
		return p
	}
	return ""
}

// agentDir Pi agent 目录（PAPERMIND_AGENT_DIR）。
func agentDir() string {
	if v := envOr("PAPERMIND_AGENT_DIR", ""); v != "" {
		return v
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".config", "papermind", "web-agent")
}

// providerKey DB provider 名 → Pi providers key。
func providerKey(provider string) string {
	re := regexp.MustCompile(`[^a-z0-9-]+`)
	k := strings.Trim(re.ReplaceAllString(strings.ToLower(strings.TrimSpace(provider)), "-"), "-")
	if k == "" {
		return "custom"
	}
	return k
}

// materializeModelConfig DB active LLM 配置 → Pi models.json/settings.json。
// 返回 (providerKey, chatModel, ok)。DB 无配置时回退 env（生产 .env 形态）。
func (s *Server) materializeModelConfig() (string, string, bool) {
	var provider, name, apiKey, apiBase, modelSkim, modelDeep, modelVision string
	err := s.db.QueryRow(
		`SELECT provider, name, api_key, COALESCE(api_base_url,''), model_skim, model_deep, COALESCE(model_vision,'')
		 FROM llm_provider_configs WHERE is_active = true LIMIT 1`,
	).Scan(&provider, &name, &apiKey, &apiBase, &modelSkim, &modelDeep, &modelVision)
	if err != nil {
		// env 回退
		provider = envOr("LLM_PROVIDER", "")
		apiKey = envOr("XIAOMI_API_KEY", "")
		if apiKey == "" {
			apiKey = envOr("OPENAI_API_KEY", "")
		}
		if apiKey == "" {
			return "", "", false
		}
		if provider == "" {
			provider = "xiaomi"
		}
		name = provider + "-env"
		modelSkim = envOr("LLM_MODEL_SKIM", "mimo-v2.5")
		modelDeep = envOr("LLM_MODEL_DEEP", "mimo-v2.5-pro")
		modelVision = envOr("LLM_MODEL_VISION", "")
		if provider == "xiaomi" {
			apiBase = "https://token-plan-cn.xiaomimimo.com/v1"
		}
	}
	dir := agentDir()
	_ = os.MkdirAll(dir, 0o755)
	key := providerKey(provider)
	api := "openai-completions"
	if provider == "anthropic" {
		api = "anthropic-messages"
	} else if provider == "google" {
		api = "google-generative-ai"
	}
	models := []map[string]string{}
	for _, m := range []string{modelSkim, modelDeep, modelVision} {
		if m != "" {
			models = append(models, map[string]string{"id": m, "name": m})
		}
	}
	entry := map[string]any{
		"name": name, "apiKey": apiKey, "api": api, "models": models,
	}
	if apiBase != "" {
		entry["baseUrl"] = strings.TrimRight(apiBase, "/")
	}
	modelsJSON, _ := json.Marshal(map[string]any{"providers": map[string]any{key: entry}})
	settingsJSON, _ := json.Marshal(map[string]string{"defaultProvider": key, "defaultModel": modelSkim})
	_ = os.WriteFile(filepath.Join(dir, "models.json"), modelsJSON, 0o644)
	_ = os.WriteFile(filepath.Join(dir, "settings.json"), settingsJSON, 0o644)
	return key, modelSkim, true
}

// ---------- 会话持久化 ----------

type agentConversation struct {
	ID        string
	Title     string
	CreatedAt time.Time
	UpdatedAt time.Time
}

func (s *Server) getOrCreateConversation(conversationID, title string) (*agentConversation, error) {
	if conversationID != "" {
		var c agentConversation
		err := s.db.QueryRow(
			`SELECT id, COALESCE(title,''), created_at, updated_at FROM agent_conversations WHERE id=$1`,
			conversationID).Scan(&c.ID, &c.Title, &c.CreatedAt, &c.UpdatedAt)
		if err == nil {
			return &c, nil
		}
		if err != sql.ErrNoRows {
			return nil, err
		}
	}
	id := newUUID()
	if title == "" {
		title = "新对话"
	}
	_, err := s.db.Exec(
		`INSERT INTO agent_conversations (id, title, created_at, updated_at) VALUES ($1, $2, NOW(), NOW())`,
		id, title)
	if err != nil {
		return nil, err
	}
	return &agentConversation{ID: id, Title: title, CreatedAt: time.Now(), UpdatedAt: time.Now()}, nil
}

func (s *Server) saveAgentMessage(conversationID, role, content string, meta map[string]any) {
	metaJSON := "{}"
	if len(meta) > 0 {
		b, _ := json.Marshal(meta)
		metaJSON = string(b)
	}
	_, err := s.db.Exec(
		`INSERT INTO agent_messages (id, conversation_id, role, content, meta, created_at)
		 VALUES ($1, $2, $3, $4, $5, NOW())`,
		newUUID(), conversationID, role, content, metaJSON)
	if err != nil {
		// 观察面不阻断流——记录即可（Python 侧同样容错）
		fmt.Printf("[agent] save message error: %v\n", err)
	}
}

// ---------- 会话互斥（同 conversation 串行，与 Python _CHAT_LOCKS 对齐） ----------

var (
	chatLocksMu sync.Mutex
	chatLocks   = map[string]*sync.Mutex{}
)

func chatLock(conversationID string) *sync.Mutex {
	chatLocksMu.Lock()
	defer chatLocksMu.Unlock()
	if l, ok := chatLocks[conversationID]; ok {
		return l
	}
	l := &sync.Mutex{}
	chatLocks[conversationID] = l
	return l
}

// ---------- Pi 事件翻译（host.py _translate 对齐） ----------

// translatePiEvent Pi JSON 行 → (sseEvent, data)；不认识返回 false。
func translatePiEvent(event map[string]any) (string, map[string]any, bool) {
	etype, _ := event["type"].(string)
	switch etype {
	case "message_update":
		sub, _ := event["assistantMessageEvent"].(map[string]any)
		if sub == nil {
			return "", nil, false
		}
		if sub["type"] == "text_delta" {
			if delta, _ := sub["delta"].(string); delta != "" {
				return "text_delta", map[string]any{"content": delta}, true
			}
		}
		return "", nil, false
	case "tool_execution_start":
		return "tool_start", map[string]any{
			"id": event["toolCallId"], "name": event["toolName"],
			"args": orEmptyMap(event["args"]),
		}, true
	case "tool_execution_update":
		partial, _ := event["partialResult"].(map[string]any)
		if partial != nil {
			if req, ok := partial["action_request"].(map[string]any); ok && req["id"] != nil {
				tool := req["tool"]
				if tool == nil || tool == "" {
					tool = event["toolName"]
				}
				return "action_confirm", map[string]any{
					"id": req["id"], "description": strOrEmpty(req["description"]),
					"tool": tool, "args": orEmptyMap(req["args"]), "engine": "pi",
				}, true
			}
		}
		return "", nil, false
	case "tool_execution_end":
		result, _ := event["result"].(map[string]any)
		success := true
		if b, ok := event["isError"].(bool); ok {
			success = !b
		}
		return "tool_result", map[string]any{
			"id": event["toolCallId"], "name": event["toolName"],
			"success": success, "summary": summaryOf(result),
			"data": result["details"],
		}, true
	case "message_end":
		message, _ := event["message"].(map[string]any)
		if message != nil {
			if role, _ := message["role"].(string); role == "assistant" {
				stopReason, _ := message["stopReason"].(string)
				if stopReason == "error" || stopReason == "aborted" {
					msg := strOrEmpty(message["errorMessage"])
					if msg == "" {
						msg = "模型请求" + stopReason
					}
					return "error", map[string]any{"message": msg}, true
				}
			}
		}
		return "", nil, false
	case "agent_end":
		return "done", map[string]any{}, true
	}
	return "", nil, false
}

func strOrEmpty(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func orEmptyMap(v any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}

// summaryOf Pi result content 提取前 200 字。
func summaryOf(result map[string]any) any {
	if result == nil {
		return nil
	}
	content, ok := result["content"].([]any)
	if !ok {
		return nil
	}
	for _, piece := range content {
		if m, ok := piece.(map[string]any); ok && m["type"] == "text" {
			if t, ok := m["text"].(string); ok && t != "" {
				r := []rune(t)
				if len(r) > 200 {
					return string(r[:200])
				}
				return t
			}
		}
	}
	return nil
}

var knownPiEvents = map[string]bool{
	"agent_start": true, "agent_end": true, "turn_start": true, "turn_end": true,
	"message_start": true, "message_update": true, "message_end": true,
	"tool_execution_start": true, "tool_execution_update": true, "tool_execution_end": true,
}

// ---------- /agent/chat（SSE） ----------

func (s *Server) handleAgentChat(w http.ResponseWriter, r *http.Request) {
	var body struct {
		ConversationID    string `json:"conversation_id"`
		Messages          []struct {
			Role    string         `json:"role"`
			Content string         `json:"content"`
			Meta    map[string]any `json:"meta"`
		} `json:"messages"`
		ConfirmedActionID string `json:"confirmed_action_id"`
	}
	if err := readBody(r, &body); err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "invalid body"})
		return
	}
	// 会话解析/创建（首条 user 消息作标题）
	title := "新对话"
	var lastUser string
	for _, m := range body.Messages {
		if m.Role == "user" {
			title = truncateRunes(m.Content, 50)
			lastUser = m.Content
		}
	}
	conv, err := s.getOrCreateConversation(body.ConversationID, title)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	// 保存本次请求带来的新消息（system 跳过；content 前 200 去重）
	savedKeys := map[string]bool{}
	for _, m := range body.Messages {
		if m.Role == "system" {
			continue
		}
		key := m.Role + ":" + truncateRunes(m.Content, 200)
		if !savedKeys[key] {
			s.saveAgentMessage(conv.ID, m.Role, m.Content, m.Meta)
			savedKeys[key] = true
		}
	}

	flusher, ok := w.(http.Flusher)
	if !ok {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "streaming unsupported"})
		return
	}
	hdr := w.Header()
	hdr.Set("Content-Type", sseHeaders)
	hdr.Set("Cache-Control", "no-cache, no-store")
	hdr.Set("Connection", "keep-alive")
	hdr.Set("X-Accel-Buffering", "no")
	hdr.Set("X-Content-Type-Options", "nosniff")

	writeSSE(w, flusher, "conversation_init", map[string]any{"conversation_id": conv.ID})

	// Pi 引擎：spawn pm（confirmed_action 存在时回退 python——前端确认卡流程）
	engine := "pi"
	forced := strings.ToLower(strings.TrimSpace(envOr("PAPERMIND_AGENT_ENGINE", "pi")))
	if body.ConfirmedActionID != "" || forced == "python" || pmBinary() == "" {
		engine = "python"
	}
	writeSSE(w, flusher, "engine", map[string]any{"engine": engine})

	if lastUser == "" {
		writeSSE(w, flusher, "error", map[string]any{"message": "缺少用户消息"})
		writeSSE(w, flusher, "done", map[string]any{})
		return
	}

	lock := chatLock(conv.ID)
	if !lock.TryLock() {
		writeSSE(w, flusher, "error", map[string]any{"message": "同会话已有进行中的对话，请稍候"})
		writeSSE(w, flusher, "done", map[string]any{})
		return
	}
	defer lock.Unlock()

	if engine == "pi" {
		s.streamPiChat(w, flusher, r, conv.ID, lastUser)
		return
	}
	// python 引擎回退：确认机制流（pending-action 轮询由 pm 工具承担；
	// 纯 python 流仅在 PAPERMIND_AGENT_ENGINE=python 强制时出现）
	writeSSE(w, flusher, "error", map[string]any{"message": "python 引擎已随 backend 退役；请配置 pm（PAPERMIND_PM_BIN）"})
	writeSSE(w, flusher, "done", map[string]any{})
}

// streamPiChat spawn pm -p --json --session <file> <prompt>，翻译事件为 SSE，
// 流内持久化 text/tool 消息（与 Python stream_with_save 语义一致）。
func (s *Server) streamPiChat(w http.ResponseWriter, flusher http.Flusher, r *http.Request, conversationID, prompt string) {
	provider, _, ok := s.materializeModelConfig()
	if !ok {
		writeSSE(w, flusher, "error", map[string]any{"message": "未配置 LLM 提供者：请在 Settings → LLM Gateway 添加并激活配置"})
		writeSSE(w, flusher, "done", map[string]any{})
		return
	}
	_ = provider

	agentRoot := agentDir()
	sfile := filepath.Join(agentRoot, "web-sessions", conversationID+".jsonl")
	workspace := filepath.Join(agentRoot, "workspaces", conversationID)
	_ = os.MkdirAll(filepath.Dir(sfile), 0o755)
	_ = os.MkdirAll(workspace, 0o755)

	ctx, cancel := context.WithTimeout(r.Context(), 300*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, pmBinary(), "-p", "--json", "--session", sfile, prompt)
	cmd.Dir = workspace
	cmd.Env = append(os.Environ(),
		"PAPERMIND_SERVER_URL="+envOr("PAPERMIND_SELF_URL", envOr("SITE_URL", "http://backend:8000")),
		"PAPERMIND_AGENT_DIR="+agentRoot,
		"PAPERMIND_WEBCHAT=1",
		"PAPERMIND_CONVERSATION_ID="+conversationID,
	)
	// 凭据透传（pm 工具以此回访 PaperMind API）
	if auth := r.Header.Get("Authorization"); auth != "" {
		cmd.Env = append(cmd.Env, "PAPERMIND_TOKEN="+strings.TrimPrefix(auth, "Bearer "))
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		writeSSE(w, flusher, "error", map[string]any{"message": err.Error()})
		writeSSE(w, flusher, "done", map[string]any{})
		return
	}
	stderr, _ := cmd.StderrPipe()
	if err := cmd.Start(); err != nil {
		writeSSE(w, flusher, "error", map[string]any{"message": "pm 启动失败: " + err.Error()})
		writeSSE(w, flusher, "done", map[string]any{})
		return
	}
	go drainStderr(stderr)

	textBuf := strings.Builder{}
	toolRecords := []any{}
	toolCallID := ""
	savedDone := false
	emittedError := false
	emittedDone := false

	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 1024*1024), 8*1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var event map[string]any
		if json.Unmarshal([]byte(line), &event) != nil {
			continue
		}
		etype, _ := event["type"].(string)
		if !knownPiEvents[etype] {
			continue
		}
		// 去重（Pi 自动重试产出多组 error/done）
		if etype == "message_end" && emittedError {
			continue
		}
		if etype == "agent_end" && emittedDone {
			continue
		}
		sseType, data, ok := translatePiEvent(event)
		if !ok {
			continue
		}
		switch sseType {
		case "text_delta":
			textBuf.WriteString(strOf(data["content"]))
		case "tool_start":
			toolCallID, _ = data["id"].(string)
		case "tool_result":
			toolRecords = append(toolRecords, data)
			toolJSON, _ := json.Marshal(data)
			s.saveAgentMessage(conversationID, "tool", string(toolJSON), map[string]any{"tool_call_id": toolCallID})
		case "message_end":
			emittedError = true
		case "done":
			emittedDone = true
		}
		writeSSE(w, flusher, sseType, data)
		// 客户端断开检测（context 取消 → 终止 pm）
		select {
		case <-ctx.Done():
			_ = cmd.Process.Kill()
			return
		default:
		}
	}
	_ = cmd.Wait()
	// assistant 消息落库（修④：只存一次）
	if !savedDone && (textBuf.Len() > 0 || len(toolRecords) > 0) {
		meta := map[string]any{}
		if len(toolRecords) > 0 {
			meta["tool_calls"] = toolRecords
		}
		s.saveAgentMessage(conversationID, "assistant", textBuf.String(), meta)
	}
	if !emittedDone {
		writeSSE(w, flusher, "done", map[string]any{})
	}
}

func drainStderr(stderr interface{ Read([]byte) (int, error) }) {
	scanner := bufio.NewScanner(stderr)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	for scanner.Scan() {
		// 排空防 PIPE 阻塞（与 Python _drain_stderr 一致）
	}
}

// ---------- pending actions ----------

// handleCreatePendingAction POST /agent/pending-actions（pm 工具回调创建）。
func (s *Server) handleCreatePendingAction(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Tool           string         `json:"tool"`
		Args           map[string]any `json:"args"`
		ConversationID string         `json:"conversation_id"`
		Description    string         `json:"description"`
	}
	if err := readBody(r, &body); err != nil || strings.TrimSpace(body.Tool) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "tool required"})
		return
	}
	actionID := newUUID()
	argsJSON, _ := json.Marshal(orEmptyMap(body.Args))
	state, _ := json.Marshal(map[string]any{
		"engine": "pi", "status": "pending", "description": body.Description,
	})
	_, err := s.db.Exec(
		`INSERT INTO agent_pending_actions (id, tool_name, tool_args, conversation_id, conversation_state, created_at)
		 VALUES ($1, $2, $3::jsonb, $4, $5::jsonb, NOW())`,
		actionID, body.Tool, string(argsJSON), nullIfEmptyStr(body.ConversationID), string(state))
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": actionID, "status": "pending"})
}

// handleGetPendingAction GET /agent/pending-actions/{action_id}（pm 工具轮询）。
func (s *Server) handleGetPendingAction(w http.ResponseWriter, r *http.Request) {
	actionID := r.PathValue("action_id")
	var toolName string
	var stateRaw []byte
	err := s.db.QueryRow(
		`SELECT tool_name, COALESCE(conversation_state,'{}'::jsonb) FROM agent_pending_actions WHERE id=$1`,
		actionID).Scan(&toolName, &stateRaw)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "确认请求不存在或已过期"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	var state map[string]any
	_ = json.Unmarshal(stateRaw, &state)
	status := "pending"
	if v, ok := state["status"].(string); ok {
		status = v
	}
	desc, _ := state["description"].(string)
	writeJSON(w, http.StatusOK, map[string]any{
		"id": actionID, "status": status, "tool": toolName, "description": desc,
	})
}

// resolvePiAction Pi 引擎决定落库（engine=pi 时返回 true——不走流暂停续播）。
func (s *Server) resolvePiAction(actionID, decision string) bool {
	var stateRaw []byte
	err := s.db.QueryRow(
		`SELECT COALESCE(conversation_state,'{}'::jsonb) FROM agent_pending_actions WHERE id=$1`,
		actionID).Scan(&stateRaw)
	if err != nil {
		return false
	}
	var state map[string]any
	_ = json.Unmarshal(stateRaw, &state)
	if engine, _ := state["engine"].(string); engine != "pi" {
		return false
	}
	state["status"] = decision
	stateJSON, _ := json.Marshal(state)
	_, err = s.db.Exec(
		`UPDATE agent_pending_actions SET conversation_state=$1::jsonb WHERE id=$2`,
		string(stateJSON), actionID)
	return err == nil
}

// handleAgentConfirm POST /agent/confirm/{action_id}。
func (s *Server) handleAgentConfirm(w http.ResponseWriter, r *http.Request) {
	if s.resolvePiAction(r.PathValue("action_id"), "approved") {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "status": "approved"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "status": "approved"})
}

// handleAgentReject POST /agent/reject/{action_id}。
func (s *Server) handleAgentReject(w http.ResponseWriter, r *http.Request) {
	if s.resolvePiAction(r.PathValue("action_id"), "rejected") {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "status": "rejected"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "status": "rejected"})
}

// ---------- conversations CRUD ----------

// handleListConversations GET /agent/conversations。
func (s *Server) handleListConversations(w http.ResponseWriter, r *http.Request) {
	limit := queryInt(r, "limit", 50)
	rows, err := s.db.Query(
		`SELECT id, COALESCE(title,''), TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
		        TO_CHAR(updated_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')
		 FROM agent_conversations ORDER BY updated_at DESC LIMIT $1`, limit)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	conversations := []map[string]any{}
	for rows.Next() {
		var id, title, createdAt, updatedAt string
		if rows.Scan(&id, &title, &createdAt, &updatedAt) == nil {
			if title == "" {
				title = "无标题"
			}
			conversations = append(conversations, map[string]any{
				"id": id, "title": title, "created_at": createdAt, "updated_at": updatedAt,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"conversations": conversations})
}

// handleGetConversation GET /agent/conversations/{id}。
func (s *Server) handleGetConversation(w http.ResponseWriter, r *http.Request) {
	convID := r.PathValue("conversation_id")
	limit := queryInt(r, "limit", 100)
	var id, title, createdAt string
	err := s.db.QueryRow(
		`SELECT id, COALESCE(title,''), TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')
		 FROM agent_conversations WHERE id=$1`, convID).Scan(&id, &title, &createdAt)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "会话不存在"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if title == "" {
		title = "无标题"
	}
	rows, err := s.db.Query(
		`SELECT id, role, content, COALESCE(meta::text,''), TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')
		 FROM agent_messages WHERE conversation_id=$1 ORDER BY created_at LIMIT $2`, convID, limit)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	messages := []map[string]any{}
	for rows.Next() {
		var mid, role, content, metaStr, msgCreatedAt string
		if rows.Scan(&mid, &role, &content, &metaStr, &msgCreatedAt) == nil {
			var meta any
			_ = json.Unmarshal([]byte(metaStr), &meta)
			messages = append(messages, map[string]any{
				"id": mid, "role": role, "content": content, "meta": meta, "created_at": msgCreatedAt,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"conversation": map[string]any{"id": id, "title": title, "created_at": createdAt},
		"messages":     messages,
	})
}

// handleDeleteConversation DELETE /agent/conversations/{id}。
func (s *Server) handleDeleteConversation(w http.ResponseWriter, r *http.Request) {
	convID := r.PathValue("conversation_id")
	res, err := s.db.Exec(`DELETE FROM agent_conversations WHERE id=$1`, convID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "会话不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"deleted": convID})
}

func nullIfEmptyStr(s string) any {
	if s == "" {
		return nil
	}
	return s
}
