// Go Core 的版本化 API（P0：控制面网关）。
//
// 端点（Executor↔Core，统一信封）：
//
//	GET  /health                    健康检查（版本化）
//	POST /v1/executors/register     Executor 注册（能力声明）
//	POST /v1/tasks/claim            领取任务（代理 durable store）
//	POST /v1/tasks/{id}/heartbeat   续约 lease + 取消探测
//	POST /v1/tasks/{id}/complete    提交结果 proposal
//	POST /v1/tasks/{id}/fail        上报失败
//	POST /v1/tasks/{id}/cancel      取消任务（控制面）
//	GET  /v1/tasks/{id}/status      观察面状态（durable store 快照）
//
// 任务/lease 状态全部代理到 Python durable-state API（/internal/durable/*）；
// Go Core 自身零任务内存态（P0：重启零状态损失）。
package core

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"runtime"
	"strings"
	"time"
)

// Server 把 durable-state API 暴露为 Executor Protocol。
type Server struct {
	Registry *ExecutorRegistry
	State    *StateClient
	mux      *http.ServeMux
}

// NewServer 创建带全部路由的 Server。
func NewServer(reg *ExecutorRegistry, state *StateClient) *Server {
	s := &Server{Registry: reg, State: state, mux: http.NewServeMux()}
	s.mux.HandleFunc("GET /health", s.handleHealth)
	s.mux.HandleFunc("GET /readyz", s.handleReady)
	s.mux.HandleFunc("POST /v1/executors/register", s.enveloped(s.handleRegister))
	s.mux.HandleFunc("POST /v1/tasks/claim", s.enveloped(s.handleClaim))
	s.mux.HandleFunc("POST /v1/tasks/{id}/heartbeat", s.enveloped(s.handleHeartbeat))
	s.mux.HandleFunc("POST /v1/tasks/{id}/progress", s.enveloped(s.handleProgress))
	s.mux.HandleFunc("POST /v1/tasks/{id}/complete", s.enveloped(s.handleComplete))
	s.mux.HandleFunc("POST /v1/tasks/{id}/fail", s.enveloped(s.handleFail))
	s.mux.HandleFunc("POST /v1/tasks/{id}/cancel-execution", s.enveloped(s.handleCancelExecution))
	s.mux.HandleFunc("POST /v1/tasks/{id}/cancel", s.enveloped(s.handleCancel))
	s.mux.HandleFunc("GET /v1/tasks/{id}/domain-result", s.handleDomainResultGET)
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

// handleHealth：liveness（进程存活）恒为 200；
// state 字段反映 durable-state API 的最近探测结果（readiness 由部署层消费）。
// 设计④：durable-state 不可达时 Core 不能假装健康——/healthz 与 /readyz 分离。
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	stateReachable := s.checkStateReady(r.Context())
	writeJSON(w, http.StatusOK, "", HealthResponse{
		Envelope:    Envelope{SchemaVersion: SchemaVersion},
		Status:      "ok",
		CoreVersion: CoreVersion,
		GoVersion:   runtime.Version(),
		StateURL:    s.State.BaseURL,
		StateReady:  stateReachable,
	})
}

// handleReady：readiness——durable-state API 不可达时返回 503（编排层摘除流量）
func (s *Server) handleReady(w http.ResponseWriter, r *http.Request) {
	if !s.checkStateReady(r.Context()) {
		writeJSON(w, http.StatusServiceUnavailable, "", map[string]any{
			"ok": false, "error": "state_unavailable", "state_url": s.State.BaseURL,
		})
		return
	}
	writeJSON(w, http.StatusOK, "", map[string]any{"ok": true})
}

