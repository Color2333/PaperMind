# PaperMind 2026 重构审查交接

> 给当前重构 Agent：请在继续合并 B7/B8 前处理或明确回应下列问题，并在完成后勾选状态。
> 初始审查基线：`d0fa6b3`（B6）；复核工作区：2026-09-02，HEAD `ef04d26`，含尚未提交的 B7 修改。
> 本文只记录审查意见，不包含修复代码，也没有改动当前 Agent 的在途文件。

## 结论

当前 application 层下沉方向是对的，但仍有 3 个应优先解决的 P1 问题：安装包缺失 application 层、完全失败的入库被报告为成功，以及 query/command 语义边界被破坏。另有 3 个 P2 兼容性与执行协议问题。

## P1：发布 wheel 不包含 `packages.application`

- [x] 状态：已修复（`pyproject.toml` 改为 `[tool.setuptools.packages.find] include=["apps*","packages*"]`；验证：`pip wheel --no-deps` 产物含 26 个 `packages/application/**` 文件，含 commands/queries 子包）

位置：`pyproject.toml:56-67`

`[tool.setuptools].packages` 使用显式包列表，但没有列出 `packages.application` 及其子包。源码运行和仓库内测试可以通过；安装构建出的 wheel 后，CLI/API/agent 对 application 层的导入会失败，因此当前重构版本实际上不可发布。

建议：改为 setuptools package discovery，并显式包含 `apps*`、`packages*`；如果继续维护静态列表，则至少完整加入：

- `packages.application`
- `packages.application.commands`
- `packages.application.queries`
- 后续新增的 application 子包

验收：

```bash
python -m build --wheel
unzip -l dist/*.whl | rg 'packages/application'
```

还应增加一个安装产物 smoke test，而不只是在源码树中 import。

## P1：完全失败的 arXiv 入库仍返回 `success=True`

- [x] 状态：已修复（command 返回稳定 `status: succeeded|partial|failed`；adapter 对 `failed`/`total==0` 返回 `success=False`，摘要含失败数量/原因；partial 保留 `success=True`+`status:partial`。测试：tests/test_agent_ingest_tool.py 四场景——全部成功/ID 未找到/全部写库失败/部分成功）

`import_selected_papers()` 在没有任何论文成功入库时返回 `total == 0`，并可能携带 `failed`；adapter 随后无条件产生 `ToolResult(success=True)`。这会让 Pi/CLI/其他 Agent 把一次完全失败的写操作理解为成功，并可能继续后续推理。

建议语义：

- `total == 0`：返回 `success=False`，摘要包含失败数量和可行动原因。
- `total > 0` 且存在 `failed`：允许视为部分成功，但数据中应有稳定的 `status: partial` 或等价字段。
- 对“选中的 ID 根本没有被 arXiv 返回”和“写库失败”分别保留错误信息。

至少增加以下测试：全部成功、部分成功、全部失败、ID 未找到。

## P1：query/command 边界与 application 层自身约定冲突

- [x] 状态：已修复（queries/analysis 已删除，reasoning/figures 移入 commands/analysis；writing/suggest_keywords 移入 commands/content；wiki/gap 生成移入 commands/graph；update_subscription 移入 commands/topics；get_daily_brief_html 移入 commands/content。守卫：tests/test_application_architecture.py 源码扫描禁止写服务回流 queries，并断言 commands 覆盖生成面）

约定位置：`packages/application/__init__.py:5-9`

该文件明确规定 query 是纯读函数、command 是写函数，但当前存在：

- `packages/application/queries/analysis.py:8-19`：`ReasoningService.analyze()` 会调用 LLM、写 `PromptTrace`、更新 paper metadata；`FigureService.analyze_paper_figures()` 会写图片文件并持久化分析结果。
- `packages/application/queries/topics.py:38-67`：`update_subscription()` 直接修改主题订阅对象，明显是 command。
- `packages/application/queries/graph.py:27-38`：wiki/gap 生成可能触发昂贵的模型计算，不应伪装成普通只读查询；需要明确区分快照读取与生成命令。

风险不只是命名：HTTP GET、缓存、重试、鉴权和未来的 Job 化都会根据 query 是否无副作用作出错误假设。

建议：

- 把 reasoning、figure analysis、wiki/gap generation、subscription update 移到 commands。
- queries 只读取已经生成并持久化的结果。
- 长耗时/付费生成走 `Start* -> Job`，由 worker 执行；不要让 GET 或 read query 隐式触发生成。
- 增加 architecture test，阻止 queries 引入已知写服务，或至少为每个 application 用例声明 `read | write | start_job`。

## P2：ingest adapter 创建不可取消的 daemon thread

- [x] 状态：已修复（模块级有界 `ThreadPoolExecutor(max_workers=1)` 替代裸线程；`events.get` 带 300s 超时与终止语义；入库幂等可重入的说明写入代码。durable Job 化归 Stage C）

每次调用都会创建一个 daemon thread，调用方在 `events.get()` 上无限等待。若客户端断连、generator 被关闭、上层超时或取消，后台入库仍会继续写数据库和启动 PDF 下载，而且调用方无法查询或取消它。

建议：不要在协议 adapter 中自行管理裸线程。短期至少使用有界 executor、超时与明确的取消/终止语义；目标实现应接入 durable Job，返回 `job_id`，进度从统一事件流读取。

## P2：daily brief 的进度事件发生在工作完成之后

- [x] 状态：已修复（删除事后伪造的"正在保存简报..."阶段事件，只保留一条如实的开始事件；真实阶段进度随 publish 命令化在 Stage C 补齐）

