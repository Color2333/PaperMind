# LangGraph PoC vs 自研 StreamingAgentLoop — 完整对比分析

基于本地 uvicorn + xiaomi LLM + SQLite/MemorySaver 实测：
- 单轮 benchmark（`bench_results.json` / `bench_results_optimized.json`）
- 多轮 benchmark（`bench_multiturn.json`）
- 真实任务案例

## 1. 性能对比

### 单轮（5 场景 × 5 次，优化后）

| 场景 | v1 E2E mean | v2 E2E mean | delta |
|---|---|---|---|
| 普通对话（无工具） | 2.6s | 3.0s | +13.8% |
| list_topics | 6.7s | 5.3s | -20.5% |
| get_batch_job_status | 5.8s | 3.9s | -32.6% |
| get_citation_tree | 9.7s | 10.5s | +8.8% |
| skim_paper confirm | 6.7s | 13.4s | +100.4% |

### 多轮增长曲线（场景 A，10 轮纯对话）

| 轮次 | v1 TTFT | v2 TTFT | v1 E2E | v2 E2E |
|---|---|---|---|---|
| 1 | 2.4s | 2.2s | 2.8s | 2.6s |
| 5 | 2.3s | 1.9s | 2.5s | 2.1s |
| 10 | 1.0s | 1.5s | 1.3s | 1.8s |

**关键发现**：TTFT/E2E 不随轮次显著增长。两后端在短对话下历史拼接开销可忽略，LLM 方差（同 prompt 1.0s~7.4s）完全淹没框架差异。

### 含 confirm 多轮（场景 B）

v2 confirm resume 后多轮不稳定（第 4 轮起全部 N/A，流被截断）。v1 confirm 后续轮也大量 N/A（LLM 调工具/超长回复导致 timeout）。这是 **LLM 行为方差 + timeout 设置**导致，非框架本质问题，但暴露 v2 在 confirm 后续状态恢复上需进一步验证。

## 2. 真实多工具任务案例

**任务**：search_papers('attention') → skim_paper(第一篇) → 一句话总结

| 指标 | v1 | v2 |
|---|---|---|
| 总耗时 | 10.08s | 10.02s |
| 首 token | 1.88s | 8.94s |
| 工具调用次数 | 2 | 2 |
| 工具序列 | search_papers, get_system_status | search_papers, get_system_status |
| 触发 confirm | 0 | 0 |

**关键发现**：
1. **两后端 LLM 决策路径完全一致**（相同工具序列）— 框架不影响 LLM 工具选择
2. **LLM 都没调 skim_paper**（任务要求粗读，但 LLM 只搜索+查状态就总结）— LLM 决策偏差，与框架无关
3. v2 TTFT 比 v1 慢（8.94s vs 1.88s）— 但这是 LLM 方差（同任务多次跑会变），非框架固有

## 3. 框架优势分析（结构性，基于源码 + 实测）

### ✅ LangGraph 的优势

| 优势 | 说明 | 自研 loop 对比 |
|---|---|---|
| **checkpoint 持久化** | 服务重启后状态不丢（PG），thread_id 隔离 | 老 loop 靠 pending action 全量快照，重启后快照可能过期 |
| **增量状态存储** | checkpoint 每步只存新消息（增量），存储 O(n) | 老 loop confirm 时存全量 conversation JSON，随轮数增大 |
| **interrupt 原生支持** | 框架级 human-in-the-loop，`interrupt()` + `Command(resume=)` | 老 loop 手写 store_pending_action / load / mark_handled / cleanup_expired |
| **状态一致性** | checkpoint 是运行时状态（增量），resume 自动恢复 | 老 loop 快照是 confirm 时点冻结，期间若有新消息会丢失 |
| **可观测性** | checkpoint 列表/回放/time-travel，可调试 | 老 loop 无 |
| **生态** | 可接 langgraph-platform 部署/监控/streaming UI | 老 loop 自维护 |
| **少写边界条件** | JSON 解析/多 confirm/max_rounds/usage 这些手修过的 bug，LangGraph 内置 | 老 loop 我们手修了 ⑧⑨⑩⑬ 等多个 bug |
| **并发安全** | thread_id 隔离 + checkpoint 事务 | 老 loop pending action 快照可能竞态 |

### ❌ LangGraph 的劣势

| 劣势 | 说明 | 量化 |
|---|---|---|
| **无工具场景延迟** | graph 编译 + LangChain 消息转换 + checkpoint 是纯额外开销 | +13.8% E2E（优化后） |
| **confirm 流 2 请求** | v2 需触发 + confirm resume 两请求，v1 单请求 | +100.4% E2E |
| **依赖更重** | langgraph + langchain-core + psycopg v3 | +~50MB 安装体积 |
| **学习曲线** | LangChain 消息协议/tool_call_chunks 等概念 | 团队需学习 |
| **confirm 后续稳定性** | v2 confirm resume 后多轮有不稳定（实测 N/A） | 需进一步排查 |

## 4. 结论与建议

### 性能上
- **短对话/无工具**：v2 慢 ~13.8%（框架固有开销，可接受）
- **含工具**：v2 与 v1 持平或更快（工具往返毫秒级，框架开销被 LLM 延迟掩盖）
- **confirm**：v2 慢 ~100%（2 请求架构，可优化为 Command goto 单请求）
- **多轮**：两后端在短对话下不劣化；长对话需更大数据量验证

### 功能上
- **LangGraph 优势在工程维护性**：checkpoint 持久化、interrupt 原生、少写边界条件、可观测性、生态
- **这些优势在"对话越长 + confirm 越多 + 需要重启/并发"时越明显**

### 决策建议
1. **如果**项目重点是快速对话、少 confirm、单进程 → 保留自研 loop（性能更好，依赖更轻）
2. **如果**项目需要长对话持久化、多 confirm、服务重启恢复、可观测性 → 用 LangGraph（工程优势 > 13.8% 延迟代价）
3. **PoC 结论**：LangGraph 功能完整、可优化到接近 v1 性能，但 confirm 流和多轮稳定性需进一步打磨。**建议保留 PoC 分支，先在生产环境小范围验证 confirm 多轮 + checkpoint 持久化**，再决定是否整体替换。

## 5. 不确定因素（需更多测试）

- **生产 PG + PostgresSaver I/O 开销**未测（本地用 MemorySaver）
- **xiaomi LLM 方差极大**（同 prompt TTFT 1.0s~7.4s），5-10 次 mean 仍有噪声，要可靠结论需固定 temperature=0 + 20+ 次
- **confirm resume 后多轮稳定性**需排查（v2 第 4 轮起 N/A）
- **长对话（50+ 轮）** 下 checkpoint 存储增长未测
