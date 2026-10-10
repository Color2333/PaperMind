// Phase 5：web 认证（login/status/me/tokens）+ settings（llm/email/daily-report）
// + system（worker/status/metrics）。
package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	core "github.com/Color2333/PaperMind/core"
)

// ---------- 认证 ----------

// handleLogin POST /auth/login —— 站点密码换 JWT。
func (s *Server) handleLogin(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Password string `json:"password"`
	}
	if err := readBody(r, &body); err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "invalid body"})
		return
	}
	if s.cfg.AuthPassword == "" {
		writeJSON(w, http.StatusForbidden, map[string]string{"detail": "Authentication is disabled"})
		return
	}
	// hmac.compare_digest 语义（防时序攻击）
	if subtle.ConstantTimeCompare([]byte(body.Password), []byte(s.cfg.AuthPassword)) != 1 {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "Incorrect password"})
		return
	}
	token, err := s.signWebJWT("papermind-user")
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"access_token": token, "token_type": "bearer"})
}

// handleAuthStatus GET /auth/status。
func (s *Server) handleAuthStatus(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"auth_enabled": s.cfg.AuthPassword != ""})
}

// handleMe GET /auth/me —— pm whoami/doctor 身份面。
func (s *Server) handleMe(w http.ResponseWriter, r *http.Request) {
	if s.cfg.AuthPassword == "" {
		writeJSON(w, http.StatusOK, map[string]any{"auth_method": "disabled"})
		return
	}
	token := bearerToken(r)
	if token == "" {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "Not authenticated"})
		return
	}
	// API 令牌 → token 明细
	var id, name, prefix string
	var scopesRaw []byte
	err := s.db.QueryRow(
		`SELECT id, name, token_prefix, scopes FROM api_tokens
		 WHERE token_hash=$1 AND revoked_at IS NULL
		   AND (expires_at IS NULL OR expires_at > now()::timestamp)`,
		hashToken(token)).Scan(&id, &name, &prefix, &scopesRaw)
	if err == nil {
		var scopes []string
		_ = json.Unmarshal(scopesRaw, &scopes)
		writeJSON(w, http.StatusOK, map[string]any{
			"auth_method": "api_token", "scopes": scopes,
			"token_id": id, "token_name": name, "token_prefix": prefix,
		})
		return
	}
	if validWebJWT(token, s.cfg.SecretKey) {
		writeJSON(w, http.StatusOK, map[string]any{"auth_method": "jwt", "sub": "papermind-user"})
		return
	}
	writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "Not authenticated"})
}

// signWebJWT 签发 HS256 web 会话（24h，与 Python ACCESS_TOKEN_EXPIRE_HOURS 对齐）。
func (s *Server) signWebJWT(sub string) (string, error) {
	header := base64URL([]byte(`{"alg":"HS256","typ":"JWT"}`))
	claims := fmt.Sprintf(`{"sub":"%s","exp":%d}`, sub, time.Now().Add(24*time.Hour).Unix())
	payload := base64URL([]byte(claims))
	mac := hmac.New(sha256.New, []byte(s.cfg.SecretKey))
	mac.Write([]byte(header + "." + payload))
	sig := base64URL(mac.Sum(nil))
	return header + "." + payload + "." + sig, nil
}

func base64URL(b []byte) string {
	return base64.RawURLEncoding.EncodeToString(b)
}

// ---------- API 令牌管理 ----------

// hashTokenLocal sha256 十六进制（与 auth.go hashToken 同义，别名复用）。

