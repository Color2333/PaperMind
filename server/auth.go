package main

// auth.go：设备码授权全流程的 Go 移植（与 apps/api/routers/auth.py 逐契约对齐）。
//
// 契约要点：
// - device_code / api_token 明文只给客户端一次，DB 存 SHA-256 hex
// - user_code 字母表去混淆（无 0/O/1/I），格式 XXXX-XXXX
// - device_code 15 分钟过期；poll 节流 5s/code
// - approved 首次 poll 创建 API 令牌（scopes=[read,write], created_by=device）
//   并交付明文；之后返回 delivered
// - start/authorize/deny 需 AUTH_PASSWORD 非空（认证关闭时 403）

import (
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
)

const (
	deviceCodeExpireSeconds = 15 * 60
	devicePollIntervalSec   = 5
	apiTokenPrefix          = "pmt_"
	jwtAlgorithm            = "HS256"
	accessTokenExpireHours  = 24 * 7
	userCodeAlphabet        = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
)

func hashToken(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}

func generateDeviceCode() (raw, codeHash string) {
	raw = randomURLSafe(32)
	return raw, hashToken(raw)
}

func randomURLSafe(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return base64.RawURLEncoding.EncodeToString(b)[:n]
}

func generateUserCode() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	out := make([]byte, 8)
	for i, bv := range b {
		out[i] = userCodeAlphabet[int(bv)%len(userCodeAlphabet)]
	}
	return fmt.Sprintf("%s-%s", out[:4], out[4:])
}

// ---- handlers ----

type deviceStartRequest struct {
	ClientName string `json:"client_name"`
}

func (s *Server) handleDeviceStart(w http.ResponseWriter, r *http.Request) {
	if s.cfg.AuthPassword == "" {
		writeJSON(w, http.StatusForbidden, map[string]string{"detail": "Authentication is disabled"})
		return
	}
	var body deviceStartRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "bad json"})
		return
	}
	clientName := strings.TrimSpace(body.ClientName)
	if clientName == "" {
		clientName = "pm-cli"
	}

	var deviceCode, codeHash, userCode string
	var requestID string
	err := s.withTx(r.Context(), func(tx *sql.Tx) error {
		// 清理过期请求（与 Python cleanup_expired 一致）
		_, _ = tx.Exec(
			`UPDATE device_auth_requests SET status='expired'
			 WHERE status='pending' AND expires_at < now()`)
		deviceCode, codeHash = generateDeviceCode()
		userCode = generateUserCode()
		return tx.QueryRow(
			`INSERT INTO device_auth_requests (id, device_code_hash, user_code, client_name, status, created_at, expires_at)
			 VALUES (gen_random_uuid()::text, $1, $2, $3, 'pending', now()::timestamp, (now()::timestamp + interval '900 seconds'))
			 RETURNING id`,
			codeHash, userCode, clientName,
		).Scan(&requestID)
	})
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"device_code":      deviceCode,
		"user_code":        userCode,
		"verification_url": strings.TrimRight(s.cfg.SiteURL, "/") + "/device?user_code=" + userCode,
		"expires_in":       deviceCodeExpireSeconds,
		"interval":         devicePollIntervalSec,
		"_request_id":      requestID,
	})
}

type devicePollRequest struct {
	DeviceCode string `json:"device_code"`
}

func (s *Server) handleDevicePoll(w http.ResponseWriter, r *http.Request) {
	var body devicePollRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "bad json"})
		return
	}
	code := strings.TrimSpace(body.DeviceCode)
	if code == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "device_code required"})
		return
	}
	// 节流：同一 device_code 5s 内重复 poll → slow_down（与 RFC 8628 语义一致）
	s.pollMu.Lock()
	if s.lastPoll[code] != (time.Time{}) && time.Since(s.lastPoll[code]) < devicePollIntervalSec*time.Second {
		s.pollMu.Unlock()
		writeJSON(w, http.StatusOK, map[string]any{"status": "slow_down", "interval": devicePollIntervalSec})
		return
	}
	s.lastPoll[code] = time.Now()
	s.pollMu.Unlock()

	var status string
	var requestID string
	var tokenID sql.NullString
	var clientName string
	var userCode string
	var approvedAt sql.NullTime
	var expiresAt time.Time
	err := s.db.QueryRow(
		`SELECT id, status, COALESCE(api_token_id::text,''), client_name, user_code, approved_at, expires_at::timestamp
		 FROM device_auth_requests WHERE device_code_hash = $1`,
		hashToken(code),
	).Scan(&requestID, &status, &tokenID, &clientName, &userCode, &approvedAt, &expiresAt)
	if errors.Is(err, sql.ErrNoRows) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "无效的 device_code"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	// 过期判定（pending 且超时 → 标记 expired）
	if status == "pending" && time.Now().After(expiresAt) {
		_, _ = s.db.Exec(`UPDATE device_auth_requests SET status='expired' WHERE id=$1`, requestID)
		status = "expired"
	}
	switch status {
	case "pending":
		writeJSON(w, http.StatusOK, map[string]string{"status": "pending"})
	case "denied":
		writeJSON(w, http.StatusOK, map[string]string{"status": "denied"})
	case "expired":
		writeJSON(w, http.StatusOK, map[string]string{"status": "expired"})
	default:
		// approved：首次 poll 创建 API 令牌并交付明文；之后 delivered
		if !tokenID.Valid {
			raw, name := s.createDeviceAPIToken(clientName, userCode, requestID)
			writeJSON(w, http.StatusOK, map[string]any{
				"status":       "approved",
				"access_token": raw,
				"token_name":   name,
			})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "delivered", "token_name": clientName})
	}
}

// createDeviceAPIToken：设备流批准后的 API 令牌签发（scopes=[read,write]）。
func (s *Server) createDeviceAPIToken(clientName, userCode, deviceRequestID string) (raw, name string) {
	name = fmt.Sprintf("%s (%s)", clientName, userCode)
	raw = apiTokenPrefix + randomURLSafe(32)
	tokenHash := hashToken(raw)
	_, _ = s.db.Exec(
		`INSERT INTO api_tokens (id, name, token_prefix, token_hash, scopes, created_by, device_request_id, created_at)
		 VALUES (gen_random_uuid()::text, $1, $2, $3, '["read","write"]', 'device', $4, now()::timestamp)`,
		name, raw[:12], tokenHash, deviceRequestID,
	)
	return raw, name
}

var _ = deviceCodeExpireSeconds
