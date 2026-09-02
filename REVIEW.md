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

## 修复记录（2026-09-02，重构 Agent）

- 6/6 项全部处理，处理说明已附在各条状态处。
- 验证：全量 pytest 132 passed + 2 skipped（新增 ingest 协议 3 场景 + application 架构守卫 2 项）；ruff 通过。
- wheel 重建验证：`packages/application/**` 26 个文件入包（commands/queries 子包齐全）。
- 待办（下轮复审建议）：干净虚拟环境安装 wheel 的 import smoke test；`search_arxiv` 完整响应契约断言补全；长耗时生成（wiki/gaps/survey）的 `Start* -> Job` 化在 Stage C 落地。