// handleCreateToken POST /auth/tokens（仅 web JWT）。
func (s *Server) handleCreateToken(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Name          string   `json:"name"`
		Scopes        []string `json:"scopes"`
		ExpiresInDays int      `json:"expires_in_days"`
	}
	if err := readBody(r, &body); err != nil || strings.TrimSpace(body.Name) == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "name required"})
		return
	}
	validScopes := []string{}
	for _, sc := range body.Scopes {
		if sc == "read" || sc == "write" {
			validScopes = append(validScopes, sc)
		}
	}
	if len(validScopes) == 0 {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "scopes 至少包含 read 或 write"})
		return
	}
	raw := newUUID() + newUUID()
	sum := sha256.Sum256([]byte(raw))
	prefix := raw[:12]
	var expiresSQL any
	if body.ExpiresInDays > 0 {
		expiresSQL = time.Now().UTC().AddDate(0, 0, body.ExpiresInDays).Format("2006-01-02 15:04:05.000000")
	}
	scopesJSON, _ := json.Marshal(validScopes)
	id := newUUID()
	err := s.db.QueryRow(
		`INSERT INTO api_tokens (id, name, token_prefix, token_hash, scopes, created_by, created_at, expires_at)
		 VALUES ($1, $2, $3, $4, $5, 'web', NOW(), $6) RETURNING id`,
		id, body.Name, prefix, hex.EncodeToString(sum[:]), string(scopesJSON), expiresSQL,
	).Scan(&id)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	out := map[string]any{
		"id": id, "name": body.Name, "token": raw, "token_prefix": prefix,
		"scopes": validScopes, "expires_at": nil,
	}
	if expiresSQL != nil {
		out["expires_at"] = expiresSQL
	}
	writeJSON(w, http.StatusOK, out)
}

// handleListTokens GET /auth/tokens（仅 web JWT，脱敏）。
func (s *Server) handleListTokens(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(
		`SELECT id, name, token_prefix, scopes, created_by,
		        TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
		        TO_CHAR(last_used_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
		        TO_CHAR(expires_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"')
		 FROM api_tokens WHERE revoked_at IS NULL ORDER BY created_at DESC`)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, name, prefix, createdBy, createdAt string
		var scopesRaw []byte
		var lastUsed, expires sql.NullString
		if rows.Scan(&id, &name, &prefix, &scopesRaw, &createdBy, &createdAt, &lastUsed, &expires) == nil {
			var scopes []string
			_ = json.Unmarshal(scopesRaw, &scopes)
			items = append(items, map[string]any{
				"id": id, "name": name, "token_prefix": prefix, "scopes": scopes,
				"created_by": createdBy, "created_at": createdAt,
				"last_used_at": nullStr(lastUsed), "expires_at": nullStr(expires),
			})
		}
	}
	writeJSON(w, http.StatusOK, items)
}

// handleRevokeToken DELETE /auth/tokens/{token_id}。
func (s *Server) handleRevokeToken(w http.ResponseWriter, r *http.Request) {
	tokenID := r.PathValue("token_id")
	res, err := s.db.Exec(
		`UPDATE api_tokens SET revoked_at = NOW() WHERE id=$1 AND revoked_at IS NULL`, tokenID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "令牌不存在或已吊销"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "revoked"})
}

func nullStr(ns sql.NullString) any {
	if ns.Valid {
		return ns.String
	}
	return nil
}

// ---------- settings：LLM providers ----------

func maskKey(key string) string {
	if len(key) <= 8 {
		return "****"
	}
	return key[:4] + "****" + key[len(key)-4:]
}

func (s *Server) llmCfgOut(id, name, provider, apiKey, apiBase, skim, deep, vision, embedding, fallback string, active bool) map[string]any {
	return map[string]any{
		"id": id, "name": name, "provider": provider,
		"api_key_masked": maskKey(apiKey), "api_base_url": nullIfEmptyStr(apiBase),
		"model_skim": skim, "model_deep": deep,
		"model_vision": nullIfEmptyStr(vision), "model_embedding": embedding,
		"model_fallback": fallback, "is_active": active,
	}
}

