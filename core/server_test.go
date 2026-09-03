// P0 网关测试：fake durable-state 后端 + Go Core 全协议闭环。
//
// 覆盖：健康检查、注册、领取（含能力交集越权防护）、心跳（含取消探测）、
// complete、fail 重入队、迟到 complete 被 fencing 拒绝（409 透传）、
// cancel、state 故障映射、Reconciler 调用 reclaim、schema 不匹配拒绝。
package core

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

// fakeState 是 durable-state API 的进程内最小实现（权威语义的替身）。
type fakeState struct {
	mu           sync.Mutex
	tasks        map[string]*fakeTask
	reclaimCalls int
	cancelFlag   map[string]bool
}

type fakeTask struct {
	id           string
	capability   string
	input        map[string]any
	status       string
	leaseToken   string
	attemptCount int
	maxAttempts  int
	lastError    string
	order        int
}

func newFakeState() *fakeState {
	return &fakeState{
		tasks:      map[string]*fakeTask{},
		cancelFlag: map[string]bool{},
	}
}

// handler 把 fakeState 暴露为 /internal/durable/* HTTP 服务。
func (f *fakeState) handler(t *testing.T) http.Handler {
	mux := http.NewServeMux()
	enc := func(w http.ResponseWriter, status int, body any) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(body)
	}
	mux.HandleFunc("POST /internal/durable/tasks/claim", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			ExecutorID   string   `json:"executor_id"`
			Capabilities []string `json:"capabilities"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		f.mu.Lock()
		defer f.mu.Unlock()
		for i := 0; i < len(f.tasks); i++ {
			for _, tk := range f.tasks {
				if tk.status != TaskQueued || tk.order != i {
					continue
				}
				want := map[string]bool{}
				for _, c := range req.Capabilities {
					want[c] = true
				}
				if !want[tk.capability] {
					continue
				}
				tk.status = TaskLeased
				tk.attemptCount++
				tk.leaseToken = fmt.Sprintf("lease-%s-%d", tk.id, tk.attemptCount)
				enc(w, 200, map[string]any{"task": map[string]any{
					"task_id":        tk.id,
					"attempt_id":     fmt.Sprintf("%s:%d", tk.id, tk.attemptCount),
					"capability":     tk.capability,
					"input":          tk.input,
					"resource_class": "default",
					"timeout_s":      600,
					"attempt_no":     tk.attemptCount,
					"fencing_token":  tk.attemptCount,
					"lease_token":    tk.leaseToken,
				}})
				return
			}
		}
		enc(w, 200, map[string]any{"task": nil})
	})
	mux.HandleFunc("POST /internal/durable/tasks/{id}/heartbeat", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			LeaseToken string `json:"lease_token"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		id := r.PathValue("id")
		f.mu.Lock()
		defer f.mu.Unlock()
		tk := f.tasks[id]
		if tk == nil || tk.leaseToken == "" || tk.leaseToken != req.LeaseToken {
			enc(w, 200, map[string]any{"ok": false, "cancel_requested": false})
			return
		}
		enc(w, 200, map[string]any{"ok": true, "cancel_requested": f.cancelFlag[id]})
	})
	completeOrFail := func(op string) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			var req struct {
				ExecutorID string         `json:"executor_id"`
				LeaseToken string         `json:"lease_token"`
				Result     map[string]any `json:"result"`
				ErrorClass string         `json:"error_class"`
				Message    string         `json:"message"`
			}
			_ = json.NewDecoder(r.Body).Decode(&req)
			id := r.PathValue("id")
			f.mu.Lock()
			defer f.mu.Unlock()
			tk := f.tasks[id]
			if tk == nil {
				enc(w, 404, map[string]any{"detail": "not found"})
				return
			}
			if tk.status != TaskLeased || tk.leaseToken != req.LeaseToken {
				// fencing 冲突：迟到写入必须被拒绝
				enc(w, 409, map[string]any{"detail": "lease token mismatch (late write rejected)"})
				return
			}
			switch op {
			case "complete":
				tk.status = TaskDone
				tk.leaseToken = ""
				enc(w, 200, map[string]any{"ok": true, "status": TaskDone})
			case "fail":
				if tk.attemptCount >= tk.maxAttempts {
					tk.status = "dead_letter"
				} else {
					tk.status = TaskQueued
				}
				tk.lastError = req.ErrorClass + ": " + req.Message
				tk.leaseToken = ""
				enc(w, 200, map[string]any{"ok": true, "status": tk.status})
			default: // cancel-execution
				tk.status = TaskCanceled
				tk.leaseToken = ""
				enc(w, 200, map[string]any{"ok": true, "status": TaskCanceled})
			}
		}
	}
	mux.HandleFunc("POST /internal/durable/tasks/{id}/complete", completeOrFail("complete"))
	mux.HandleFunc("POST /internal/durable/tasks/{id}/fail", completeOrFail("fail"))
	mux.HandleFunc("POST /internal/durable/tasks/{id}/cancel-execution", completeOrFail("cancel"))
	mux.HandleFunc("POST /internal/durable/tasks/{id}/cancel", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		f.mu.Lock()
		defer f.mu.Unlock()
		tk := f.tasks[id]
		if tk == nil {
			enc(w, 404, map[string]any{"detail": "not found"})
			return
		}
		if tk.status == TaskQueued {
			tk.status = TaskCanceled
			enc(w, 200, map[string]any{"ok": true, "status": TaskCanceled})
			return
		}
		if tk.status == TaskLeased {
			f.cancelFlag[id] = true
			enc(w, 200, map[string]any{"ok": true, "status": TaskLeased, "cancel_requested": true})
			return
		}
		enc(w, 200, map[string]any{"ok": false, "status": tk.status})
	})
	mux.HandleFunc("GET /internal/durable/tasks/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		f.mu.Lock()
		defer f.mu.Unlock()
		tk := f.tasks[id]
		if tk == nil {
			enc(w, 404, map[string]any{"detail": "not found"})
			return
		}
		enc(w, 200, map[string]any{"task": map[string]any{
			"task_id": tk.id, "status": tk.status, "capability": tk.capability,
			"attempt_count": tk.attemptCount, "max_attempts": tk.maxAttempts,
			"input": tk.input, "last_error": tk.lastError,
		}})
	})
	mux.HandleFunc("POST /internal/durable/reclaim", func(w http.ResponseWriter, _ *http.Request) {
		f.mu.Lock()
		f.reclaimCalls++
		f.mu.Unlock()
		enc(w, 200, map[string]any{"outcomes": map[string]string{}})
	})
	return mux
}

