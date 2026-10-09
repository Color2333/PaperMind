// 网页侧设备授权决策（GET info / POST authorize·deny —— 仅 Web JWT 会话）。
package main

import (
	"net/http"
	"time"
)

// handleDeviceInfo：授权页查询待授权设备信息。
func (s *Server) handleDeviceInfo(w http.ResponseWriter, r *http.Request) {
	userCode := r.PathValue("code")
	var status, clientName string
	var requestID string
	var expiresAt time.Time
	err := s.db.QueryRow(
		`SELECT id, status, client_name, expires_at::timestamp FROM device_auth_requests
		 WHERE user_code = UPPER($1)`,
		userCode,
	).Scan(&requestID, &status, &clientName, &expiresAt)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "授权请求不存在"})
		return
	}
	if status == "pending" && time.Now().After(expiresAt) {
		_, _ = s.db.Exec(`UPDATE device_auth_requests SET status='expired' WHERE id=$1`, requestID)
		status = "expired"
	}
	expiresIn := int(time.Until(expiresAt).Seconds())
	if expiresIn < 0 {
		expiresIn = 0
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"user_code":   userCode,
		"client_name": clientName,
		"status":      status,
		"expires_in":  expiresIn,
	})
}

// handleDeviceAuthorize / handleDeviceDeny：网页批准/拒绝。
func (s *Server) handleDeviceAuthorize(w http.ResponseWriter, r *http.Request) {
	s.deviceDecision(w, r.PathValue("code"), "approved")
}

func (s *Server) handleDeviceDeny(w http.ResponseWriter, r *http.Request) {
	s.deviceDecision(w, r.PathValue("code"), "denied")
}

func (s *Server) deviceDecision(w http.ResponseWriter, userCode, decision string) {
	res, err := s.db.Exec(
		`UPDATE device_auth_requests SET status=$1, approved_at=now()::timestamp
		 WHERE user_code = UPPER($2) AND status='pending'`,
		decision, userCode,
	)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "授权请求不存在或已处理"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": decision})
}
