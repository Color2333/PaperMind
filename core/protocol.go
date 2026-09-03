// Package core 实现 PaperMind Go Core 的协议类型与常量。
//
// 协议规则：
//   - Executor↔Core 的所有请求/响应都是 JSON 信封：{"schema_version", "correlation_id", ...载荷}
//   - schema_version 不匹配 → 400，correlation_id 原样回显
//   - correlation_id 由调用方生成，用于全链路追踪
//   - Core↔durable-state（Python）走 plain JSON（内部协议，见 stateclient.go）
package core

// SchemaVersion 是 Executor Protocol 的当前协议版本。
const SchemaVersion = 1

// Task 状态值（与 Python TaskStatus 对齐）。
const (
	TaskQueued   = "queued"
	TaskLeased   = "leased"
	TaskRunning  = "running"
	TaskDone     = "succeeded"
	TaskFailed   = "failed"
	TaskCanceled = "cancelled"
)

// Envelope 是所有协议消息的统一信封。
type Envelope struct {
	SchemaVersion int    `json:"schema_version"`
	CorrelationID string `json:"correlation_id"`
}

// Capability 描述 Executor 注册的一种工作能力。
type Capability struct {
	Name          string `json:"name"`
	Version       int    `json:"version"`
	ResourceClass string `json:"resource_class"`
}

// RegisterRequest：Executor 上线并声明能力。
type RegisterRequest struct {
	Envelope
	ExecutorID   string       `json:"executor_id"`
	Capabilities []Capability `json:"capabilities"`
}

// RegisterResponse：注册回执。
type RegisterResponse struct {
	Envelope
	OK          bool   `json:"ok"`
	CoreVersion string `json:"core_version"`
	ExecutorID  string `json:"executor_id"`
}

// ClaimRequest：Executor 按能力领取任务。
type ClaimRequest struct {
	Envelope
	ExecutorID   string   `json:"executor_id"`
	Capabilities []string `json:"capabilities"` // capability 名列表（与注册声明取交集）
}

// Task 是分派给 Executor 的工作原子（durable store 权威形状）。
type Task struct {
	TaskID        string         `json:"task_id"`
	AttemptID     string         `json:"attempt_id"`
	Capability    string         `json:"capability"`
	Input         map[string]any `json:"input"`
	ResourceClass string         `json:"resource_class"`
	TimeoutS      int            `json:"timeout_s"`
	AttemptNo     int            `json:"attempt_no"`
	FencingToken  int            `json:"fencing_token"`
	LeaseToken    string         `json:"lease_token"`
}

// ClaimResponse：领取结果；无任务时 Task 为 null。
type ClaimResponse struct {
	Envelope
	OK   bool  `json:"ok"`
	Task *Task `json:"task"`
}

// HeartbeatRequest：续约 lease 并探测取消请求。
type HeartbeatRequest struct {
	Envelope
	ExecutorID string `json:"executor_id"`
	TaskID     string `json:"task_id"`
	LeaseToken string `json:"lease_token"`
}

// HeartbeatResponse：续约回执；cancel_requested=true 时 Executor 应在安全检查点退出。
type HeartbeatResponse struct {
	Envelope
	OK              bool   `json:"ok"`
	CancelRequested bool   `json:"cancel_requested"`
	LeaseExpiresAt  string `json:"lease_expires_at,omitempty"`
}

// ProgressRequest：Executor 进度上报（聚合进度 + 续约 lease）。
type ProgressRequest struct {
	Envelope
	ExecutorID string `json:"executor_id"`
	TaskID     string `json:"task_id"`
	LeaseToken string `json:"lease_token"`
	Current    int    `json:"current"`
	Total      int    `json:"total"`
	Message    string `json:"message"`
}

// ProgressResponse：进度回执。
type ProgressResponse struct {
	Envelope
	OK bool `json:"ok"`
}

// CompleteRequest：Executor 提交结果 proposal（经 durable store fencing 校验）。
type CompleteRequest struct {
	Envelope
	ExecutorID string         `json:"executor_id"`
	TaskID     string         `json:"task_id"`
	LeaseToken string         `json:"lease_token"`
	Result     map[string]any `json:"result"`
}

// CompleteResponse：提交回执。
type CompleteResponse struct {
	Envelope
	OK     bool   `json:"ok"`
	Status string `json:"status"`
}

// FailRequest：Executor 上报失败（错误分类供 durable store 重试策略使用）。
type FailRequest struct {
	Envelope
	ExecutorID string `json:"executor_id"`
	TaskID     string `json:"task_id"`
	LeaseToken string `json:"lease_token"`
	ErrorClass string `json:"error_class"`
	Message    string `json:"message"`
}

// FailResponse：失败回执；retry_scheduled 指示 durable store 是否重新入队。
type FailResponse struct {
	Envelope
	OK              bool   `json:"ok"`
	Status          string `json:"status"`
	RetryScheduled  bool   `json:"retry_scheduled"`
	AttemptRecorded bool   `json:"attempt_recorded"`
}

// CancelRequest：控制面请求取消任务（未领取→直接取消；已领取→协作取消标记）。
type CancelRequest struct {
	Envelope
	TaskID string `json:"task_id"`
	Reason string `json:"reason"`
}

// CancelResponse：取消回执。
type CancelResponse struct {
	Envelope
	OK     bool   `json:"ok"`
	Status string `json:"status"`
}

// TaskStatusResponse：观察面任务状态（durable store 快照）。
type TaskStatusResponse struct {
	Envelope
	OK           bool           `json:"ok"`
	TaskID       string         `json:"task_id"`
	Status       string         `json:"status"`
	Capability   string         `json:"capability,omitempty"`
	AttemptCount int            `json:"attempt_count"`
	MaxAttempts  int            `json:"max_attempts"`
	Input        map[string]any `json:"input,omitempty"`
	LastError    string         `json:"last_error,omitempty"`
}

// HealthResponse：健康检查（版本化）。
type HealthResponse struct {
	Envelope
	Status      string `json:"status"`
	CoreVersion string `json:"core_version"`
	GoVersion   string `json:"go_version"`
	StateURL    string `json:"state_url,omitempty"`
}
