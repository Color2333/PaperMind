# PaperMind Go Core（Stage C0 骨架）

设计依据：[docs/plans/2026-09-02-design-3-durable-execution-protocol.md](../docs/plans/2026-09-02-design-3-durable-execution-protocol.md) 与路线图 C0。

## 现状（C0）

- **Executor Protocol**：版本化信封（`schema_version` + `correlation_id`）之上的六个动作——
  `register / claim / heartbeat / complete / fail / cancel`，外加版本化 `GET /health`。
- **内存 Registry**：Executor 能力注册、任务队列、lease 签发与最简 fencing（executor+attempt 匹配）。
- **纯 stdlib**：零第三方依赖；持久化 schema 在 C2 落库，调度器在 C6。

## 运行

```bash
cd core
go test ./...          # 协议闭环测试（fake Executor）
go run .               # 默认 :8081，CORE_ADDR 可覆盖
```

## 协议（v1）

请求/响应信封：`{"schema_version": 1, "correlation_id": "...", "payload": {...}}`。
`schema_version` 不匹配 → 400 `schema_version_mismatch`；`correlation_id` 全链路回显。

| 端点 | 说明 |
| --- | --- |
| `GET /health` | `{status, core_version, go_version}` |
| `POST /v1/executors/register` | 能力声明（capability name/version/resource_class） |
| `POST /v1/tasks/claim` | 按能力领取；未注册 Executor 拒绝 |
| `POST /v1/tasks/{id}/heartbeat` | 续约 lease + `cancel_requested` 探测 |
| `POST /v1/tasks/{id}/complete` | 结果 proposal；lease/attempt 不匹配 → 409（fencing） |
| `POST /v1/tasks/{id}/fail` | 失败上报 → C0 一律重入队（backoff/死信在 C8） |
| `POST /v1/tasks/{id}/cancel` | 未领取直接取消；已领取协作取消 |

Python 侧客户端：`packages/core_client/client.py`（契约测试 `tests/test_core_client.py`）。

## 后续（Stage C）

C2 任务/Attempt 持久化 → C6 Scheduler/Planner/Dispatcher/Reconciler → C7 Python Executor
真实 capability 接入 → C8 lease/fencing 完整化 → C9 Go 权威提交与副作用账本。