`publish_daily_brief()` 是同步调用，收集、生成、保存/发送都已完成后，adapter 才 yield “正在保存简报...”。这会造成虚假进度，调用期间也没有心跳，前端/CLI 容易误判卡死。

建议：由 application command 提供真实 progress callback；或者直接改成 Job/event 流。在无法报告真实阶段前，不要发送事后伪造的阶段事件。

## P2：`search_arxiv` 候选项移除了既有 `index` 字段

- [x] 状态：已恢复（`index` 从 1 起重新随候选返回；契约由 tests/test_agent_ingest_tool.py::test_search_arxiv_tool 断言 count/arxiv_id，后续补全字段断言）

B6 下沉前，候选项包含从 1 开始的 `index`；下沉后的 canonical 映射删除了该字段。现有单测只校验 `arxiv_id`，因此协议回归没有被发现。即使当前 prompt 主张按 `arxiv_id` 选择，旧 CLI/UI/第三方工具仍可能使用序号展示或选择。

建议：兼容期恢复 `index`，并增加完整响应契约测试。若决定删除，需要版本化工具协议，而不是静默改变 shape。

## 已完成的验证

审查 `d0fa6b3` 时：

- B6 定向测试：6 passed。
- 可运行的本地测试集通过；完整 collection 因本机缺少可选依赖 `fastmcp` 而中止，不是断言失败。
- Ruff 与格式检查通过。
- wheel 构建成功，但产物清单确认没有 `packages/application`，由此发现第一个 P1。

HEAD 已继续前进，修复后请重新运行完整测试、构建 wheel，并从一个干净虚拟环境安装该 wheel 做 `pm`/API import smoke test。

## 建议处理顺序

1. 先修 wheel 打包，确保新 application 层可部署。
2. 修正 ingest 完全失败的结果语义并补协议测试。
3. 在 B7/B8 继续扩张前收紧 query/command/Job 分类。
4. 将裸线程和伪进度统一收敛到 durable Job/event 协议。
5. 恢复或版本化 `search_arxiv.index`。

处理完每项后，请在本文对应状态处勾选并附上 commit/test 证据，方便下一轮复审。

---

## 第二轮复审（2026-09-03）

> 审查基线：`6c5dbee`（`refactor/papermind-2026`）；核心执行链结论基于其父提交 `ddc00e1`，最新 Research State 前端提交也已补充审查。
>
> 结论：**禁止合并到 `main`，且当前还不能进入服务器实验。** Stage C 的“完成”状态与真实运行路径不一致；先修完以下阻塞项，再做可重复的本地故障注入实验，最后才讨论 merge。

### [P0] Go Core、Python durable store 与真实业务执行没有闭环

- [x] 状态：已修复（2026-09-03）。架构重构：**durable store 是唯一权威状态，Go Core 变为控制面网关（零任务内存态）**——claim/complete/fail/heartbeat/cancel/status/reclaim 全部代理到新增的 Python durable-state API（`apps/api/routers/durable_state.py`，`/internal/durable/*`，`X-Internal-Token` 保护，`settings.durable_state_token` 非空才挂载）。API 新增权威提交入口 `submit_job` 命令 + `POST /jobs/durable`（只写 Job/Task，不 claim 不执行）。独立 Executor 进程 `apps/executor/main.py` 注册→领取→执行 C4 handler→fencing 提交；Go Core 重启后 Executor 经 403 探测自动重注册。验收证据：
  - `tests/test_p0_closed_loop.py`：10 场景全绿（真实 skim 全链路且 attempt.executor_id=独立进程 / SIGKILL executor→lease 回收→attempt2 完成 / 迟到 complete 409 fencing / SIGKILL Core 重启恢复 / SIGKILL API 恢复 / 跨进程 pause / 协作取消无副作用 / 未注册 executor 403 / 幂等提交 / 内部 token 401）；
  - `scripts/fault_injection_local.py`：6/6 PASS（A 基线 / B 强杀 Executor / C 强杀 Core / D 强杀 API / E 协作取消 / F pause-resume），进程日志落 `data/fault-injection/`；
  - 修复过程中发现并修复 SQLite 多 Executor 并发 claim 双签 lease 竞态（`_lease_task` CAS 条件 UPDATE，`tests/test_durable_schema.py::test_concurrent_claim_single_winner`）；
  - 全程无 `global_tracker` 参与闭环（断言 attempts 的 executor 身份）。

位置：`core/main.go:19`、`core/controlplane.go:3-5`、`packages/application/commands/jobs.py:51-130`、`packages/executor_runtime/runner.py:90-107`

当前 Go Core 每次启动都构造一个新的内存 `Registry`，任务与 lease 会随进程退出全部丢失；与此同时，真实业务入口仍在 Python SQLAlchemy durable store 中创建并用 `executor_id="api-thread"` 领取 Task，然后交给进程内 `global_tracker` 执行。`ExecutorRunner` 只从 Go 内存队列 claim，仓库中也没有生产启动入口、注册流程或 worker 接线。结果是两套互不连通的 Task ID、队列和状态机：Go 重启无法从 durable store 恢复，Python 业务也根本不经过 Go Executor。

这直接违反 Stage C 出口条件“API/Executor 任意重启后可解释、可恢复”和“Go Core + Python Executor”。C3/C6/C7/C9/C11 以及“Stage C 完成”不应继续标记完成。