// handleListLLMProviders GET /settings/llm-providers。
func (s *Server) handleListLLMProviders(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(
		`SELECT id, name, provider, api_key, COALESCE(api_base_url,''), model_skim, model_deep,
		        COALESCE(model_vision,''), model_embedding, model_fallback, is_active
		 FROM llm_provider_configs ORDER BY created_at`)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, name, provider, apiKey, apiBase, skim, deep, vision, embedding, fallback string
		var active bool
		if rows.Scan(&id, &name, &provider, &apiKey, &apiBase, &skim, &deep, &vision, &embedding, &fallback, &active) == nil {
			items = append(items, s.llmCfgOut(id, name, provider, apiKey, apiBase, skim, deep, vision, embedding, fallback, active))
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

// handleActiveLLMProvider GET /settings/llm-providers/active。
func (s *Server) handleActiveLLMProvider(w http.ResponseWriter, r *http.Request) {
	var id, name, provider, apiKey, apiBase, skim, deep, vision, embedding, fallback string
	var active bool
	err := s.db.QueryRow(
		`SELECT id, name, provider, api_key, COALESCE(api_base_url,''), model_skim, model_deep,
		        COALESCE(model_vision,''), model_embedding, model_fallback, is_active
		 FROM llm_provider_configs WHERE is_active = true LIMIT 1`,
	).Scan(&id, &name, &provider, &apiKey, &apiBase, &skim, &deep, &vision, &embedding, &fallback, &active)
	if err == nil {
		writeJSON(w, http.StatusOK, map[string]any{"source": "database", "config": s.llmCfgOut(id, name, provider, apiKey, apiBase, skim, deep, vision, embedding, fallback, active)})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"source": "env", "config": map[string]any{
		"provider":       envOr("LLM_PROVIDER", "xiaomi"),
		"model_skim":     envOr("LLM_MODEL_SKIM", "mimo-v2.5"),
		"model_deep":     envOr("LLM_MODEL_DEEP", "mimo-v2.5-pro"),
		"model_vision":   envOr("LLM_MODEL_VISION", "mimo-v2.5"),
		"model_embedding": envOr("EMBEDDING_MODEL", "BAAI/bge-m3"),
		"model_fallback": envOr("LLM_MODEL_FALLBACK", "mimo-v2.5-pro"),
		"is_active":      true,
	}})
}

// handleCreateLLMProvider POST /settings/llm-providers。
func (s *Server) handleCreateLLMProvider(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Name           string `json:"name"`
		Provider       string `json:"provider"`
		APIKey         string `json:"api_key"`
		APIBaseURL     string `json:"api_base_url"`
		ModelSkim      string `json:"model_skim"`
		ModelDeep      string `json:"model_deep"`
		ModelVision    string `json:"model_vision"`
		ModelEmbedding string `json:"model_embedding"`
		ModelFallback  string `json:"model_fallback"`
	}
	if err := readBody(r, &body); err != nil || body.Name == "" || body.Provider == "" || body.APIKey == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "name/provider/api_key required"})
		return
	}
	if body.ModelSkim == "" {
		body.ModelSkim = "mimo-v2.5"
	}
	if body.ModelDeep == "" {
		body.ModelDeep = "mimo-v2.5-pro"
	}
	if body.ModelEmbedding == "" {
		body.ModelEmbedding = "BAAI/bge-m3"
	}
	if body.ModelFallback == "" {
		body.ModelFallback = body.ModelDeep
	}
	id := newUUID()
	_, err := s.db.Exec(
		`INSERT INTO llm_provider_configs (id, name, provider, api_key, api_base_url, model_skim, model_deep, model_vision, model_embedding, model_fallback, is_active, created_at, updated_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, false, NOW(), NOW())`,
		id, body.Name, body.Provider, body.APIKey, nullIfEmptyStr(body.APIBaseURL),
		body.ModelSkim, body.ModelDeep, nullIfEmptyStr(body.ModelVision),
		body.ModelEmbedding, body.ModelFallback)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, s.llmCfgOut(id, body.Name, body.Provider, body.APIKey, body.APIBaseURL, body.ModelSkim, body.ModelDeep, body.ModelVision, body.ModelEmbedding, body.ModelFallback, false))
}

// handleUpdateLLMProvider PATCH /settings/llm-providers/{config_id}（字段级 merge）。
func (s *Server) handleUpdateLLMProvider(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("config_id")
	var body map[string]any
	if err := readBody(r, &body); err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "invalid body"})
		return
	}
	sets, args := []string{}, []any{id}
	colMap := map[string]string{
		"name": "name", "provider": "provider", "api_key": "api_key",
		"api_base_url": "api_base_url", "model_skim": "model_skim",
		"model_deep": "model_deep", "model_vision": "model_vision",
		"model_embedding": "model_embedding", "model_fallback": "model_fallback",
	}
	i := 2
	for key, col := range colMap {
		if v, ok := body[key]; ok {
			sets = append(sets, fmt.Sprintf("%s=$%d", col, i))
			args = append(args, v)
			i++
		}
	}
	if len(sets) == 0 {
		writeJSON(w, http.StatusOK, map[string]any{"updated": id})
		return
	}
	res, err := s.db.Exec(
		`UPDATE llm_provider_configs SET `+strings.Join(sets, ", ")+`, updated_at=NOW() WHERE id=$1`, args...)
	if err != nil || func() bool { n, _ := res.RowsAffected(); return n == 0 }() {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "配置不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"updated": id})
}

