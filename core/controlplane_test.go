// C6：控制面提交 / 观察面 / Reconciler 测试。
//
// 覆盖：控制面提交任务 → fake Executor 领取完成（闭环）、任务状态观察端点、
// Reconciler 回收过期 lease（短 lease + 时钟推进）、schema 不匹配拒绝。
package core

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestControlPlaneSubmitAndExecute(t *testing.T) {
	reg := NewRegistry()
	srv := httptest.NewServer(NewServer(reg).Handler())
	defer srv.Close()
	const cid = "c6-1"

	// fake Executor 注册
	post(t, srv.URL+"/v1/executors/register", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []map[string]any{
			{"name": "fake_cap", "version": 1, "resource_class": "default"},
		}}, nil)

	// 控制面提交
	var submit map[string]any
	if code := post(t, srv.URL+"/v1/tasks/submit", cid,
		map[string]any{"capability": "fake_cap", "input": map[string]any{"x": 1},
			"resource_class": "default", "timeout_s": 60}, &submit); code != 200 {
		t.Fatalf("submit status=%d body=%v", code, submit)
	}
	taskID := submit["task_id"].(string)
	if taskID == "" {
		t.Fatal("submit 应返回 task_id")
	}

	// 领取 → 完成
	var claim map[string]any
	post(t, srv.URL+"/v1/tasks/claim", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim)
	task := claim["task"].(map[string]any)
	attemptID := task["attempt_id"].(string)

	var comp map[string]any
	if code := post(t, srv.URL+"/v1/tasks/"+taskID+"/complete", cid,
		map[string]any{"executor_id": "fake-1", "task_id": taskID, "attempt_id": attemptID,
			"result": map[string]any{"out": 1}}, &comp); code != 200 {
		t.Fatalf("complete status=%d", code)
	}

	// 观察面状态
	var status map[string]any
	resp, err := http.Get(srv.URL + "/v1/tasks/" + taskID + "/status")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var envelope struct {
		Body TaskStatusResponse
	}
	_ = json.NewDecoder(resp.Body).Decode(&envelope)
	status = map[string]any{"status": envelope.Body.Status, "result": envelope.Body.Result}
	if status["status"] != TaskDone {
		t.Fatalf("观察面状态应为 done: %v", status)
	}
	if status["result"].(map[string]any)["out"] != float64(1) {
		t.Fatalf("观察面应含结果: %v", status)
	}
}

func TestReconcilerReclaimsExpiredLease(t *testing.T) {
	reg := NewRegistry()
	reg.LeaseBaseS = 0 // 领取即过期（测试用）
	srv := httptest.NewServer(NewServer(reg).Handler())
	defer srv.Close()
	const cid = "c6-2"

	post(t, srv.URL+"/v1/executors/register", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []map[string]any{
			{"name": "fake_cap", "version": 1, "resource_class": "default"},
		}}, nil)
	reg.SubmitTask("fake_cap", nil, "", 0)

	var claim map[string]any
	post(t, srv.URL+"/v1/tasks/claim", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim)
	if claim["task"] == nil {
		t.Fatal("应领取到任务")
	}

	// lease 已过期（LeaseBaseS=0）：Reconciler 回收
	reclaimed := reg.ReclaimExpiredLeases(time.Now().UTC().Add(time.Second))
	if reclaimed != 1 {
		t.Fatalf("应回收 1 个过期 lease，got %d", reclaimed)
	}

	// 回收后可重新领取（新 attempt）
	var claim2 map[string]any
	post(t, srv.URL+"/v1/tasks/claim", cid,
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim2)
	if claim2["task"] == nil {
		t.Fatal("回收后应可重新领取")
	}
	if claim2["task"].(map[string]any)["attempt_id"] == claim["task"].(map[string]any)["attempt_id"] {
		t.Fatal("重新领取应签发新 attempt")
	}
}

func TestSubmitValidation(t *testing.T) {
	srv, _ := newTestServer(t)
	// 缺 capability → 400
	var body map[string]any
	if code := post(t, srv.URL+"/v1/tasks/submit", "cid", map[string]any{"input": map[string]any{}}, &body); code != 400 {
		t.Fatalf("缺 capability 应 400，got %d", code)
	}
}