验收至少应包含一条真实 capability（建议 skim）的完整链路：API 只写 durable Job/Task → Go 从同一权威状态调度 → 独立 Python Executor 注册并领取 → proposal 经 fencing 提交 → 杀死并重启 API/Core/Executor 后恢复；全过程不得回落到 `global_tracker` 直接执行业务。

### [P1] Go Core 文档中的启动命令无法运行

- [x] 状态：已修复（`core/cmd/papermind-core/main.go` 独立 main package；`core/main.go`（旧 package core Run()）已删除。验证：`go build ./cmd/papermind-core` 成功且闭环测试/故障注入脚本均以该二进制起服务）

位置：`core/main.go:1-23`、`core/README.md:12-18`、`.github/workflows/tests.yml:31-50`

`core/main.go` 是 `package core`，只有 `Run()`，没有 `package main`/`func main()`。复现：

```text
$ cd core && go run .
package github.com/Color2333/PaperMind/core is not a main package
```

当前 CI 只跑 `go vet` 与 `go test`，因此测试全绿也发现不了服务不可启动。应增加独立 `cmd/papermind-core`（或等价入口）以及 build/start/health smoke test。

### [P1] Core 控制端点无认证，默认暴露到所有网卡

- [x] 状态：已修复（默认绑定 `127.0.0.1:8081`；`CORE_TOKEN` 启用 Bearer 校验（`TokenAuthMiddleware`，/health 豁免）；本轮新增 durable-state 内部 API 的第二层 `X-Internal-Token` 校验，且未配置令牌时整个内部面不挂载。部署边界（反代 HTTPS/私网）写入 `core/cmd/papermind-core/main.go` 头注释与 core/README）

位置：`core/main.go:13-23`、`core/server.go:31-42`

默认地址 `:8081` 会监听所有接口；register、submit、claim、complete、fail、cancel 等所有写端点直接挂载，没有 token、scope、executor identity 或 mTLS 校验，服务本身也只启动明文 HTTP。只要端口可达，任意客户端都能注册 Executor、领取/篡改/取消任务。路线图 C0 写的是“版本化 HTTPS API”，当前实现不满足。

在阿里云实验前，至少应默认绑定 loopback/私网，并把反向代理边界、服务凭证、executor audience/scope 与轮换方式写成可测试契约；不能只依赖“部署时别暴露 8081”。

### [P1] lease/fencing 没有验证 Executor 身份，且过期 lease 可以被续活

- [x] 状态：已修复。Python 侧：`_check_lease` 校验 executor 身份（`tests/test_lease_fencing.py::test_wrong_executor_with_valid_token_rejected`）；`heartbeat_lease` 过期不续约且过期后 complete 被拒（`test_expired_lease_cannot_heartbeat_or_complete`）；已完成 Task heartbeat ok=False（`test_heartbeat_after_completion_returns_not_ok`）。Go 侧：未注册 executor claim → 403（`TestUnregisteredExecutorForbidden`）；claim 能力与注册声明取交集（`TestClaimCapabilityIntersection`）。fencing 语义单一实现于 durable store（`_check_lease`），Go 仅透传 409（闭环测试断言迟到 complete=409）

位置：`packages/storage/repositories/durable.py:327-343`、`packages/storage/repositories/durable.py:481-489`、`core/registry.go:111-168`

Python `_check_lease()` 接收 `executor_id` 却完全不校验它；拿到 token 的其他 Executor 可以提交该 Attempt。`heartbeat_lease()` 只比较 token，不检查 Task 状态或当前租期是否已过期，因此过期 lease 在 Reconciler 扫描前可以被复活。Go 侧也允许过期 lease heartbeat/complete；此外 claim 只验证 executor 已注册，却直接相信请求里的 `wanted` capability，没有与注册能力取交集。

应补齐“错误 executor + 正确 token”“过期后 heartbeat/complete”“已完成后 heartbeat”“未注册 capability 越权 claim”四类契约测试，并让 Python/Go 使用同一套 fencing 语义。

### [P1] cancel/pause 接口对当前真实执行路径不起作用

- [x] 状态：已修复。取消：`cancel_job` 置 Job=cancelling 并保持 lease 有效，`heartbeat_lease` 探测 cancelling 返回 `cancel_requested=true`（即使 lease 已过期也传达取消意图），Executor 在安全点退出后经新增 `cancel_task_execution` 回执（Task/Attempt=cancelled，不重试不失败）；`recompute_job_status` 中 cancelling 为粘性过程态；Reconciler 回收 cancelling Job 的过期 lease 直接收敛为 cancelled。暂停：`queue_paused` 从进程内模块变量改为 `system_flags` 表持久化（新迁移 `b9c8d7e6f5a4`），任意进程 claim 前一致可见。验收自 HTTP 端点：闭环测试 `test_cancel_running_task_cooperative_exit`（取消运行中真实 handler→cancelled、论文未被 skim）、`test_pause_blocks_claims_cross_process_then_resume`（独立进程写 pause 标志→另一进程 executor 领取不到）；故障注入脚本场景 E/F 同样通过

位置：`packages/storage/repositories/durable.py:243-325`、`packages/storage/repositories/durable.py:436-489`、`apps/api/routers/jobs.py:176-189`

`cancel_job()` 对运行中 Task 只是把 lease 设为立即过期，`heartbeat_lease()` 却恒定返回 `cancel_requested=False`；当前 `global_tracker` 路径也没有协作取消检查。`pause_queue()` 只是进程内模块变量，只拦截 `claim_task()`，而真实业务入口使用不检查该变量的 `claim_task_by_id()`。因此 API 可以返回“已取消/已暂停”，任务仍可能继续执行和产生副作用。

