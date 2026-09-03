// Go Core 的版本化 HTTPS API（Stage C0 骨架）。
//
// 端点：
//
//	GET  /health                              健康检查（版本化）
//	POST /v1/executors/register               Executor 注册（能力声明）
//	POST /v1/tasks/claim                      领取任务
//	POST /v1/tasks/{id}/heartbeat             续约 lease + 取消探测
//	POST /v1/tasks/{id}/complete              提交结果 proposal
//	POST /v1/tasks/{id}/fail                  上报失败
//	POST /v1/tasks/{id}/cancel                取消任务（控制面）
//
// 所有消息走统一信封（protocol.go）：schema_version + correlation_id。
package core

import (
	"encoding/json"
	"net/http"
	"runtime"
	"strings"
	"time"
)

// Server 把 Registry 暴露为 HTTP API。
type Server struct {
	Registry *Registry
	mux      *http.ServeMux
}

// NewServer 创建带全部路由的 Server。
func NewServer(reg *Registry) *Server {
	s := &Server{Registry: reg, mux: http.NewServeMux()}
	s.mux.HandleFunc("GET /health", s.handleHealth)
	s.mux.HandleFunc("POST /v1/executors/register", s.enveloped(s.handleRegister))
	s.mux.HandleFunc("POST /v1/tasks/claim", s.enveloped(s.handleClaim))
	s.mux.HandleFunc("POST /v1/tasks/{id}/heartbeat", s.enveloped(s.handleHeartbeat))
	s.mux.HandleFunc("POST /v1/tasks/{id}/complete", s.enveloped(s.handleComplete))
	s.mux.HandleFunc("POST /v1/tasks/{id}/fail", s.enveloped(s.handleFail))
	s.mux.HandleFunc("POST /v1/tasks/{id}/cancel", s.enveloped(s.handleCancel))
	s.mux.HandleFunc("POST /v1/tasks/submit", s.enveloped(s.handleSubmitTask))
	s.mux.HandleFunc("GET /v1/tasks/{id}/status", s.handleTaskStatusGET)
	return s
}

// Handler 返回 http.Handler（测试与部署共用）。
func (s *Server) Handler() http.Handler { return s.mux }

// writeJSON 写统一响应信封。
func writeJSON(w http.ResponseWriter, status int, correlationID string, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"schema_version": SchemaVersion,
		"correlation_id": correlationID,
		"body":           body,
	})
}

// enveloped 统一解析信封、校验 schema_version、回显 correlation_id。
func (s *Server) enveloped(h func(w http.ResponseWriter, r *http.Request, correlationID string, raw json.RawMessage)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var envelope struct {
			SchemaVersion int             `json:"schema_version"`
			CorrelationID string          `json:"correlation_id"`
			Payload       json.RawMessage `json:"payload"`
		}
		if err := json.NewDecoder(r.Body).Decode(&envelope); err != nil {
			writeJSON(w, http.StatusBadRequest, "", map[string]any{"ok": false, "error": "invalid_json: " + err.Error()})
			return
		}
		if envelope.SchemaVersion != SchemaVersion {
			writeJSON(w, http.StatusBadRequest, envelope.CorrelationID, map[string]any{
				"ok":             false,
				"error":          "schema_version_mismatch",
				"expected":       SchemaVersion,
				"schema_version": envelope.SchemaVersion,
			})
			return
		}
		h(w, r, envelope.CorrelationID, envelope.Payload)
	}
}

func (s *Server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, "", HealthResponse{
		Envelope:    Envelope{SchemaVersion: SchemaVersion},
		Status:      "ok",
		CoreVersion: CoreVersion,
		GoVersion:   runtime.Version(),
	})
}

func (s *Server) handleRegister(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req RegisterRequest
	if err := json.Unmarshal(raw, &req); err != nil || req.ExecutorID == "" {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_register_request"})
		return
	}
	s.Registry.RegisterExecutor(req.ExecutorID, req.Capabilities)
	writeJSON(w, http.StatusOK, cid, RegisterResponse{
		Envelope:    Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:          true,
		CoreVersion: CoreVersion,
		ExecutorID:  req.ExecutorID,
	})
}