// checkStateReady 快速探测 durable-state（1.5s 超时；结果不缓存——编排层轮询频率即探测频率）
func (s *Server) checkStateReady(ctx context.Context) bool {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.State.BaseURL+"/health", nil)
	if err != nil {
		return false
	}
	client := &http.Client{Timeout: 1500 * time.Millisecond}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode < 500
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
	// P1 修复：未注册的 Executor 不能领取；claim 能力必须与注册声明取交集
	if !s.Registry.HasExecutor(req.ExecutorID) {
		writeJSON(w, http.StatusForbidden, cid, map[string]any{"ok": false, "error": "executor_not_registered"})
		return
	}
	declared := s.Registry.DeclaredCapabilities(req.ExecutorID)
	wanted := Intersect(req.Capabilities, declared)
	if len(wanted) == 0 {
		writeJSON(w, http.StatusOK, cid, ClaimResponse{
			Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
			OK:       true,
			Task:     nil,
		})
		return
	}

	var out struct {
		Task *Task `json:"task"`
	}
	err := s.State.Post("/internal/durable/tasks/claim", map[string]any{
		"executor_id":  req.ExecutorID,
		"capabilities": wanted,
	}, &out)
	if err != nil {
		s.writeStateError(w, cid, err)
		return
	}
	s.Registry.Touch(req.ExecutorID)
	writeJSON(w, http.StatusOK, cid, ClaimResponse{
		Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:       true,
		Task:     out.Task,
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
	if err := json.Unmarshal(raw, &req); err != nil || req.LeaseToken == "" {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_heartbeat_request"})
		return
	}
	var out struct {
		OK              bool `json:"ok"`
		CancelRequested bool `json:"cancel_requested"`
	}
	err := s.State.Post("/internal/durable/tasks/"+s.taskID(r)+"/heartbeat", map[string]any{
		"lease_token": req.LeaseToken,
	}, &out)
	if err != nil {
		s.writeStateError(w, cid, err)
		return
	}
	if !out.OK {
		writeJSON(w, http.StatusConflict, cid, map[string]any{"ok": false, "error": "lease_not_renewable"})
		return
	}
	s.Registry.Touch(req.ExecutorID)
	writeJSON(w, http.StatusOK, cid, HeartbeatResponse{
		Envelope:        Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:              true,
		CancelRequested: out.CancelRequested,
	})
}

func (s *Server) handleProgress(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req ProgressRequest
	if err := json.Unmarshal(raw, &req); err != nil || req.LeaseToken == "" {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_progress_request"})
		return
	}
	var out struct {
		OK bool `json:"ok"`
	}
	err := s.State.Post("/internal/durable/tasks/"+s.taskID(r)+"/progress", map[string]any{
		"lease_token": req.LeaseToken,
		"current":     req.Current,
		"total":       req.Total,
		"message":     req.Message,
	}, &out)
	if err != nil {
		s.writeStateError(w, cid, err)
		return
	}
	s.Registry.Touch(req.ExecutorID)
	writeJSON(w, http.StatusOK, cid, ProgressResponse{
		Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:       out.OK,
	})
}

func (s *Server) handleComplete(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req CompleteRequest
	if err := json.Unmarshal(raw, &req); err != nil || req.LeaseToken == "" {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_complete_request"})
		return
	}
	var out struct {
		OK     bool   `json:"ok"`
		Status string `json:"status"`
	}
	err := s.State.Post("/internal/durable/tasks/"+s.taskID(r)+"/complete", map[string]any{
		"executor_id": req.ExecutorID,
		"lease_token": req.LeaseToken,
		"result":      req.Result,
	}, &out)
	if err != nil {
		s.writeStateError(w, cid, err)
		return
	}
	writeJSON(w, http.StatusOK, cid, CompleteResponse{
		Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:       true,
		Status:   out.Status,
	})
}

func (s *Server) handleFail(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req FailRequest
	if err := json.Unmarshal(raw, &req); err != nil || req.LeaseToken == "" {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_fail_request"})
		return
	}
	var out struct {
		OK     bool   `json:"ok"`
		Status string `json:"status"`
	}
	err := s.State.Post("/internal/durable/tasks/"+s.taskID(r)+"/fail", map[string]any{
		"executor_id": req.ExecutorID,
		"lease_token": req.LeaseToken,
		"error_class": req.ErrorClass,
		"message":     req.Message,
	}, &out)
	if err != nil {
		s.writeStateError(w, cid, err)
		return
	}
	writeJSON(w, http.StatusOK, cid, FailResponse{
		Envelope:        Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:              true,
		Status:          out.Status,
		RetryScheduled:  out.Status == TaskQueued,
		AttemptRecorded: true,
	})
}

// handleCancelExecution 处理协作取消回执（Executor 安全点退出后提交）。
func (s *Server) handleCancelExecution(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req CompleteRequest // executor_id + task_id + lease_token 同形
	if err := json.Unmarshal(raw, &req); err != nil || req.LeaseToken == "" {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_cancel_execution_request"})
		return
	}
	var out struct {
		OK     bool   `json:"ok"`
		Status string `json:"status"`
	}
	err := s.State.Post("/internal/durable/tasks/"+s.taskID(r)+"/cancel-execution", map[string]any{
		"executor_id": req.ExecutorID,
		"lease_token": req.LeaseToken,
	}, &out)
	if err != nil {
		s.writeStateError(w, cid, err)
		return
	}
	writeJSON(w, http.StatusOK, cid, CancelResponse{
		Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:       true,
		Status:   out.Status,
	})
}

func (s *Server) handleCancel(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	// 以 URL path id 为唯一资源标识；payload 携带 task_id 时必须一致（P1 修复）
	pathID := s.taskID(r)
	var req CancelRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_cancel_request"})
		return
	}
	if req.TaskID != "" && req.TaskID != pathID {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{
			"ok": false, "error": "task_id_mismatch",
			"detail": "payload task_id must match URL resource id",
		})
		return
	}
	var out struct {
		OK     bool   `json:"ok"`
		Status string `json:"status"`
	}
	err := s.State.Post("/internal/durable/tasks/"+pathID+"/cancel", map[string]any{
		"reason": req.Reason,
	}, &out)
	if err != nil {
		s.writeStateError(w, cid, err)
		return
	}
	writeJSON(w, http.StatusOK, cid, CancelResponse{
		Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:       out.OK,
		Status:   out.Status,
	})
}