验收应从 HTTP 端点发起：暂停后新 Job 不得执行；恢复后可继续；取消正在运行的真实 handler 后必须在安全点停止，并在 Job/Task/Attempt 中留下确定状态。跨进程状态必须持久化或由唯一控制面维护。

### [P1] 完整测试存在可复现竞态，不是稳定绿灯

- [x] 状态：已修复（external_ref 在启动执行前原子落库（`7f71034`）；本轮重复运行验证：`test_stage_c3.py + test_stage_c.py` 连续 3 次全绿；全量 pytest 234 passed + 2 skipped；并发 claim 竞态另见 P0 条目中的 CAS 修复）

位置：`packages/application/commands/jobs.py:121-130`、`tests/test_stage_c3.py:37-60`

在项目 `.venv` 中运行完整 `pytest -q`，出现 1 个失败：后台 `_wrapped` 已把 Job 收敛为 succeeded，而主线程尚未执行 `set_external_ref()`，测试读到 `pending:*`。单独重跑通过，确认这是时序竞态而非固定断言错误。当前流程先启动 tracker 线程、后回填关联 ID，本身就允许调用方在已完成状态下读到临时引用。

应在启动执行前原子确定并持久化 external reference，或彻底移除过渡 tracker ID；CI 还应增加重复/并发运行，避免一次性“212 passed”掩盖竞态。

### [P1] Worker 停机途中会把未处理完的 batch 标成 completed

- [x] 状态：已修复（`batch_consumer.poll_once` 在 `_stop.is_set()` 时的剩余任务标记为 failed 而非 completed（`7f71034`）；测试：`tests/test_stage_c.py::test_batch_consumer_not_in_api_process` 及 poll_once 系列）

位置：`packages/agent_core/batch_consumer.py:23-28`、`packages/agent_core/batch_consumer.py:47-63`、`apps/worker/main.py:321-326`

收到终止信号后 `_run_one_job()` 会在剩余 paper 前直接 break，但 `poll_once()` 随后无条件 `mark_finished(..., "completed")`。这会把未执行 paper 静默丢掉，并使“优雅关闭”产生错误完成态。停机应进入 cancelling/retryable 状态，或把未完成原子 Task 留在 durable 队列等待恢复，不能标 completed。

### [P1] Executor 吞掉 complete/fail 协议错误，可能重复副作用

- [x] 状态：已修复（`_submit_with_retry`：complete/fail 3 次指数退避重试，失败不吞——记录"执行已发生、回执未落地"并注明靠 lease 过期回收兜底（`tests/test_executor_runtime.py` 覆盖 complete/fail/cancel-execution 回执路径）；外部副作用由 C9 effect ledger（`task_effects` 表 + effect_key 唯一约束）保护）

位置：`packages/executor_runtime/runner.py:127-178`

handler 成功后，`client.complete()` 被 `suppress(Exception)` 包住。若业务副作用已发生而完成回执因网络失败/409/协议错误未落地，Executor 会静默继续；lease 到期后同一任务可能再次执行。fail/no-handler/cancel 上报也存在同类吞错。至少应记录并重试幂等提交，把“执行成功但提交结果未知”持久化为可恢复状态，且外部副作用必须由 effect key 保护。

### [P2] F6“端到端验证”只有文档声明，没有可重放证据

- [x] 状态：已澄清并补齐可重放证据（部署 profile 的 F6 验证保留为手工 smoke 记录、不用于关闭出口；P0 闭环的可重放证据由 `tests/test_p0_closed_loop.py`（多进程 pytest，每次运行重建三进程）与 `scripts/fault_injection_local.py`（可重复执行的全进程故障注入，输出 PASS 清单与进程日志）承担；路线图中已把"骨架/hermetic test"与"真实链路完成"分开表述）

位置：commit `ddc00e1`、`docs/plans/2026-09-02-rearchitecture-roadmap.md`

该 commit 只增加一行“全链路正常”的路线图文字，没有新增测试、脚本、日志或实验产物。它验证的是现有 Python 路径与部署 profile，不是 Go Core/独立 Executor/durable recovery 的端到端实验。应保留为“手工 smoke 记录”，不要用它关闭重构出口或替代用户尚未完成的实验。

### [P2] 新 Research State 页面没有正常入口，导出失败会被保存成 Markdown

- [x] 状态：已修复（Sidebar 增加 Research/JobMonitor 导航入口；`exportMd` 先检查 `response.ok` 再下载，错误不再被存成 .md（`6c5dbee` 后续修复提交）；路由可发现性由 Sidebar 集成保证）

位置：`frontend/src/App.tsx:119-122`、`frontend/src/components/Sidebar.tsx:34-47`、`frontend/src/services/api.ts:802-806`

`6c5dbee` 注册了 `/research` 路由，但没有在 Sidebar 或其他页面增加入口，普通用户只能手输 URL。`exportMd()` 又绕过公共 HTTP 错误处理，直接对任意响应调用 `text()`；404/401/500 时仍会把错误正文下载成 `.md`，也不会触发现有的 401 清理流程。应补导航入口，并在导出前检查 `response.ok`、复用统一认证/错误处理；增加路由可发现性和导出失败测试。

### 本轮独立验证

- `go test ./...`：通过。
- `go run .`：失败，`core is not a main package`。
- `.venv/bin/python -m pytest -q`：出现 1 个竞态失败、2 个 skip；单独重跑该用例通过，进一步确认 flaky。
- 系统 Python 因未安装项目声明依赖 `fastmcp` 在 collection 阶段失败；项目 `.venv` 已包含该依赖，因此未把这一点列为代码缺陷。