// handleDeleteLLMProvider DELETE /settings/llm-providers/{config_id}。
func (s *Server) handleDeleteLLMProvider(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("config_id")
	res, err := s.db.Exec(`DELETE FROM llm_provider_configs WHERE id=$1`, id)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "配置不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"deleted": id})
}

// handleActivateLLMProvider POST /settings/llm-providers/{config_id}/activate。
func (s *Server) handleActivateLLMProvider(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("config_id")
	tx, err := s.db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer tx.Rollback()
	if _, err := tx.Exec(`UPDATE llm_provider_configs SET is_active = false WHERE is_active = true`); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	res, err := tx.Exec(`UPDATE llm_provider_configs SET is_active = true, updated_at=NOW() WHERE id=$1`, id)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "配置不存在"})
		return
	}
	if err := tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"activated": id})
}

// handleDeactivateLLMProviders POST /settings/llm-providers/deactivate。
func (s *Server) handleDeactivateLLMProviders(w http.ResponseWriter, r *http.Request) {
	_, err := s.db.Exec(`UPDATE llm_provider_configs SET is_active = false WHERE is_active = true`)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"deactivated": true})
}

// ---------- settings：邮箱配置 ----------

// handleListEmailConfigs GET /settings/email-configs。
func (s *Server) handleListEmailConfigs(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(
		`SELECT id, name, smtp_server, smtp_port, smtp_use_tls, sender_email, sender_name, username, is_active
		 FROM email_configs ORDER BY created_at`)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, name, server, senderEmail, senderName, username string
		var port int
		var useTLS, active bool
		if rows.Scan(&id, &name, &server, &port, &useTLS, &senderEmail, &senderName, &username, &active) == nil {
			items = append(items, map[string]any{
				"id": id, "name": name, "smtp_server": server, "smtp_port": port,
				"smtp_use_tls": useTLS, "sender_email": senderEmail,
				"sender_name": senderName, "username": username, "is_active": active,
			})
		}
	}
	writeJSON(w, http.StatusOK, items)
}

// handleCreateEmailConfig POST /settings/email-configs。
func (s *Server) handleCreateEmailConfig(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Name        string `json:"name"`
		SMTPServer  string `json:"smtp_server"`
		SMTPPort    int    `json:"smtp_port"`
		SMTPUseTLS  bool   `json:"smtp_use_tls"`
		SenderEmail string `json:"sender_email"`
		SenderName  string `json:"sender_name"`
		Username    string `json:"username"`
		Password    string `json:"password"`
	}
	if err := readBody(r, &body); err != nil || body.Name == "" || body.SMTPServer == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "name/smtp_server required"})
		return
	}
	if body.SMTPPort == 0 {
		body.SMTPPort = 587
	}
	if body.SenderName == "" {
		body.SenderName = "PaperMind"
	}
	id := newUUID()
	_, err := s.db.Exec(
		`INSERT INTO email_configs (id, name, smtp_server, smtp_port, smtp_use_tls, sender_email, sender_name, username, password, is_active, created_at, updated_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, false, NOW(), NOW())`,
		id, body.Name, body.SMTPServer, body.SMTPPort, body.SMTPUseTLS,
		body.SenderEmail, body.SenderName, body.Username, body.Password)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": id, "name": body.Name, "is_active": false})
}