func (s *Server) handleClaim(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req ClaimRequest
	if err := json.Unmarshal(raw, &req); err != nil || req.ExecutorID == "" {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_claim_request"})
		return
	}
	task := s.Registry.ClaimTask(req.ExecutorID, req.Capabilities)
	writeJSON(w, http.StatusOK, cid, ClaimResponse{
		Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:       true,
		Task:     task,
	})
}

func (s *Server) taskID(r *http.Request) string {
	// 路径形如 /v1/tasks/{id}/heartbeat —— 取第三段
	parts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
	if len(parts) >= 3 {
		return parts[2]
	}
	return ""
}

func (s *Server) handleHeartbeat(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req HeartbeatRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_heartbeat_request"})
		return
	}
	taskID := s.taskID(r)
	ok, cancelRequested, expires := s.Registry.Heartbeat(req.ExecutorID, taskID, req.AttemptID)
	if !ok {
		writeJSON(w, http.StatusNotFound, cid, map[string]any{"ok": false, "error": "task_or_lease_not_found"})
		return
	}
	writeJSON(w, http.StatusOK, cid, HeartbeatResponse{
		Envelope:        Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:              true,
		CancelRequested: cancelRequested,
		LeaseExpiresAt:  expires.UTC().Format(time.RFC3339),
	})
}

func (s *Server) handleComplete(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req CompleteRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_complete_request"})
		return
	}
	ok, status := s.Registry.CompleteTask(req.ExecutorID, req.TaskID, req.AttemptID, req.Result)
	if !ok {
		writeJSON(w, http.StatusConflict, cid, map[string]any{"ok": false, "error": "complete_rejected", "status": status})
		return
	}
	writeJSON(w, http.StatusOK, cid, CompleteResponse{
		Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:       true,
		Status:   status,
	})
}

func (s *Server) handleFail(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req FailRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_fail_request"})
		return
	}
	ok, retry := s.Registry.FailTask(req.ExecutorID, req.TaskID, req.AttemptID)
	if !ok {
		writeJSON(w, http.StatusConflict, cid, map[string]any{"ok": false, "error": "fail_rejected"})
		return
	}
	writeJSON(w, http.StatusOK, cid, FailResponse{
		Envelope:        Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:              true,
		RetryScheduled:  retry,
		AttemptRecorded: true,
	})
}

func (s *Server) handleCancel(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req CancelRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_cancel_request"})
		return
	}
	taskID := req.TaskID
	if taskID == "" {
		taskID = s.taskID(r)
	}
	ok, status := s.Registry.CancelTask(taskID, req.Reason)
	if !ok {
		writeJSON(w, http.StatusNotFound, cid, map[string]any{"ok": false, "error": "task_not_found", "status": status})
		return
	}
	writeJSON(w, http.StatusOK, cid, CancelResponse{
		Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:       true,
		Status:   status,
	})
}

func (s *Server) handleTaskStatusGET(w http.ResponseWriter, r *http.Request) {
	taskID := s.taskID(r)
	t, ok := s.Registry.TaskStatus(taskID)
	if !ok {
		writeJSON(w, http.StatusNotFound, "", map[string]any{"ok": false, "error": "task_not_found"})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"schema_version": SchemaVersion,
		"correlation_id": "",
		"body": TaskStatusResponse{
			Envelope:        Envelope{SchemaVersion: SchemaVersion},
			OK:              true,
			TaskID:          taskID,
			Status:          t.Status,
			Capability:      t.Capability,
			AttemptCount:    t.AttemptCount,
			FailCount:       t.FailCount,
			CancelRequested: t.CancelRequested,
			Result:          t.Result,
			LastError:       t.LastError,
		},
	})
}


// TokenAuthMiddleware 校验 Bearer token（P1 修复：控制面认证）。
func TokenAuthMiddleware(next http.Handler, token string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			next.ServeHTTP(w, r)
			return
		}
		auth := r.Header.Get("Authorization")
		if auth != "Bearer "+token {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"schema_version": SchemaVersion,
				"correlation_id": "",
				"body":           map[string]any{"ok": false, "error": "unauthorized"},
			})
			return
		}
		next.ServeHTTP(w, r)
	})
}
