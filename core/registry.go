// 能力注册表与内存任务存储（Stage C0 骨架；持久化 schema 在 C2 落库）。
package core

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"sync"
	"time"
)

// CoreVersion 是 Go Core 的版本（C0 骨架阶段手工递增）。
const CoreVersion = "0.1.0-c0"

// Executor 是一个已注册的执行载体。
type Executor struct {
	ID           string
	Capabilities []Capability
	RegisteredAt time.Time
	LastSeen     time.Time
}

// internalTask 是 Core 侧的任务记录（内存态）。
type internalTask struct {
	Task
	Status          string
	ExecutorID      string // 当前 lease 持有者
	LeaseExpires    time.Time
	Result          map[string]any
	FailCount       int
	AttemptCount    int
	LastError       string
	CancelRequested bool
	CreatedAt       time.Time
}

// Registry 持有 Executor、能力与任务的内存态。所有方法并发安全。
type Registry struct {
	mu         sync.Mutex
	executors  map[string]*Executor
	caps       map[string]Capability // capability name → 声明
	tasks      map[string]*internalTask
	queue      []string // FIFO 的 task_id（C0 简化；优先级/依赖在 C6）
	LeaseBaseS int      // lease 基础时长（秒）
}

// NewRegistry 创建空的注册表。
func NewRegistry() *Registry {
	return &Registry{
		executors:  map[string]*Executor{},
		caps:       map[string]Capability{},
		tasks:      map[string]*internalTask{},
		LeaseBaseS: 600,
	}
}

func newID(prefix string) string {
	b := make([]byte, 12)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("%s_%d", prefix, time.Now().UnixNano())
	}
	return prefix + "_" + hex.EncodeToString(b)
}

// RegisterExecutor 登记 Executor 及其能力（重复注册覆盖能力声明）。
func (r *Registry) RegisterExecutor(id string, caps []Capability) {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := time.Now().UTC()
	for _, c := range caps {
		r.caps[c.Name] = c
	}
	if e, ok := r.executors[id]; ok {
		e.Capabilities = caps
		e.LastSeen = now
		return
	}
	r.executors[id] = &Executor{ID: id, Capabilities: caps, RegisteredAt: now, LastSeen: now}
}

// HasExecutor 报告 Executor 是否已注册。
func (r *Registry) HasExecutor(id string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	_, ok := r.executors[id]
	return ok
}

// SubmitTask 入队一个新任务（fake Executor 测试与 C6 调度器都会用）。
func (r *Registry) SubmitTask(capability string, input map[string]any, resourceClass string, timeoutS int) string {
	r.mu.Lock()
	defer r.mu.Unlock()
	id := newID("task")
	if timeoutS <= 0 {
		timeoutS = 600
	}
	if resourceClass == "" {
		resourceClass = "default"
	}
	r.tasks[id] = &internalTask{
		Task:      Task{TaskID: id, Capability: capability, Input: input, ResourceClass: resourceClass, TimeoutS: timeoutS},
		Status:    TaskQueued,
		CreatedAt: time.Now().UTC(),
	}
	r.queue = append(r.queue, id)
	return id
}

// ClaimTask 为 Executor 领取一个与其能力匹配的排队任务并签发 lease。
// 无匹配任务返回 nil。
func (r *Registry) ClaimTask(executorID string, wanted []string) *Task {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.executors[executorID]; !ok {
		return nil // 未注册的 Executor 不能领取
	}
	want := map[string]bool{}
	for _, w := range wanted {
		want[w] = true
	}
	now := time.Now().UTC()
	for i, tid := range r.queue {
		t := r.tasks[tid]
		if t.Status != TaskQueued || !want[t.Capability] {
			continue
		}
		// 出队并签发 lease
		r.queue = append(r.queue[:i], r.queue[i+1:]...)
		t.Status = TaskLeased
		t.ExecutorID = executorID
		t.AttemptID = newID("att")
		t.LeaseExpires = now.Add(time.Duration(r.LeaseBaseS) * time.Second)
		task := t.Task
		task.AttemptID = t.AttemptID
		return &task
	}
	return nil
}

// Heartbeat 续约 lease 并回传取消请求。任务不存在/lease 不属于该 Executor → false。
func (r *Registry) Heartbeat(executorID, taskID, attemptID string) (bool, bool, time.Time) {
	r.mu.Lock()
	defer r.mu.Unlock()
	t, ok := r.tasks[taskID]
	if !ok || t.ExecutorID != executorID || t.AttemptID != attemptID {
		return false, false, time.Time{}
	}
	if e, ok := r.executors[executorID]; ok {
		e.LastSeen = time.Now().UTC()
	}
	t.LeaseExpires = time.Now().UTC().Add(time.Duration(r.LeaseBaseS) * time.Second)
	return true, t.CancelRequested, t.LeaseExpires
}

// CompleteTask 校验 lease 持有者后提交结果（fencing 的最简形态：executor + attempt 必须匹配）。
func (r *Registry) CompleteTask(executorID, taskID, attemptID string, result map[string]any) (bool, string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	t, ok := r.tasks[taskID]
	if !ok || t.ExecutorID != executorID || t.AttemptID != attemptID {
		return false, "unknown_task"
	}
	if t.Status == TaskCanceled {
		return false, "cancelled"
	}
	t.Status = TaskDone
	t.Result = result
	return true, TaskDone
}

// FailTask 记录失败；C0 一律重新入队（backoff/死信在 C8）。
func (r *Registry) FailTask(executorID, taskID, attemptID string) (bool, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	t, ok := r.tasks[taskID]
	if !ok || t.ExecutorID != executorID || t.AttemptID != attemptID {
		return false, false
	}
	t.FailCount++
	t.ExecutorID = ""
	t.Status = TaskQueued
	t.AttemptID = ""
	r.queue = append(r.queue, taskID)
	return true, true
}

// CancelTask 标记取消：未领取直接取消；已领取标记协作取消（Executor 经 heartbeat 感知）。
func (r *Registry) CancelTask(taskID, _ string) (bool, string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	t, ok := r.tasks[taskID]
	if !ok {
		return false, ""
	}
	switch t.Status {
	case TaskQueued:
		t.Status = TaskCanceled
		return true, TaskCanceled
	case TaskLeased:
		t.CancelRequested = true
		return true, TaskLeased
	default:
		return false, t.Status
	}
}

// ExecutorCount 返回已注册 Executor 数（健康检查/测试用）。
func (r *Registry) ExecutorCount() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.executors)
}

// TaskStatus 返回观察面快照（状态/计数/结果）。
func (r *Registry) TaskStatus(taskID string) (internalTask, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	t, ok := r.tasks[taskID]
	if !ok {
		return internalTask{}, false
	}
	return *t, true
}

// ReclaimExpiredLeases 回收过期 lease：leased 任务租期已过 → 回队列（C8 扩展退避）。
func (r *Registry) ReclaimExpiredLeases(now time.Time) int {
	r.mu.Lock()
	defer r.mu.Unlock()
	reclaimed := 0
	for _, t := range r.tasks {
		if t.Status == TaskLeased && !t.LeaseExpires.IsZero() && t.LeaseExpires.Before(now) {
			t.Status = TaskQueued
			t.ExecutorID = ""
			t.AttemptID = ""
			t.FailCount++
			t.AttemptCount++
			r.queue = append(r.queue, t.TaskID)
			reclaimed++
		}
	}
	return reclaimed
}