// handleUpdateEmailConfig PATCH /settings/email-configs/{config_id}。
func (s *Server) handleUpdateEmailConfig(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("config_id")
	var body map[string]any
	if err := readBody(r, &body); err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "invalid body"})
		return
	}
	colMap := map[string]string{
		"name": "name", "smtp_server": "smtp_server", "smtp_port": "smtp_port",
		"smtp_use_tls": "smtp_use_tls", "sender_email": "sender_email",
		"sender_name": "sender_name", "username": "username", "password": "password",
	}
	sets, args := []string{}, []any{id}
	i := 2
	for key, col := range colMap {
		if v, ok := body[key]; ok {
			sets = append(sets, fmt.Sprintf("%s=$%d", col, i))
			args = append(args, v)
			i++
		}
	}
	if len(sets) == 0 {
		writeJSON(w, http.StatusOK, map[string]any{"updated": id})
		return
	}
	res, err := s.db.Exec(
		`UPDATE email_configs SET `+strings.Join(sets, ", ")+`, updated_at=NOW() WHERE id=$1`, args...)
	if err != nil || func() bool { n, _ := res.RowsAffected(); return n == 0 }() {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "邮箱配置不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"updated": id})
}

// handleDeleteEmailConfig DELETE /settings/email-configs/{config_id}。
func (s *Server) handleDeleteEmailConfig(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("config_id")
	res, err := s.db.Exec(`DELETE FROM email_configs WHERE id=$1`, id)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "邮箱配置不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"deleted": id})
}

// handleActivateEmailConfig POST /settings/email-configs/{config_id}/activate。
func (s *Server) handleActivateEmailConfig(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("config_id")
	tx, err := s.db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer tx.Rollback()
	if _, err := tx.Exec(`UPDATE email_configs SET is_active = false WHERE is_active = true`); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	res, err := tx.Exec(`UPDATE email_configs SET is_active = true, updated_at=NOW() WHERE id=$1`, id)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "邮箱配置不存在"})
		return
	}
	if err := tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"activated": id})
}

// handleTestEmailConfig POST /settings/email-configs/{config_id}/test。
func (s *Server) handleTestEmailConfig(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("config_id")
	var server, username, password, senderEmail string
	var port int
	err := s.db.QueryRow(
		`SELECT smtp_server, smtp_port, username, password, sender_email FROM email_configs WHERE id=$1`,
		id).Scan(&server, &port, &username, &password, &senderEmail)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "邮箱配置不存在"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	cfg := &smtpTestConfig{host: server, port: fmt.Sprintf("%d", port), user: username, pass: password}
	if !sendTestEmail(cfg, senderEmail) {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "测试邮件发送失败"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"message": "测试邮件发送成功"})
}

// ---------- settings：每日报告 + SMTP 预设 ----------

// handleGetDailyReportConfig GET /settings/daily-report-config。
func (s *Server) handleGetDailyReportConfig(w http.ResponseWriter, r *http.Request) {
	var id string
	var enabled, autoDeep, sendEmail, includeDetails, includeGraph bool
	var deepLimit int
	var recipients, cron string
	err := s.db.QueryRow(
		`SELECT id, enabled, auto_deep_read, deep_read_limit, send_email_report,
		        recipient_emails, cron_expression, include_paper_details, include_graph_insights
		 FROM daily_report_configs LIMIT 1`,
	).Scan(&id, &enabled, &autoDeep, &deepLimit, &sendEmail, &recipients, &cron, &includeDetails, &includeGraph)
	if err == sql.ErrNoRows {
		writeJSON(w, http.StatusOK, map[string]any{
			"enabled": false, "auto_deep_read": true, "deep_read_limit": 10,
			"send_email_report": true, "recipient_emails": "",
			"cron_expression": "0 4 * * *", "include_paper_details": true,
			"include_graph_insights": false,
		})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"enabled": enabled, "auto_deep_read": autoDeep, "deep_read_limit": deepLimit,
		"send_email_report": sendEmail, "recipient_emails": recipients,
		"cron_expression": cron, "include_paper_details": includeDetails,
		"include_graph_insights": includeGraph,
	})
}

