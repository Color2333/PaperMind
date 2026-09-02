// C0 骨架测试：fake Executor 走完整协议闭环。
//
// 覆盖：健康检查、注册、领取、心跳（含取消探测）、complete、fail 重入队、
// cancel、schema_version 不匹配拒绝、未注册 Executor 拒绝领取。
package core

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func newTestServer(t *testing.T) (*httptest.Server, *Registry) {
	t.Helper()
	reg := NewRegistry()
	srv := httptest.NewServer(NewServer(reg).Handler())
	t.Cleanup(srv.Close)
	return srv, reg
}

// post 发送信封请求并解码响应信封（body 解到 out）。
func post(t *testing.T, url, correlationID string, payload any, out *map[string]any) int {
	t.Helper()
	env := map[string]any{"schema_version": SchemaVersion, "correlation_id": correlationID, "payload": payload}
	raw, err := json.Marshal(env)
	if err != nil {
		t.Fatal(err)
	}
	resp, err := http.Post(url, "application/json", bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var envelope struct {
		SchemaVersion int            `json:"schema_version"`
		CorrelationID string         `json:"correlation_id"`
		Body          map[string]any `json:"body"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		t.Fatal(err)
	}
	if envelope.CorrelationID != correlationID {
		t.Fatalf("correlation_id 未回显: want %q got %q", correlationID, envelope.CorrelationID)
	}
	if out != nil {
		*out = envelope.Body
	}
	return resp.StatusCode
}

func TestHealthVersioned(t *testing.T) {
	srv, _ := newTestServer(t)
	resp, err := http.Get(srv.URL + "/health")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var envelope struct {
		SchemaVersion int `json:"schema_version"`
		Body          HealthResponse
	}
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		t.Fatal(err)
	}
	if envelope.SchemaVersion != SchemaVersion || envelope.Body.Status != "ok" {
		t.Fatalf("health 异常: %+v", envelope)
	}
	if envelope.Body.CoreVersion == "" || envelope.Body.GoVersion == "" {
		t.Fatalf("health 缺版本信息: %+v", envelope.Body)
	}
}

func TestFakeExecutorFullFlow(t *testing.T) {
	srv, _ := newTestServer(t)
	const cid = "flow-1"

	// 注册（fake Executor 声明 fake_cap 能力）
	var reg map[string]any
	if code := post(t, srv.URL+"/v1/executors/register", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []map[string]any{
			{"name": "fake_cap", "version": 1, "resource_class": "default"},
		}}, &reg); code != 200 {
		t.Fatalf("register status=%d body=%v", code, reg)
	}
	if reg["ok"] != true || reg["executor_id"] != "fake-1" {
		t.Fatalf("register 响应异常: %v", reg)
	}

	// 空领取 → task null（C0 无控制面提交端点；带任务的完整闭环见
	// TestFullFlowWithSubmittedTask，经内存 Registry 注入任务）
	var claim map[string]any
	if code := post(t, srv.URL+"/v1/tasks/claim", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim); code != 200 {
		t.Fatalf("claim status=%d", code)
	}
	if claim["task"] != nil {
		t.Fatalf("空队列不应返回任务: %v", claim["task"])
	}
}

func TestFullFlowWithSubmittedTask(t *testing.T) {
	reg := NewRegistry()
	srv := httptest.NewServer(NewServer(reg).Handler())
	defer srv.Close()
	const cid = "flow-2"

	// 注册 fake Executor
	var regResp map[string]any
	if code := post(t, srv.URL+"/v1/executors/register", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []map[string]any{
			{"name": "fake_cap", "version": 1, "resource_class": "default"},
		}}, &regResp); code != 200 {
		t.Fatalf("register status=%d", code)
	}

	// Core（调度器角色）提交任务
	taskID := reg.SubmitTask("fake_cap", map[string]any{"prompt": "hello"}, "default", 60)

	// 领取
	var claim map[string]any
	if code := post(t, srv.URL+"/v1/tasks/claim", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim); code != 200 {
		t.Fatalf("claim status=%d", code)
	}
	taskAny := claim["task"]
	if taskAny == nil {
		t.Fatal("应领取到任务")
	}
	task := taskAny.(map[string]any)
	if task["task_id"] != taskID || task["capability"] != "fake_cap" || task["input"].(map[string]any)["prompt"] != "hello" {
		t.Fatalf("任务字段不符: %v", task)
	}
	if task["attempt_id"] == "" {
		t.Fatal("attempt_id 必须由 Core 签发")
	}
	attemptID := task["attempt_id"].(string)

	// 心跳续约（无取消）
	var hb map[string]any
	if code := post(t, srv.URL+"/v1/tasks/"+taskID+"/heartbeat", cid,
		map[string]any{"executor_id": "fake-1", "task_id": taskID, "attempt_id": attemptID}, &hb); code != 200 {
		t.Fatalf("heartbeat status=%d", code)
	}
	if hb["cancel_requested"] != false {
		t.Fatalf("不应有取消请求: %v", hb)
	}

	// 完成
	var comp map[string]any
	if code := post(t, srv.URL+"/v1/tasks/"+taskID+"/complete", cid,
		map[string]any{"executor_id": "fake-1", "task_id": taskID, "attempt_id": attemptID,
			"result": map[string]any{"output": "done"}}, &comp); code != 200 {
		t.Fatalf("complete status=%d body=%v", code, comp)
	}
	if comp["status"] != "done" {
		t.Fatalf("complete 后状态应为 done: %v", comp)
	}
}

func TestFailRequeuesAndFencing(t *testing.T) {
	reg := NewRegistry()
	srv := httptest.NewServer(NewServer(reg).Handler())
	defer srv.Close()
	const cid = "flow-3"

	post(t, srv.URL+"/v1/executors/register", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []map[string]any{
			{"name": "fake_cap", "version": 1, "resource_class": "default"},
		}}, nil)
	taskID := reg.SubmitTask("fake_cap", nil, "", 0)

	var claim map[string]any
	post(t, srv.URL+"/v1/tasks/claim", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim)
	task := claim["task"].(map[string]any)
	attemptID := task["attempt_id"].(string)

	// fail → 重入队
	var fail map[string]any
	if code := post(t, srv.URL+"/v1/tasks/"+taskID+"/fail", cid,
		map[string]any{"executor_id": "fake-1", "task_id": taskID, "attempt_id": attemptID,
			"error_class": "network", "message": "boom"}, &fail); code != 200 {
		t.Fatalf("fail status=%d", code)
	}
	if fail["retry_scheduled"] != true {
		t.Fatalf("fail 后应重新入队: %v", fail)
	}

	// 旧 attempt 的 complete 必须被拒绝（fencing 最简形态）
	var comp map[string]any
	code := post(t, srv.URL+"/v1/tasks/"+taskID+"/complete", cid,
		map[string]any{"executor_id": "fake-1", "task_id": taskID, "attempt_id": attemptID,
			"result": map[string]any{"late": true}}, &comp)
	if code != 409 {
		t.Fatalf("迟到 complete 应被拒绝 (409)，got %d: %v", code, comp)
	}

	// 重新领取得到新 attempt
	var claim2 map[string]any
	post(t, srv.URL+"/v1/tasks/claim", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim2)
	newAttempt := claim2["task"].(map[string]any)["attempt_id"].(string)
	if newAttempt == attemptID {
		t.Fatal("重入队后应签发新 attempt")
	}
}

func TestCancelFlow(t *testing.T) {
	reg := NewRegistry()
	srv := httptest.NewServer(NewServer(reg).Handler())
	defer srv.Close()
	const cid = "flow-4"

	post(t, srv.URL+"/v1/executors/register", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []map[string]any{
			{"name": "fake_cap", "version": 1, "resource_class": "default"},
		}}, nil)
	taskID := reg.SubmitTask("fake_cap", nil, "", 0)

	// 未领取：直接取消
	var cancel map[string]any
	if code := post(t, srv.URL+"/v1/tasks/"+taskID+"/cancel", cid,
		map[string]any{"task_id": taskID, "reason": "test"}, &cancel); code != 200 {
		t.Fatalf("cancel status=%d", code)
	}
	if cancel["status"] != TaskCanceled {
		t.Fatalf("排队任务应直接取消: %v", cancel)
	}

	// 已取消的任务不能再领取
	var claim map[string]any
	post(t, srv.URL+"/v1/tasks/claim", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim)
	if claim["task"] != nil {
		t.Fatal("已取消任务不应被领取")
	}
}

func TestSchemaVersionMismatchRejected(t *testing.T) {
	srv, _ := newTestServer(t)
	raw, _ := json.Marshal(map[string]any{
		"schema_version": 99, "correlation_id": "cid-1",
		"payload": map[string]any{"executor_id": "x"},
	})
	resp, err := http.Post(srv.URL+"/v1/executors/register", "application/json", bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 400 {
		t.Fatalf("schema 不匹配应 400，got %d", resp.StatusCode)
	}
	var envelope struct {
		CorrelationID string `json:"correlation_id"`
		Body          map[string]any
	}
	_ = json.NewDecoder(resp.Body).Decode(&envelope)
	if envelope.CorrelationID != "cid-1" {
		t.Fatal("拒绝时也必须回显 correlation_id")
	}
	if envelope.Body["error"] != "schema_version_mismatch" {
		t.Fatalf("错误类型不符: %v", envelope.Body)
	}
}

func TestUnregisteredExecutorCannotClaim(t *testing.T) {
	srv, reg := newTestServer(t)
	reg.SubmitTask("fake_cap", nil, "", 0)
	var claim map[string]any
	code := post(t, srv.URL+"/v1/tasks/claim", "cid-5",
		map[string]any{"executor_id": "ghost", "capabilities": []string{"fake_cap"}}, &claim)
	if code != 200 {
		t.Fatalf("claim status=%d", code)
	}
	if claim["task"] != nil {
		t.Fatal("未注册 Executor 不得领取任务")
	}
}
