"""application 层——唯一能力入口（设计文档 §5.1）

Stage B 会把 commands/queries 逐步收敛到这里；HTTP router、MCP tool、CLI command
只做协议转换，不得直接组合 repository 与模型 SDK。
"""