// handleUpdateDailyReportConfig PUT /settings/daily-report-config。
func (s *Server) handleUpdateDailyReportConfig(w http.ResponseWriter, r *http.Request) {
	var body map[string]any
	if err := readBody(r, &body); err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "invalid body"})
		return
	}
	colMap := map[string]string{
		"enabled": "enabled", "auto_deep_read": "auto_deep_read",
		"deep_read_limit": "deep_read_limit", "send_email_report": "send_email_report",
		"recipient_emails": "recipient_emails", "cron_expression": "cron_expression",
		"include_paper_details": "include_paper_details",
		"include_graph_insights": "include_graph_insights",
	}
	sets, args := []string{}, []any{}
	i := 1
	for key, col := range colMap {
		if v, ok := body[key]; ok {
			sets = append(sets, fmt.Sprintf("%s=$%d", col, i))
			args = append(args, v)
			i++
		}
	}
	_ = args
	if len(sets) == 0 {
		s.handleGetDailyReportConfig(w, r)
		return
	}
	// upsert（单行表）
	var exists string
	err := s.db.QueryRow(`SELECT id FROM daily_report_configs LIMIT 1`).Scan(&exists)
	if err == sql.ErrNoRows {
		exists = newUUID()
		_, _ = s.db.Exec(
			`INSERT INTO daily_report_configs (id, enabled, auto_deep_read, deep_read_limit, send_email_report, recipient_emails, cron_expression, include_paper_details, include_graph_insights, created_at, updated_at)
			 VALUES ($1, false, true, 10, true, '', '0 4 * * *', true, false, NOW(), NOW())`, exists)
	}
	args = append(args, exists)
	_, err = s.db.Exec(
		`UPDATE daily_report_configs SET `+strings.Join(sets, ", ")+`, updated_at=NOW() WHERE id=$`+fmt.Sprint(i), args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	s.handleGetDailyReportConfig(w, r)
}

// handleSMTPPresets GET /settings/smtp-presets。
func (s *Server) handleSMTPPresets(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"gmail":   map[string]any{"smtp_server": "smtp.gmail.com", "smtp_port": 587, "smtp_use_tls": true},
		"qq":      map[string]any{"smtp_server": "smtp.qq.com", "smtp_port": 587, "smtp_use_tls": true},
		"163":     map[string]any{"smtp_server": "smtp.163.com", "smtp_port": 465, "smtp_use_tls": true},
		"outlook": map[string]any{"smtp_server": "smtp-mail.outlook.com", "smtp_port": 587, "smtp_use_tls": true},
	})
}

// ---------- system ----------

var heartbeatStaleSeconds = 1200

// readWorkerHeartbeat 共享卷心跳（worker 写、goserver 读）。
func readWorkerHeartbeat() map[string]any {
	raw, err := os.ReadFile(envOr("WORKER_HEARTBEAT_FILE", "/app/data/worker_heartbeat.json"))
	if err != nil {
		return nil
	}
	var hb map[string]any
	if json.Unmarshal(raw, &hb) != nil {
		return nil
	}
	if ts, ok := hb["ts"].(float64); ok {
		hb["age_seconds"] = int(time.Since(time.Unix(int64(ts), 0)).Seconds())
		hb["is_stale"] = time.Since(time.Unix(int64(ts), 0)).Seconds() > float64(heartbeatStaleSeconds)
	}
	return hb
}

// handleSystemWorker GET /system/worker。
func (s *Server) handleSystemWorker(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"heartbeat": readWorkerHeartbeat(), "stale_threshold": heartbeatStaleSeconds,
	})
}

// handleSystemStatus GET /system/status。
func (s *Server) handleSystemStatus(w http.ResponseWriter, r *http.Request) {
	var topicsTotal, topicsEnabled, papersTotal, topicErrors int
	_ = s.db.QueryRow(`SELECT COUNT(*), COALESCE(SUM(CASE WHEN enabled THEN 1 ELSE 0 END),0) FROM topic_subscriptions`).Scan(&topicsTotal, &topicsEnabled)
	_ = s.db.QueryRow(`SELECT COUNT(*) FROM papers`).Scan(&papersTotal)
	_ = s.db.QueryRow(`SELECT COUNT(*) FROM topic_subscriptions WHERE COALESCE(last_error,'') != ''`).Scan(&topicErrors)
	var runsTotal, runsFailed int
	latestRun := map[string]any(nil)
	rows, err := s.db.Query(
		`SELECT pipeline_name, status, TO_CHAR(created_at,'YYYY-MM-DD"T"HH24:MI:SS"Z"'), COALESCE(error_message,'')
		 FROM pipeline_runs ORDER BY created_at DESC LIMIT 50`)
	if err == nil {
		for rows.Next() {
			var name, status, createdAt, errMsg string
			if rows.Scan(&name, &status, &createdAt, &errMsg) == nil {
				runsTotal++
				if status == "failed" {
					runsFailed++
				}
				if latestRun == nil {
					latestRun = map[string]any{
						"pipeline_name": name, "status": status,
						"created_at": createdAt, "error_message": errMsg,
					}
				}
			}
		}
		rows.Close()
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"health": map[string]any{"status": "ok", "app": "PaperMind", "component": "goserver"},
		"counts": map[string]any{
			"topics": topicsTotal, "enabled_topics": topicsEnabled,
			"papers_latest_200": papersTotal, "runs_latest_50": runsTotal,
			"failed_runs_latest_50": runsFailed,
		},
		"worker_heartbeat": readWorkerHeartbeat(),
		"topic_errors":     topicErrors,
		"latest_run":       latestRun,
	})
}

