# PaperMind Go Core（P0：durable-state 控制面网关）

设计依据：[docs/plans/2026-09-02-design-3-durable-execution-protocol.md](../docs/plans/2026-09-02-design-3-durable-execution-protocol.md) 与路线图 C0/C6/C12。

## 架构（P0 闭环后的最终形态）

**durable store（Python SQLAlchemy：jobs/tasks/attempts 表）是任务与 lease 的唯一权威状态。**
Go Core 不持有任何任务内存态——进程重启零状态损失。它的职责是控制面网关：

- Executor 的注册/认证（Bearer `CORE_TOKEN`）与能力声明（内存，重启后 Executor 自动重注册）；
- claim/complete/fail/heartbeat/cancel/status 全部代理到 Python durable-state API
  （`STATE_ADDR` 指向的 `/internal/durable/*`，凭 `X-Internal-Token`）；
- claim 能力与注册声明取交集（越权防护）；未注册 Executor 403；
  fencing 冲突（409）原样透传给 Executor；
- Reconciler 周期驱动 durable store 回收过期 lease（权威逻辑在 Python 侧）。

```
API/CLI/MCP ──POST /jobs/durable──▶ Python API ──只写──▶ durable store（权威状态）
                                          ▲                   │
                            /internal/durable/*（内部令牌）        │
                                          │                    │
Go Core（控制面网关）──────────────────────┘        ◀── reclaim ──┘
   ▲  Executor Protocol（信封 v1 + Bearer）
   │
独立 Python Executor（apps/executor）── claim → handler → fencing 提交
```

## 运行

```bash
cd core && go test ./...                    # 协议闭环测试（fake durable-state 后端）
go build -o papermind-core ./cmd/papermind-core

CORE_TOKEN=xxx STATE_TOKEN=yyy STATE_ADDR=http://127.0.0.1:8000 \
  ./papermind-core                          # 默认 127.0.0.1:8081（不绑所有网卡）
```

环境变量：`CORE_ADDR`（监听地址）、`CORE_TOKEN`（Executor Bearer）、`STATE_ADDR`（durable-state API）、
`STATE_TOKEN`（内部令牌，与后端 `DURABLE_STATE_TOKEN` 一致）、`RECONCILE_INTERVAL_S`、`RECLAIM_BACKOFF_S`。

Python API 侧需 `DURABLE_STATE_TOKEN` 非空才会挂载 `/internal/durable/*`（未配置=不暴露内部面）；
Executor 启动：`python -m apps.executor --core-url ... --core-token ... --capabilities skim_paper`。

## 协议（v1）

请求/响应信封：`{"schema_version": 1, "correlation_id": "...", "payload": {...}}`。
`schema_version` 不匹配 → 400 `schema_version_mismatch`；`correlation_id` 全链路回显。

| 端点 | 说明 |
| --- | --- |
| `GET /health` | `{status, core_version, go_version, state_url}`（免认证） |
| `POST /v1/executors/register` | 能力声明（capability name/version/resource_class） |
| `POST /v1/tasks/claim` | 领取（∩注册能力）；lease_token 由 durable store 签发 |
| `POST /v1/tasks/{id}/heartbeat` | 续约 + `cancel_requested` 探测 |
| `POST /v1/tasks/{id}/complete` | 结果 proposal；lease 不匹配 → 409（fencing） |
| `POST /v1/tasks/{id}/fail` | 失败上报 → durable store 按重试策略处理 |
| `POST /v1/tasks/{id}/cancel-execution` | 协作取消回执（安全点退出，不重试） |
| `POST /v1/tasks/{id}/cancel` | 控制面取消 |
| `GET /v1/tasks/{id}/status` | durable store 状态快照 |

Python 侧客户端：`packages/core_client/client.py`（契约测试 `tests/test_core_client.py`）。

## 端到端验证

- `tests/test_p0_closed_loop.py`：真实 skim 全链路 + API/Core/Executor 分别 SIGKILL 重启恢复；
- `scripts/fault_injection_local.py`：可重复的全进程故障注入（6 场景）。
