// P0：Executor 注册表 + durable-state 客户端。
//
// 架构契约（第二轮 REVIEW P0 修复）：
//   - **权威任务状态只有一份**：Python durable store（jobs/tasks/attempts 表）。
//     Go Core 不再持有任何任务/lease 内存态——进程重启零状态损失。
//   - Go Core 是控制面网关：Executor 注册/认证、claim/complete/fail/heartbeat/
//     cancel/status/reclaim 全部代理到 Python durable-state API。
//   - Executor 只能与自身注册的能力交集 claim（防止越权领取未声明能力）。
package core

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"
)

// CoreVersion 是 Go Core 的版本。
const CoreVersion = "0.2.0-p0"

// StateClient 是 Python durable-state API（/internal/durable/*）的 HTTP 客户端。
type StateClient struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

func NewStateClient(baseURL, token string) *StateClient {
	return &StateClient{
		BaseURL: baseURL,
		Token:   token,
		HTTP:    &http.Client{Timeout: 30 * time.Second},
	}
}

// Post 调用 state API；非 2xx 返回 error（含状态码与响应体摘要）。
func (c *StateClient) Post(path string, in any, out any) error {
	body, err := json.Marshal(in)
	if err != nil {
		return fmt.Errorf("marshal request: %w", err)
	}
	req, err := http.NewRequest(http.MethodPost, c.BaseURL+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.Token != "" {
		req.Header.Set("X-Internal-Token", c.Token)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode >= 300 {
		return &StateError{StatusCode: resp.StatusCode, Body: string(raw)}
	}
	if out != nil {
		if err := json.Unmarshal(raw, out); err != nil {
			return fmt.Errorf("decode response: %w", err)
		}
	}
	return nil
}

func (c *StateClient) Get(path string, out any) error {
	req, err := http.NewRequest(http.MethodGet, c.BaseURL+path, nil)
	if err != nil {
		return err
	}
	if c.Token != "" {
		req.Header.Set("X-Internal-Token", c.Token)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode >= 300 {
		return &StateError{StatusCode: resp.StatusCode, Body: string(raw)}
	}
	if out != nil {
		if err := json.Unmarshal(raw, out); err != nil {
			return fmt.Errorf("decode response: %w", err)
		}
	}
	return nil
}

// StateError 表示 durable-state API 返回了非 2xx。
type StateError struct {
	StatusCode int
	Body       string
}

func (e *StateError) Error() string {
	return fmt.Sprintf("state api %d: %s", e.StatusCode, e.Body)
}

// Executor 是一个已注册的执行载体（内存态——重启后 Executor 重新注册即可）。
type Executor struct {
	ID           string
	Capabilities []Capability
	RegisteredAt time.Time
	LastSeen     time.Time
}

// ExecutorRegistry 只管 Executor 身份与能力声明（无任务态）。
type ExecutorRegistry struct {
	mu        sync.Mutex
	executors map[string]*Executor
}

func NewExecutorRegistry() *ExecutorRegistry {
	return &ExecutorRegistry{executors: map[string]*Executor{}}
}

// RegisterExecutor 登记 Executor 及其能力（重复注册覆盖能力声明）。
func (r *ExecutorRegistry) RegisterExecutor(id string, caps []Capability) {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := time.Now().UTC()
	if e, ok := r.executors[id]; ok {
		e.Capabilities = caps
		e.LastSeen = now
		return
	}
	r.executors[id] = &Executor{ID: id, Capabilities: caps, RegisteredAt: now, LastSeen: now}
}

// HasExecutor 报告 Executor 是否已注册。
func (r *ExecutorRegistry) HasExecutor(id string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	_, ok := r.executors[id]
	return ok
}

// Touch 更新 Executor 的 LastSeen。
func (r *ExecutorRegistry) Touch(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if e, ok := r.executors[id]; ok {
		e.LastSeen = time.Now().UTC()
	}
}

// DeclaredCapabilities 返回 Executor 注册时声明的能力名集合。
func (r *ExecutorRegistry) DeclaredCapabilities(id string) map[string]bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	e, ok := r.executors[id]
	out := map[string]bool{}
	if !ok {
		return out
	}
	for _, c := range e.Capabilities {
		out[c.Name] = true
	}
	return out
}

// Intersect 返回 wanted ∩ declared（claim 越权防护）。
func Intersect(wanted []string, declared map[string]bool) []string {
	out := make([]string, 0, len(wanted))
	seen := map[string]bool{}
	for _, w := range wanted {
		if declared[w] && !seen[w] {
			out = append(out, w)
			seen[w] = true
		}
	}
	return out
}

// ExecutorCount 返回已注册 Executor 数（健康检查/测试用）。
func (r *ExecutorRegistry) ExecutorCount() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.executors)
}