// handleMetricsCosts GET /metrics/costs?days=。
// 契约：CostMetrics{window_days, calls, input_tokens, output_tokens, total_cost_usd,
// by_stage:[{stage,calls,total_cost_usd,input_tokens,output_tokens}], by_model:[...]}。
func (s *Server) handleMetricsCosts(w http.ResponseWriter, r *http.Request) {
	days := queryInt(r, "days", 7)
	filter := ""
	if days > 0 {
		filter = fmt.Sprintf(` WHERE created_at >= NOW() - INTERVAL '%d days'`, days)
	}
	var calls int
	var inTok, outTok int64
	var totalCost float64
	if err := s.db.QueryRow(
		`SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(total_cost_usd),0)
		 FROM prompt_traces`+filter).Scan(&calls, &inTok, &outTok, &totalCost); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	byStage := []map[string]any{}
	rows, err := s.db.Query(
		`SELECT stage, COUNT(*), COALESCE(SUM(total_cost_usd),0), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0)
		 FROM prompt_traces` + filter + ` GROUP BY stage ORDER BY COUNT(*) DESC`)
	if err == nil {
		for rows.Next() {
			var stage string
			var c int
			var cost float64
			var inT, outT int64
			if rows.Scan(&stage, &c, &cost, &inT, &outT) == nil {
				byStage = append(byStage, map[string]any{
					"stage": stage, "calls": c, "total_cost_usd": cost,
					"input_tokens": inT, "output_tokens": outT,
				})
			}
		}
		rows.Close()
	}
	byModel := []map[string]any{}
	rows, err = s.db.Query(
		`SELECT provider, model, COUNT(*), COALESCE(SUM(total_cost_usd),0), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0)
		 FROM prompt_traces` + filter + ` GROUP BY provider, model ORDER BY COUNT(*) DESC`)
	if err == nil {
		for rows.Next() {
			var provider, model string
			var c int
			var cost float64
			var inT, outT int64
			if rows.Scan(&provider, &model, &c, &cost, &inT, &outT) == nil {
				byModel = append(byModel, map[string]any{
					"provider": provider, "model": model, "calls": c,
					"total_cost_usd": cost, "input_tokens": inT, "output_tokens": outT,
				})
			}
		}
		rows.Close()
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"window_days":    days,
		"calls":          calls,
		"input_tokens":   inTok,
		"output_tokens":  outTok,
		"total_cost_usd": totalCost,
		"by_stage":       byStage,
		"by_model":       byModel,
	})
}

// smtpTestConfig / sendTestEmail —— settings 测试邮件（core SMTP 复用）。
type smtpTestConfig struct {
	host, port, user, pass string
}

// sendTestEmail 测试邮件（复用 core SendEmailHTML）。
func sendTestEmail(cfg *smtpTestConfig, to string) bool {
	coreCfg := &coreSMTPConfig{Host: cfg.host, Port: cfg.port, User: cfg.user, Password: cfg.pass, From: cfg.user}
	html := "<html><body><h3>PaperMind 测试邮件</h3><p>邮箱配置验证成功。</p></body></html>"
	return core.SendEmailHTML(coreCfg, to, "PaperMind 测试邮件", html)
}

// coreSMTPConfig 别名（避免与 core 包名冲突的本地命名）。
type coreSMTPConfig = core.SMTPConfig