func (f *fakeState) addTask(id, capability string, input map[string]any) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.tasks[id] = &fakeTask{
		id: id, capability: capability, input: input,
		status: TaskQueued, maxAttempts: 3, order: len(f.tasks),
	}
}

func (f *fakeState) get(id string) *fakeTask {
	f.mu.Lock()
	defer f.mu.Unlock()
	cp := *f.tasks[id]
	return &cp
}

// newGateway 起一个 fake state 后端 + 指向它的 Go Core，返回 core URL 与 fake。
func newGateway(t *testing.T) (string, *fakeState) {
	t.Helper()
	fake := newFakeState()
	stateSrv := httptest.NewServer(fake.handler(t))
	t.Cleanup(stateSrv.Close)
	coreSrv := httptest.NewServer(NewServer(NewExecutorRegistry(), NewStateClient(stateSrv.URL, "")).Handler())
	t.Cleanup(coreSrv.Close)
	return coreSrv.URL, fake
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

func registerExecutor(t *testing.T, url, cid, executorID string, caps []string) {
	t.Helper()
	capList := make([]map[string]any, 0, len(caps))
	for _, c := range caps {
		capList = append(capList, map[string]any{"name": c, "version": 1, "resource_class": "default"})
	}
	var out map[string]any
	if code := post(t, url+"/v1/executors/register", cid,
		map[string]any{"executor_id": executorID, "capabilities": capList}, &out); code != 200 {
		t.Fatalf("register status=%d body=%v", code, out)
	}
}

func TestHealthVersioned(t *testing.T) {
	url, _ := newGateway(t)
	resp, err := http.Get(url + "/health")
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

func TestFakeExecutorFullFlowEmptyClaim(t *testing.T) {
	url, _ := newGateway(t)
	registerExecutor(t, url, "flow-1", "fake-1", []string{"fake_cap"})

	var claim map[string]any
	if code := post(t, url+"/v1/tasks/claim", "flow-1",
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim); code != 200 {
		t.Fatalf("claim status=%d", code)
	}
	if claim["task"] != nil {
		t.Fatalf("空队列不应返回任务: %v", claim["task"])
	}
}

func TestFullFlowWithSubmittedTask(t *testing.T) {
	url, fake := newGateway(t)
	registerExecutor(t, url, "flow-2", "fake-1", []string{"fake_cap"})
	fake.addTask("task-1", "fake_cap", map[string]any{"prompt": "hello"})

	var claim map[string]any
	if code := post(t, url+"/v1/tasks/claim", "flow-2",
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim); code != 200 {
		t.Fatalf("claim status=%d", code)
	}
	taskAny := claim["task"]
	if taskAny == nil {
		t.Fatal("应领取到任务")
	}
	task := taskAny.(map[string]any)
	if task["task_id"] != "task-1" || task["capability"] != "fake_cap" || task["input"].(map[string]any)["prompt"] != "hello" {
		t.Fatalf("任务字段不符: %v", task)
	}
	if task["lease_token"] == "" {
		t.Fatal("lease_token 必须由 durable store 签发")
	}
	leaseToken := task["lease_token"].(string)

	var hb map[string]any
	if code := post(t, url+"/v1/tasks/task-1/heartbeat", "flow-2",
		map[string]any{"executor_id": "fake-1", "task_id": "task-1", "lease_token": leaseToken}, &hb); code != 200 {
		t.Fatalf("heartbeat status=%d", code)
	}
	if hb["cancel_requested"] != false {
		t.Fatalf("不应有取消请求: %v", hb)
	}

	var comp map[string]any
	if code := post(t, url+"/v1/tasks/task-1/complete", "flow-2",
		map[string]any{"executor_id": "fake-1", "task_id": "task-1", "lease_token": leaseToken,
			"result": map[string]any{"output": "done"}}, &comp); code != 200 {
		t.Fatalf("complete status=%d body=%v", code, comp)
	}
	if comp["status"] != TaskDone {
		t.Fatalf("complete 后状态应为 succeeded: %v", comp)
	}
}

func TestFailRequeuesAndFencing(t *testing.T) {
	url, fake := newGateway(t)
	registerExecutor(t, url, "flow-3", "fake-1", []string{"fake_cap"})
	fake.addTask("task-1", "fake_cap", nil)

	var claim map[string]any
	post(t, url+"/v1/tasks/claim", "flow-3",
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim)
	task := claim["task"].(map[string]any)
	leaseToken := task["lease_token"].(string)

	// fail → 重入队
	var fail map[string]any
	if code := post(t, url+"/v1/tasks/task-1/fail", "flow-3",
		map[string]any{"executor_id": "fake-1", "task_id": "task-1", "lease_token": leaseToken,
			"error_class": "network", "message": "boom"}, &fail); code != 200 {
		t.Fatalf("fail status=%d", code)
	}
	if fail["retry_scheduled"] != true {
		t.Fatalf("fail 后应重新入队: %v", fail)
	}

	// 旧 lease 的 complete 必须被拒绝（fencing 409 透传）
	var comp map[string]any
	code := post(t, url+"/v1/tasks/task-1/complete", "flow-3",
		map[string]any{"executor_id": "fake-1", "task_id": "task-1", "lease_token": leaseToken,
			"result": map[string]any{"late": true}}, &comp)
	if code != 409 {
		t.Fatalf("迟到 complete 应被拒绝 (409)，got %d: %v", code, comp)
	}

	// 重新领取得到新 lease
	var claim2 map[string]any
	post(t, url+"/v1/tasks/claim", "flow-3",
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim2)
	newLease := claim2["task"].(map[string]any)["lease_token"].(string)
	if newLease == leaseToken {
		t.Fatal("重入队后应签发新 lease")
	}
}

func TestCancelFlow(t *testing.T) {
	url, fake := newGateway(t)
	registerExecutor(t, url, "flow-4", "fake-1", []string{"fake_cap"})
	fake.addTask("task-1", "fake_cap", nil)

	var cancel map[string]any
	if code := post(t, url+"/v1/tasks/task-1/cancel", "flow-4",
		map[string]any{"task_id": "task-1", "reason": "test"}, &cancel); code != 200 {
		t.Fatalf("cancel status=%d", code)
	}
	if cancel["status"] != TaskCanceled {
		t.Fatalf("排队任务应直接取消: %v", cancel)
	}

	var claim map[string]any
	post(t, url+"/v1/tasks/claim", "flow-4",
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim)
	if claim["task"] != nil {
		t.Fatal("已取消任务不应被领取")
	}
}

func TestUnregisteredExecutorForbidden(t *testing.T) {
	url, fake := newGateway(t)
	fake.addTask("task-1", "fake_cap", nil)
	var claim map[string]any
	code := post(t, url+"/v1/tasks/claim", "cid-5",
		map[string]any{"executor_id": "ghost", "capabilities": []string{"fake_cap"}}, &claim)
	if code != http.StatusForbidden {
		t.Fatalf("未注册 Executor 应 403，got %d: %v", code, claim)
	}
}

func TestClaimCapabilityIntersection(t *testing.T) {
	// P1 修复：claim 请求的能力与注册声明取交集——只注册了 fake_cap 的 Executor
	// 请求 other_cap 时，交集为空 → 不向 state API 发起领取。
	url, fake := newGateway(t)
	registerExecutor(t, url, "cid-6", "fake-1", []string{"fake_cap"})
	fake.addTask("task-1", "other_cap", nil)

	var claim map[string]any
	code := post(t, url+"/v1/tasks/claim", "cid-6",
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap", "other_cap"}}, &claim)
	if code != 200 {
		t.Fatalf("claim status=%d", code)
	}
	if claim["task"] != nil {
		t.Fatalf("越权能力不得领取: %v", claim["task"])
	}
	if got := fake.get("task-1").status; got != TaskQueued {
		t.Fatalf("任务应仍在队列: %s", got)
	}
}

func TestStateOutageMapped(t *testing.T) {
	// state API 不可达 → 502（而非静默成功）
	state := httptest.NewServer(newFakeState().handler(t))
	state.Close() // 立即关闭制造故障
	coreSrv := httptest.NewServer(NewServer(NewExecutorRegistry(), NewStateClient(state.URL, "")).Handler())
	defer coreSrv.Close()
	registerExecutor(t, coreSrv.URL, "cid-7", "fake-1", []string{"fake_cap"})

	var claim map[string]any
	code := post(t, coreSrv.URL+"/v1/tasks/claim", "cid-7",
		map[string]any{"executor_id": "fake-1", "capabilities": []string{"fake_cap"}}, &claim)
	if code != http.StatusBadGateway {
		t.Fatalf("state 不可用应 502，got %d: %v", code, claim)
	}
}

func TestTaskStatusProxiedFromState(t *testing.T) {
	url, fake := newGateway(t)
	fake.addTask("task-1", "fake_cap", nil)
	resp, err := http.Get(url + "/v1/tasks/task-1/status")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var envelope struct {
		Body TaskStatusResponse
	}
	_ = json.NewDecoder(resp.Body).Decode(&envelope)
	if envelope.Body.Status != TaskQueued || envelope.Body.TaskID != "task-1" {
		t.Fatalf("观察面应代理 durable store 快照: %+v", envelope.Body)
	}
}

func TestReconcilerCallsReclaim(t *testing.T) {
	fake2 := newFakeState()
	stateSrv := httptest.NewServer(fake2.handler(t))
	defer stateSrv.Close()
	srv := NewServer(NewExecutorRegistry(), NewStateClient(stateSrv.URL, ""))
	stop := make(chan struct{})
	srv.StartReconciler(10*time.Millisecond, 60, stop)
	defer close(stop)

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		fake2.mu.Lock()
		calls := fake2.reclaimCalls
		fake2.mu.Unlock()
		if calls >= 3 {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("reconciler 未周期调用 reclaim")
}

func TestSchemaVersionMismatchRejected(t *testing.T) {
	url, _ := newGateway(t)
	raw, _ := json.Marshal(map[string]any{
		"schema_version": 99, "correlation_id": "cid-1",
		"payload": map[string]any{"executor_id": "x"},
	})
	resp, err := http.Post(url+"/v1/executors/register", "application/json", bytes.NewReader(raw))
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
