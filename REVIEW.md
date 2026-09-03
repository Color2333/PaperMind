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

- [ ] 状态：待修复

位置：`core/main.go:19`、`core/controlplane.go:3-5`、`packages/application/commands/jobs.py:51-130`、`packages/executor_runtime/runner.py:90-107`

当前 Go Core 每次启动都构造一个新的内存 `Registry`，任务与 lease 会随进程退出全部丢失；与此同时，真实业务入口仍在 Python SQLAlchemy durable store 中创建并用 `executor_id="api-thread"` 领取 Task，然后交给进程内 `global_tracker` 执行。`ExecutorRunner` 只从 Go 内存队列 claim，仓库中也没有生产启动入口、注册流程或 worker 接线。结果是两套互不连通的 Task ID、队列和状态机：Go 重启无法从 durable store 恢复，Python 业务也根本不经过 Go Executor。

这直接违反 Stage C 出口条件“API/Executor 任意重启后可解释、可恢复”和“Go Core + Python Executor”。C3/C6/C7/C9/C11 以及“Stage C 完成”不应继续标记完成。

验收至少应包含一条真实 capability（建议 skim）的完整链路：API 只写 durable Job/Task → Go 从同一权威状态调度 → 独立 Python Executor 注册并领取 → proposal 经 fencing 提交 → 杀死并重启 API/Core/Executor 后恢复；全过程不得回落到 `global_tracker` 直接执行业务。

### [P1] Go Core 文档中的启动命令无法运行

- [ ] 状态：待修复

位置：`core/main.go:1-23`、`core/README.md:12-18`、`.github/workflows/tests.yml:31-50`

`core/main.go` 是 `package core`，只有 `Run()`，没有 `package main`/`func main()`。复现：

```text
$ cd core && go run .
package github.com/Color2333/PaperMind/core is not a main package
```

当前 CI 只跑 `go vet` 与 `go test`，因此测试全绿也发现不了服务不可启动。应增加独立 `cmd/papermind-core`（或等价入口）以及 build/start/health smoke test。

### [P1] Core 控制端点无认证，默认暴露到所有网卡

- [ ] 状态：待修复

位置：`core/main.go:13-23`、`core/server.go:31-42`

默认地址 `:8081` 会监听所有接口；register、submit、claim、complete、fail、cancel 等所有写端点直接挂载，没有 token、scope、executor identity 或 mTLS 校验，服务本身也只启动明文 HTTP。只要端口可达，任意客户端都能注册 Executor、领取/篡改/取消任务。路线图 C0 写的是“版本化 HTTPS API”，当前实现不满足。

在阿里云实验前，至少应默认绑定 loopback/私网，并把反向代理边界、服务凭证、executor audience/scope 与轮换方式写成可测试契约；不能只依赖“部署时别暴露 8081”。

### [P1] lease/fencing 没有验证 Executor 身份，且过期 lease 可以被续活

- [ ] 状态：待修复

位置：`packages/storage/repositories/durable.py:327-343`、`packages/storage/repositories/durable.py:481-489`、`core/registry.go:111-168`

Python `_check_lease()` 接收 `executor_id` 却完全不校验它；拿到 token 的其他 Executor 可以提交该 Attempt。`heartbeat_lease()` 只比较 token，不检查 Task 状态或当前租期是否已过期，因此过期 lease 在 Reconciler 扫描前可以被复活。Go 侧也允许过期 lease heartbeat/complete；此外 claim 只验证 executor 已注册，却直接相信请求里的 `wanted` capability，没有与注册能力取交集。

应补齐“错误 executor + 正确 token”“过期后 heartbeat/complete”“已完成后 heartbeat”“未注册 capability 越权 claim”四类契约测试，并让 Python/Go 使用同一套 fencing 语义。

### [P1] cancel/pause 接口对当前真实执行路径不起作用

- [ ] 状态：待修复

位置：`packages/storage/repositories/durable.py:243-325`、`packages/storage/repositories/durable.py:436-489`、`apps/api/routers/jobs.py:176-189`

`cancel_job()` 对运行中 Task 只是把 lease 设为立即过期，`heartbeat_lease()` 却恒定返回 `cancel_requested=False`；当前 `global_tracker` 路径也没有协作取消检查。`pause_queue()` 只是进程内模块变量，只拦截 `claim_task()`，而真实业务入口使用不检查该变量的 `claim_task_by_id()`。因此 API 可以返回“已取消/已暂停”，任务仍可能继续执行和产生副作用。

验收应从 HTTP 端点发起：暂停后新 Job 不得执行；恢复后可继续；取消正在运行的真实 handler 后必须在安全点停止，并在 Job/Task/Attempt 中留下确定状态。跨进程状态必须持久化或由唯一控制面维护。

### [P1] 完整测试存在可复现竞态，不是稳定绿灯

- [ ] 状态：待修复

位置：`packages/application/commands/jobs.py:121-130`、`tests/test_stage_c3.py:37-60`

在项目 `.venv` 中运行完整 `pytest -q`，出现 1 个失败：后台 `_wrapped` 已把 Job 收敛为 succeeded，而主线程尚未执行 `set_external_ref()`，测试读到 `pending:*`。单独重跑通过，确认这是时序竞态而非固定断言错误。当前流程先启动 tracker 线程、后回填关联 ID，本身就允许调用方在已完成状态下读到临时引用。

应在启动执行前原子确定并持久化 external reference，或彻底移除过渡 tracker ID；CI 还应增加重复/并发运行，避免一次性“212 passed”掩盖竞态。

### [P1] Worker 停机途中会把未处理完的 batch 标成 completed

- [ ] 状态：待修复

位置：`packages/agent_core/batch_consumer.py:23-28`、`packages/agent_core/batch_consumer.py:47-63`、`apps/worker/main.py:321-326`

收到终止信号后 `_run_one_job()` 会在剩余 paper 前直接 break，但 `poll_once()` 随后无条件 `mark_finished(..., "completed")`。这会把未执行 paper 静默丢掉，并使“优雅关闭”产生错误完成态。停机应进入 cancelling/retryable 状态，或把未完成原子 Task 留在 durable 队列等待恢复，不能标 completed。

### [P1] Executor 吞掉 complete/fail 协议错误，可能重复副作用

- [ ] 状态：待修复

位置：`packages/executor_runtime/runner.py:127-178`

handler 成功后，`client.complete()` 被 `suppress(Exception)` 包住。若业务副作用已发生而完成回执因网络失败/409/协议错误未落地，Executor 会静默继续；lease 到期后同一任务可能再次执行。fail/no-handler/cancel 上报也存在同类吞错。至少应记录并重试幂等提交，把“执行成功但提交结果未知”持久化为可恢复状态，且外部副作用必须由 effect key 保护。

### [P2] F6“端到端验证”只有文档声明，没有可重放证据

- [ ] 状态：待澄清

位置：commit `ddc00e1`、`docs/plans/2026-09-02-rearchitecture-roadmap.md`

该 commit 只增加一行“全链路正常”的路线图文字，没有新增测试、脚本、日志或实验产物。它验证的是现有 Python 路径与部署 profile，不是 Go Core/独立 Executor/durable recovery 的端到端实验。应保留为“手工 smoke 记录”，不要用它关闭重构出口或替代用户尚未完成的实验。

### [P2] 新 Research State 页面没有正常入口，导出失败会被保存成 Markdown

- [ ] 状态：待修复

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
