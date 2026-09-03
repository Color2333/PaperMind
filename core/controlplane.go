// 控制面提交与 Reconciler（Stage C6）。
//
//   - POST /v1/tasks/submit：控制面（APScheduler 过渡期 / 管理端点）把任务提交进
//     Core 内存队列；持久化权威在 Python 侧 durable store（C2），Core 队列是调度面。
//   - Reconciler：周期回收过期 lease（回队列），并统计 dead_letter（C8 扩展退避策略）。
//   - GET /v1/tasks/{id}/status：观察面任务状态。
package core

import (
	"encoding/json"
	"net/http"
	"time"
)

// SubmitTaskRequest：控制面提交任务。
type SubmitTaskRequest struct {
	Envelope
	Capability    string         `json:"capability"`
	Input         map[string]any `json:"input"`
	ResourceClass string         `json:"resource_class"`
	TimeoutS      int            `json:"timeout_s"`
	Priority      int            `json:"priority"`
}

// SubmitTaskResponse：提交回执（task_id 供观察/取消）。
type SubmitTaskResponse struct {
	Envelope
	OK     bool   `json:"ok"`
	TaskID string `json:"task_id"`
	Status string `json:"status"`
}

// TaskStatusResponse：观察面任务状态。
type TaskStatusResponse struct {
	Envelope
	OK              bool           `json:"ok"`
	TaskID          string         `json:"task_id"`
	Status          string         `json:"status"`
	Capability      string         `json:"capability,omitempty"`
	AttemptCount    int            `json:"attempt_count"`
	FailCount       int            `json:"fail_count"`
	CancelRequested bool           `json:"cancel_requested"`
	Result          map[string]any `json:"result,omitempty"`
	LastError       string         `json:"last_error,omitempty"`
}

func (s *Server) handleSubmitTask(w http.ResponseWriter, r *http.Request, cid string, raw json.RawMessage) {
	var req SubmitTaskRequest
	if err := json.Unmarshal(raw, &req); err != nil || req.Capability == "" {
		writeJSON(w, http.StatusBadRequest, cid, map[string]any{"ok": false, "error": "invalid_submit_request"})
		return
	}
	taskID := s.Registry.SubmitTask(req.Capability, req.Input, req.ResourceClass, req.TimeoutS)
	writeJSON(w, http.StatusOK, cid, SubmitTaskResponse{
		Envelope: Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:       true,
		TaskID:   taskID,
		Status:   TaskQueued,
	})
}

func (s *Server) handleTaskStatus(w http.ResponseWriter, r *http.Request, cid string, _ json.RawMessage) {
	taskID := s.taskID(r)
	t, ok := s.Registry.TaskStatus(taskID)
	if !ok {
		writeJSON(w, http.StatusNotFound, cid, map[string]any{"ok": false, "error": "task_not_found"})
		return
	}
	writeJSON(w, http.StatusOK, cid, TaskStatusResponse{
		Envelope:        Envelope{SchemaVersion: SchemaVersion, CorrelationID: cid},
		OK:              true,
		TaskID:          taskID,
		Status:          t.Status,
		Capability:      t.Capability,
		AttemptCount:    t.AttemptCount,
		FailCount:       t.FailCount,
		CancelRequested: t.CancelRequested,
		Result:          t.Result,
		LastError:       t.LastError,
	})
}

// Reconciler 周期回收过期 lease（回队列重跑）。C8 在此扩展 backoff/dead-letter。
func (s *Server) StartReconciler(interval time.Duration, stop <-chan struct{}) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-stop:
				return
			case <-ticker.C:
				s.Registry.ReclaimExpiredLeases(time.Now().UTC())
			}
		}
	}()
}

var _ = json.Marshal // 保持 encoding/json 引用（writeJSON 在 server.go）