// handleDomainResultGET 幂等卫兵：既有成功领域结果查询（透传 durable store）
func (s *Server) handleDomainResultGET(w http.ResponseWriter, r *http.Request) {
	var out struct {
		Found  bool           `json:"found"`
		TaskID string         `json:"task_id,omitempty"`
		Result map[string]any `json:"result,omitempty"`
	}
	if err := s.State.Get("/internal/durable/tasks/"+s.taskID(r)+"/domain-result", &out); err != nil {
		s.writeStateError(w, "", err)
		return
	}
	writeJSON(w, http.StatusOK, "", out)
}

func (s *Server) handleTaskStatusGET(w http.ResponseWriter, r *http.Request) {
	var out struct {
		Task *struct {
			TaskID       string         `json:"task_id"`
			Status       string         `json:"status"`
			Capability   string         `json:"capability"`
			AttemptCount int            `json:"attempt_count"`
			MaxAttempts  int            `json:"max_attempts"`
			Input        map[string]any `json:"input"`
			LastError    string         `json:"last_error"`
		} `json:"task"`
	}
	if err := s.State.Get("/internal/durable/tasks/"+s.taskID(r), &out); err != nil {
		var se *StateError
		if errors.As(err, &se) && se.StatusCode == http.StatusNotFound {
			writeJSON(w, http.StatusNotFound, "", map[string]any{"ok": false, "error": "task_not_found"})
			return
		}
		writeJSON(w, http.StatusBadGateway, "", map[string]any{"ok": false, "error": "state_unavailable"})
		return
	}
	t := out.Task
	writeJSON(w, http.StatusOK, "", TaskStatusResponse{
		Envelope:     Envelope{SchemaVersion: SchemaVersion},
		OK:           true,
		TaskID:       t.TaskID,
		Status:       t.Status,
		Capability:   t.Capability,
		AttemptCount: t.AttemptCount,
		MaxAttempts:  t.MaxAttempts,
		Input:        t.Input,
		LastError:    t.LastError,
	})
}

// writeStateError 把 durable-state 的错误映射到 Executor 协议响应。
// fencing 冲突（409）必须原样传给 Executor——它是「迟到写入被拒绝」的信号。
func (s *Server) writeStateError(w http.ResponseWriter, cid string, err error) {
	if se, ok := err.(*StateError); ok {
		status := http.StatusBadGateway
		if se.StatusCode == http.StatusConflict {
			status = http.StatusConflict
		} else if se.StatusCode == http.StatusNotFound {
			status = http.StatusNotFound
		}
		writeJSON(w, status, cid, map[string]any{"ok": false, "error": "state_rejected", "detail": se.Body})
		return
	}
	writeJSON(w, http.StatusBadGateway, cid, map[string]any{"ok": false, "error": "state_unavailable"})
}

// StartReconciler 周期驱动 durable store 回收过期 lease（权威逻辑在 Python 侧）。
func (s *Server) StartReconciler(interval time.Duration, backoffS int, stop <-chan struct{}) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-stop:
				return
			case <-ticker.C:
				var out struct {
					Outcomes map[string]string `json:"outcomes"`
				}
				if err := s.State.Post("/internal/durable/reclaim", map[string]any{
					"backoff_s": backoffS,
				}, &out); err != nil {
					continue // state API 暂不可用——下轮重试
				}
				if len(out.Outcomes) > 0 {
					log.Printf("reconciler reclaimed %d lease(s): %v", len(out.Outcomes), out.Outcomes)
				}
			}
		}
	}()
}

// TokenAuthMiddleware 校验 Bearer token（Executor/控制面认证）。
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

// errorsAs 已移除——统一使用标准 errors.As。