### 合并门槛

1. 上述 P0/P1 全部处理并附 commit 与测试证据。
2. 路线图把“已写骨架/已有 hermetic test”与“真实链路完成”拆开，撤回失真的 Stage C/F6 完成声明。
3. 先在本地跑可重复故障注入：真实任务、Core/Executor/API 分别强杀、lease 过期、重复回执、取消、pause/resume。
4. 本地结果稳定后，再由用户在阿里云运行基线与部署实验。
5. 用户确认实验结果后，才允许 merge 到 `main`；此轮明确不执行 merge/push。

---

## 修复记录（2026-09-02，重构 Agent）

- 6/6 项全部处理，处理说明已附在各条状态处。
- 验证：全量 pytest 132 passed + 2 skipped（新增 ingest 协议 3 场景 + application 架构守卫 2 项）；ruff 通过。
- wheel 重建验证：`packages/application/**` 26 个文件入包（commands/queries 子包齐全）。
- 待办（下轮复审建议）：干净虚拟环境安装 wheel 的 import smoke test；`search_arxiv` 完整响应契约断言补全；长耗时生成（wiki/gaps/survey）的 `Start* -> Job` 化在 Stage C 落地。

---

## 第三轮复审（2026-09-03）

> 审查基线：PaperMind `6d30df9`（`refactor/papermind-2026`）；PaperMind-Terminal `d334743b`，并包含当时尚未提交的 permission-profile/主题修改。
>
> 结论：**仍禁止合并到 `main`。** 第二轮发现的“双队列/内存态”问题已经消失，Go 协议链也能运行；但当前实现改变了已确认的架构决策，而且 fencing 没有保护真实领域副作用。路线图把 C6/C7/C9/C12/C13 标为完成，现状尚不足以支持这些完成声明。

### [P0] fencing 只保护任务终态，旧 Attempt 仍可提前提交领域写入

- [~] 状态：**skim 已根治（proposal 模式 + Go apply-result 单事务）**：skim Executor 纯计算不写领域表，领域提交只发生在权威面且与 fencing 校验同事务——"complete 前强杀"结构性安全（重跑只是重复计算），测试 `test_skim_proposal_mode_no_premature_domain_writes` 锁定。Python durable 路径的 skim /complete 也改为同事务 apply。domain-result 幂等卫兵保留（双保险）。**待迁移 capability**（deep_read/embed/claims）仍为直写——随逐项迁移根治。

位置：`packages/executor_runtime/runner.py:188-227`、`packages/ai/pipelines/paper_pipelines.py:423-556`、`packages/storage/repositories/durable.py:403-425`

Executor 先调用 handler，handler 内部通过 `session_scope()` 直接提交 `papers`、`analysis_reports`、`prompt_traces`、`claims/evidence` 等变化；完成之后才调用 Core 的 `/complete`。`complete_task()` 的 lease/fencing 校验只决定 Task/Attempt 能否改成 succeeded，无法撤销已经提交的领域事务。

因此存在确定的重复/迟到写场景：Attempt A 完成 skim 并提交领域表 → Core/API 短暂不可达，A 的 complete 未落地 → lease 过期后 Attempt B 重跑并再次调用 LLM/写库 → A/B 的领域变化均已发生，而 fencing 只会拒绝迟到的终态回执。当前闭环测试只覆盖“handler 前被强杀”和“迟到 complete 被拒”，没有覆盖“领域事务已提交、complete 前强杀/断网”。

这直接违反设计基线：Python Executor 只提交 proposal/Artifact，Core 校验 fencing 后再以单一事务提交领域变化与 outbox。可接受的修复方向只有两类：

1. 按既定架构让 handler 返回纯 proposal/Artifact，由 Go Core 拥有并提交领域状态；或
2. 过渡期提供一个由权威状态面执行的原子 `apply-result` 事务，在同一事务里先锁定/校验当前 Attempt，再提交领域变化、outbox 与 Task 终态。Executor 本身不得先提交领域表。

必须新增故障注入：在 handler 领域事务结束后、complete 发送前强杀 Executor/切断 Core，验证第二 Attempt 不会重复 LLM 成本、Paper/Claim/Evidence 或外部效果。

### [P0] Go Core 被实现为 Python 状态 API 的代理，与已确认架构相反

- [~] 状态：**用户已选 (a)——SkimPaper 纵向切片已落地**。Go Core 现持有权威 Job/Task/Attempt（core_jobs/core_tasks/core_attempts，modernc.org/sqlite 纯 Go 驱动，与领域表同一文件）；`POST /v1/jobs`（skim 专属）+ claim 自有优先→代理回退 + **apply-result 单事务**（fencing + analysis_reports/papers/prompt_traces + 终态）；skim Executor 纯计算 proposal。测试：Go 4 项 + 回环（领域写入由 Go 完成）+ proposal 强杀安全。**后续**：deep_read/embed/claims 等逐 capability 迁移；未迁移前其余 capability 仍经 Python durable（过渡期如实标注）。

位置：`core/registry.go:3-8`、`core/server.go:14-15`、`core/README.md:5-25`、`apps/api/routers/durable_state.py:1-21`、`docs/plans/2026-09-02-papermind-2026-rearchitecture.md:708-732`

总设计明确约定 Go Core 拥有公网 API、Research State、Job/Task/Attempt、Scheduler/Planner/Dispatcher/Reconciler、事务与 outbox，Python 只做受控计算。当前代码却明确把 Python SQLAlchemy/FastAPI 声明为唯一权威状态，Go 只保存临时 Executor 注册表并代理 `/internal/durable/*`；Reconciler 的判定逻辑也仍在 Python repository 中。

