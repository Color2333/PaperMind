"""application 层——唯一能力入口（设计文档 §5.1，设计②用例目录）

层约定（B1 起生效，逐步收敛）：

1. commands/ 与 queries/ 是全部业务用例的唯一实现位置；HTTP router、MCP tool、
   CLI command、Pi tool 只做「解析输入与鉴权 → 调用 application → 转换协议」。
2. query = 接收 session 的纯读函数，返回 plain dict（canonical result）；
   command = 接收 session 的写函数（含触发长任务的 Start*——B7 起只创建 Job）。
3. repository / domain service / provider 只允许在本层及其下层使用；
   上层（routers/mcp/cli）禁止直接 import 具体服务单例。
4. 返回结构对外兼容优先：下沉存量逻辑时逐字段保持原 HTTP 响应形状。
5. 领域变更与 research_events 同事务提交（设计① outbox 规则）。

现有覆盖：queries/research_state.py、queries/research_export.py（D4/D5）、
queries/papers.py（B2）；commands 待 B7 按设计②映射逐批落位。
"""
