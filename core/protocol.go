// Package core 实现 PaperMind Go Core 的协议类型与常量（Stage C0）。
//
// 协议规则（设计③ C0）：
//   - 所有请求/响应都是 JSON 信封：{"schema_version", "correlation_id", ...载荷}
//   - schema_version 不匹配 → 400，correlation_id 原样回显
//   - correlation_id 由调用方生成，用于全链路追踪
package core

// SchemaVersion 是 Executor Protocol 的当前协议版本。
const SchemaVersion = 1

// 信封字段名（避免 magic string 散落）。
const (
	FieldSchemaVersion = "schema_version"
	FieldCorrelationID = "correlation_id"
)

// Task 状态（C0 骨架的内存态；持久化 schema 在 C2 落库）。
const (
	TaskQueued   = "queued"
	TaskLeased   = "leased"
	TaskDone     = "done"
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
	OK             bool   `json:"ok"`
	CoreVersion    string `json:"core_version"`
	ExecutorID     string `json:"executor_id"`
	RegisteredTask bool   `json:"registered"`
}

// ClaimRequest：Executor 按能力领取任务。
type ClaimRequest struct {
	Envelope
	ExecutorID   string   `json:"executor_id"`
	Capabilities []string `json:"capabilities"` // capability 名列表
}

// Task 是分派给 Executor 的工作原子（C0 骨架形状；持久化在 C2）。
type Task struct {
	TaskID          string         `json:"task_id"`
	AttemptID       string         `json:"attempt_id"`
	Capability      string         `json:"capability"`
	Input           map[string]any `json:"input"`
	ResourceClass   string         `json:"resource_class"`
	TimeoutS        int            `json:"timeout_s"`
	CancelRequested bool           `json:"cancel_requested"`
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
	AttemptID  string `json:"attempt_id"`
}

// HeartbeatResponse：续约回执；cancel_requested=true 时 Executor 应在安全检查点退出。
type HeartbeatResponse struct {
	Envelope
	OK              bool   `json:"ok"`
	CancelRequested bool   `json:"cancel_requested"`
	LeaseExpiresAt  string `json:"lease_expires_at,omitempty"`
}

// CompleteRequest：Executor 提交结果 proposal（C9 起由 Go 权威提交领域变更）。
type CompleteRequest struct {
	Envelope
	ExecutorID string         `json:"executor_id"`
	TaskID     string         `json:"task_id"`
	AttemptID  string         `json:"attempt_id"`
	Result     map[string]any `json:"result"`
}

// CompleteResponse：提交回执。
type CompleteResponse struct {
	Envelope
	OK     bool   `json:"ok"`
	Status string `json:"status"`
}

// FailRequest：Executor 上报失败（错误分类供 C8 重试策略使用）。
type FailRequest struct {
	Envelope
	ExecutorID string `json:"executor_id"`
	TaskID     string `json:"task_id"`
	AttemptID  string `json:"attempt_id"`
	ErrorClass string `json:"error_class"`
	Message    string `json:"message"`
}

// FailResponse：失败回执；retry_scheduled 指示 Core 是否会重新入队。
type FailResponse struct {
	Envelope
	OK              bool `json:"ok"`
	RetryScheduled  bool `json:"retry_scheduled"`
	AttemptRecorded bool `json:"attempt_recorded"`
}

// CancelRequest：控制面请求取消任务（未领取→直接取消；已领取→标记协作取消）。
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

// HealthResponse：健康检查（版本化）。
type HealthResponse struct {
	Envelope
	Status      string `json:"status"`
	CoreVersion string `json:"core_version"`
	GoVersion   string `json:"go_version"`
}