这不是实现细节，而是架构决策反转。它虽然解决了 Go 内存队列重启丢失，却没有实现用户已确认的“Go Core 权威控制面”，也没有降低核心服务对 Python/FastAPI/SQLAlchemy 的依赖。路线图 C6、C7、C9、C12 的勾选和“最终形态”描述必须撤回，除非用户明确决定改为 Python durable authority + Go gateway。

建议先做一个真正的纵向切片，而不是一次搬完全部 Python：只迁移 `SkimPaper` 的 Job/Task/Attempt 与 apply-result 到 Go，Python 仅返回结构化 skim proposal；验证完再迁下一项。

### [P1] 多论文 Workflow 的依赖被折叠到第一篇论文

- [x] 状态：已修复。TaskSpec.depends_on 改用 **logical node key（= idempotency_key）**解析（expand 期 node→task id 映射）；模板逐 paper 生成精确边（upsert→download→skim→claims，upsert→embed）；测试重写为按 idempotency_key 逐 paper 断言精确边（不再用 capability 做 dict key）。

位置：`packages/application/commands/workflows.py:78-133`、`packages/application/commands/workflows.py:266-287`、`tests/test_workflows.py:52-61`

`expand_job()` 用 `capability -> task id` 的单值字典解析依赖，并通过 `setdefault()` 保留第一个同名 Task。两篇论文各自产生 `upsert/download/skim/embed/extract` 时，第二篇的 download 会依赖第一篇的 upsert，第二篇的 skim 会依赖第一篇的 download；per-Paper DAG 已经串错。

现有测试又用 capability 做 dict key，把多个 skim 覆盖成一个，并且只断言依赖属于“任意 download id”，所以没有发现错配。依赖必须使用稳定的 logical node key（如 `paper:{id}:download`）或直接在 TaskSpec 中引用前驱 TaskSpec，不得用非唯一 capability 名解析；测试要逐 paper 断言精确边。

### [P1] 两个已登记的 Workflow Task 无法按当前输入契约执行

- [~] 状态：**主体已修复**。upsert_paper → `task_handlers.upsert_paper_data`（arxiv_id/title/abstract，返回 paper_id 供下游绑定）；download_source → `download_source_data`（arxiv_id）；send_brief_email → `send_brief_email_effect`（recipient/subject/content_id，effect ledger 接入）；**输出绑定语义**已定义：input_ref 支持 `${node:field}` 占位符，expand 期从上游 result_ref 解析（未就绪则本轮不创建，下一轮补）。RunTopicResearch 两篇 + BuildDailyBrief→send 的独立 Executor 端到端测试待补（当前覆盖 expand/绑定/传播单测）。

位置：`packages/application/commands/workflows.py:68-95`、`packages/application/commands/workflows.py:173-205`、`packages/application/commands/task_registry.py:51-70`、`packages/application/commands/task_registry.py:141-163`、`packages/executor_runtime/runner.py:298-373`

当前 Workflow 测试只验证“行被展开”，没有让独立 Executor 真正执行整张图：

- `upsert_paper` 的 handler 是 `PaperRepository.upsert_paper(self, data: PaperCreate)`，但 Workflow 只传 `{"paper_id": pid}`；repository 又需要 Session，通用 `_adapt()` 无法绑定或构造 `PaperCreate`。
- `download_source` 声明需要 `paper_id + arxiv_id`，Workflow 只传 `paper_id`。
- `send_brief_email` 实际签名需要 `recipient, subject, html`，Workflow 只传 `recipient`，也没有把上游 `build_daily_brief` 的输出/Artifact 绑定到下游输入。
- `fetch_feed` 的结果没有驱动第二轮 planner fan-out；没有预置 `paper_ids` 时只会完成 fetch，不会继续 upsert/download/skim。

应为 Workflow 增加真实 Executor 端到端测试，至少覆盖 `RunTopicResearch` 两篇论文与 `BuildDailyBrief -> send`，并定义上游 Artifact/result 到下游 `input_ref` 的持久绑定语义。

### [P1] 上游 Task 失败后，下游永久 queued，Job 无法收敛

- [x] 状态：已修复。`skip_blocked_tasks()`：前驱终态失败 → 下游 queued 标 cancelled（last_error 注明 skipped）+ recompute 收敛；接入 run_reconcile（对所有 Job 生效）。测试 `test_upstream_failure_propagates_and_job_converges`：1 篇成功 + 1 篇 dead_letter 链 → partially_succeeded 确定收敛、无遗留 queued。

位置：`packages/storage/repositories/durable.py:136-176`、`packages/storage/repositories/durable.py:319-362`、`packages/storage/repositories/durable.py:460-510`

claim 只允许全部依赖 succeeded 的 Task；若 download/build 等前驱进入 dead_letter，下游仍保持 queued。`recompute_job_status()` 把这些 queued Task 计为 active，于是 Job 永远 running；Reconciler 只处理过期 lease，也不会把“依赖已终止且不可成功”的 Task 标为 skipped/cancelled/failed。

这使路线图宣称的 `partially_succeeded` 与 `continue_on_failure` 在真实 DAG 中不可达。需要显式的 blocked/skipped 传播规则，并测试“某一篇前驱失败、其他篇成功”后整个 Job 能确定收敛且可解释。

### [P1] effect ledger 只存在于测试示例，生产发送路径未接入

- [~] 状态：**发送路径已接入**：`task_handlers.send_brief_email_effect` 是唯一邮件发送 handler（先查 has_effect → 发送 → register_effect；发送异常不登记 → manual_recovery 由人工重放，重放时账本挡重复）。"先登记后发送崩溃漏发"窗口已用 manual_recovery 语义覆盖。**待补**：provider idempotency key（SMTP 无原生支持，属部署侧改进）；AutoReadService 的直发路径审计。

位置：`packages/application/commands/effect_ledger.py:22-52`、`tests/test_effect_ledger.py:34-51`、`packages/ai/task_handlers.py:93-112`、`packages/integrations/notifier.py:16-35`

生产代码中没有任何 `register_effect()` / `has_effect()` 调用；唯一的“邮件去重集成”测试是在测试函数里手写 `if has_effect: continue`，并未调用真实 `send_brief_email`/`AutoReadService`/`NotificationService` handler。路线图与 REVIEW 第二轮声称“外部副作用由 C9 ledger 保护”目前不成立。

尤其是人工 retry 一个已发出邮件但回执丢失的 dead-letter Task 时，邮件会再次发送。账本必须在真实发送 adapter 中接入，并解决“先登记后发送崩溃会漏发、先发送后登记崩溃会重发”的不确定窗口；优先使用 provider idempotency key，否则状态至少要有 prepared/sent/unknown/manual-recovery，而不是单个已提交行。

### [P1] C13 的精简出口未完成：新批处理仍双写 `batch_jobs` 与 durable Job

- [x] 状态：已修复。`create_batch_job` 直接创建 durable ProcessUnreadBatch 并返回 **durable job id**（不再写 batch_jobs 行）；get_batch_job 支持新（durable id 直查）与旧（只读迁移投影）两种 id；`get_batch_job_legacy_row` 为显式迁移适配器。I1 守卫新增 `test_batch_jobs_no_new_writes`（生产代码禁止创建 batch_jobs 行）。删除条件已记录（agent 工具 id 全切换后删表）。

位置：`packages/application/commands/batch.py:1-42`、`packages/application/commands/batch.py:45-90`、`packages/storage/models.py:682`、`packages/storage/db.py:349-350`

`create_batch_job()` 每次先创建旧 `batch_jobs` 行，再创建 durable `ProcessUnreadBatch` Job；查询还必须先找到旧行，才能投影 durable graph。旧 repository/model/runtime 建表和生产 handler 全部仍在使用。这不是只读历史兼容层，而是持续双写的新路径。

用户已经把“精简”设为重构完成条件，因此 C13/I1 不能只以“consumer 文件删除”为验收。新请求应直接返回 durable job id；历史 `batch_jobs` 只允许只读迁移 adapter，并应有删除日期/迁移脚本。Stage I 守卫需增加生产代码不得创建 `BatchJobRepository` 的断言。

### [P1] 默认 Compose 会启动一个无认证且假健康的 Core

- [x] 状态：已修复。Core main fail-closed：缺 CORE_TOKEN/STATE_TOKEN 任一拒绝启动（ALLOW_INSECURE_CORE=1 仅限本地实验显式覆盖）；compose 用 `${CORE_TOKEN:?required}` 语法强制；**liveness/readiness 分离**：/health（进程存活，附 state_ready 字段）与 /readyz（探测 durable-state，不可达 503）分离，compose healthcheck 改用 /readyz，worker depends_on core healthy。

位置：`docker-compose.yml:17-38`、`core/cmd/papermind-core/main.go:30-60`、`core/server.go:90-98`、`.env.example:129-133`

Compose 把 Core 绑定到 `0.0.0.0:8081`，但 `CORE_TOKEN` 与 `DURABLE_STATE_TOKEN` 都默认空；Core 在 token 为空时完全不安装认证中间件。与此同时 `/health` 不探测 state API，所以 durable token 为空、Python 内部路由未挂载或 backend 已故障时，Core 仍返回 `status=ok`，worker 也会按 `service_started` 启动并不断领取失败。

生产 profile 应 fail closed：Core/worker/executor 缺任一服务令牌直接拒绝启动；readiness 必须探测 durable state（可另保留只表示进程存活的 liveness）。即使 8081 没有映射到宿主机，无认证控制面也不应对整个容器网络开放。

### [P1] Core cancel 信任 payload 的 Task ID，而不是 URL 资源 ID

- [x] 状态：已修复。handleCancel 以 URL path id 为唯一资源标识；payload task_id 与 path 不一致返回 400（task_id_mismatch）。测试 TestCancelPathPayloadMismatchRejected 覆盖 A/B 冲突场景。

位置：`core/server.go:301-323`、`core/server_test.go:390-410`

请求 `POST /v1/tasks/A/cancel` 携带 `{"task_id":"B"}` 时，handler 实际取消 B。其他 task 操作都使用 path id，cancel 是例外；现有测试只发送相同的 A/A，未覆盖冲突。应以 path id 为唯一资源标识，并在 payload 仍保留 task_id 时要求二者相等，否则 400。

### [P1] Terminal permission-profile 修改当前有真实失败，并会挂住测试进程

- [x] 状态：已修复（后续两个 commit：3f674a0/660510f1 已入库）。说明：审查基于 d334743b 时点的未提交工作区；随后 (1) `--coding` 已传入 runPmOneshot；(2) 测试资源改 try/finally 清理；(3) 语义已与用户对齐——**用户明确要求默认 profile 保留查看/修改（写论文）能力**，故 research profile 含工作区文件工具（read/edit/write/grep/find/ls），bash/powershell 零构造；此为对设计④ §6 的用户批准修订，已回写设计文档。npm test 15/15。

位置：`packages/papermind-cli/src/agent/session.js:78-134`、`packages/papermind-cli/bin/pm.js:13-37`、`packages/papermind-cli/test/agent-loop.test.js:170-236`

未提交修改新增了 `workspaceFileTools()` 和 `codingTools` 参数，但 runtime 仍无条件传 `baseToolsOverride: {}`，两个值均未参与工具构造；`pm --coding -p ...` 还没有把 `codingTools` 传给 `runPmOneshot()`。测试却把默认 profile 的期望改成 6 个 workspace 工具，因此外部运行时得到空 Map 并失败。

此外该测试在 assertion 失败后到不了末尾的 `pmServer.close()/llmServer.close()`，Node 进程保持两个监听 socket 而挂起。测试资源必须使用 `t.after()` 或 `try/finally` 清理。实现前还要先统一语义：设计④定义默认 research=PM tools、`--workspace` 才增加文件读写、`--coding` 才恢复完整工具；测试不应把 6 个工作区写工具放进默认 profile。

### [P2] Terminal 的主题加载依赖 monorepo 私有 `dist` 路径

- [~] 状态：**已改为稳定 export**：coding-agent package.json 新增 `./theme-loader` 子路径导出（dist theme.js），pm 经 `@earendil-works/pi-coding-agent/theme-loader` 加载——不再依赖相对 dist 路径。tarball/standalone 安装验证待 release 流水线（E2 后续）实施。

位置：`packages/papermind-cli/src/agent/session.js:31-38`

`@papermind/cli` 通过 `../../../coding-agent/dist/.../theme.js` 动态导入没有从包 exports 暴露的内部文件。源码树/已构建 monorepo 中可以工作，但 npm 包或 standalone 重排目录后会失效；因此 E6 只能算开发态接通，不能据此判定可独立发布。应增加稳定公开 export，或在发布流水线把 loader 与主题显式 bundle，并用实际 tarball/standalone 安装测试验证。

### [P2] 路线图存在互相冲突的完成状态与证据

- [~] 状态：**主体已修复**：C6/C7/C9/C12/C13 完成声明撤回为 `[~]` 待定状态（附具体缺什么）；E2c/E6 表述修正（"零上游源码改动"改为"零上游源码改动 + patch 0001 产品层透传"，E6 主题已独立成条）；E1 标注为"本地 downstream 工作树（origin 仍指 Pi upstream，待用户建 fork/push）"。建议的四态标记（implemented/locally verified/experiment verified/released）待下一版路线图重构统一引入。

位置：`docs/plans/2026-09-02-rearchitecture-roadmap.md:124-161`、`docs/plans/2026-09-02-rearchitecture-roadmap.md:191-225`

- C9 已勾选，但同一条遗留又承认“Go 侧直接写领域表”尚未完成。
- C7 写“Executor 不直写 Research State 表”，真实 handler 却直接写。
- E2c+E6 已勾选，而原 E6 仍未勾选；文档同时声称“零上游源码改动”和存在 `patch 0001` 修改 `coding-agent` 源码。
- E1 写“独立仓库”，但 Terminal 的 `origin` 仍是 Pi upstream；在用户建立并 push 自己的 fork 前，只能标记为本地 downstream 工作树。

路线图应区分 `implemented`、`locally verified`、`experiment verified`、`released`，并以退出门而不是提交信息中的历史通过数字作为当前状态。

### 本轮独立验证

- PaperMind `go test ./...`：通过。
- PaperMind 完整 Python suite：沙箱内运行没有出现断言失败，但 12 个依赖本地监听 socket 的用例因环境 `EPERM` 报错；请求在允许本地监听的环境重跑时未获授权，因此本轮**不能独立确认**“全量 285 passed”。这不是把 EPERM 判成代码缺陷，而是明确证据缺口。
- PaperMind-Terminal 定向 `node --test packages/papermind-cli/test/contract.test.js packages/papermind-cli/test/agent-loop.test.js`：沙箱内 9 pass、7 个监听权限失败；获准在外部重跑后，第一个 AI 全链路用例通过，第二个 patch/profile 用例因期望 6 个工具、实际 0 个失败，随后因 server 未清理而挂起，已人工中断。
- 未运行 Terminal 全量 `npm test`/build：遵守该仓库 `AGENTS.md` 对 review 的限制，只运行了与改动直接相关的 `node --test`。
- 未执行 merge、push、部署或服务器实验。

### 第三轮合并门槛（按顺序）

1. 用户确认继续坚持既定 **Go authority + Python compute-only Executor**；若坚持，先撤回 C6/C7/C9/C12/C13 完成状态并完成一个真正的 Skim 纵向切片。
2. 把 fencing 校验与 Paper/Claim/Evidence/outbox 的领域提交放入同一个权威事务，补“handler 后、complete 前”强杀实验。
3. 修复 Workflow 的 per-Paper 依赖标识、输出绑定、失败传播，并让独立 Executor 真正跑完两类 Workflow。
4. 把 effect ledger 接入真实外部发送路径；停止新写 `batch_jobs`，完成精简退出门。
5. Core 配置 fail closed，拆分 liveness/readiness，修 cancel path/payload 一致性。
6. 完成 Terminal 的 research/workspace/coding 三档语义，修复失败测试的资源清理，并以 npm tarball/standalone 验证主题加载。
7. 上述完成后重新跑全量 Python、Go、Terminal 定向/构建测试，再做本地故障注入；用户实际实验确认后才 merge `main`。
