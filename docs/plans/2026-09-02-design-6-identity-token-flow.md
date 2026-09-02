# 设计⑥：HTTPS identity/token flow

状态：**待确认**（重构路线图 A10；六份设计之第六份）

日期：2026-09-02

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md) §3.2（MCP OAuth）、§6.3（Demo 登录与授权）、§10（token 风险项）；现状：`packages/auth.py` + `apps/api/token_auth.py` + `/auth/device/*`（已实现并有 73–319 行测试覆盖）。

范围：三个信任域的凭据模型、scope 体系、GitHub Web 登录（Demo）、CLI device authorization 规范、MCP OAuth discovery、Local UI session 边界。出口条件：能直接指导 E3/E8–E10 与 G2。

## 1. 现有资产（不重做，只扩展）

| 资产 | 现状 | 差距 |
| --- | --- | --- |
| 网页 JWT 会话 | `/auth/login` 密码换 JWT（7 天），AuthMiddleware 全局校验 | Demo 需要 GitHub 登录路径（G2） |
| 个人 API token | `pmt_` 前缀、DB 哈希存储、可撤销；scope 二值 `read`/`write`（按 HTTP 方法强制） | scope 粒度不足（设计文档要求分 scope 凭据，E8/E9） |
| CLI 设备码流 | `/auth/device/start|poll|{user_code}|authorize|deny` + `device_auth_requests` 表 | 已符合"CLI 只信任 PaperMind"原则；补轮询限速与审计 |
| Demo 限流 | `DemoModeMiddleware` + IP/全局限额（有测试） | 用户维度限额与 TTL 清理（G2） |

## 2. 三个信任域（严格分离）

| 信任域 | 凭据 | 存储位置 | 撤销 |
| --- | --- | --- | --- |
| **PaperMind 访问** | 网页 JWT / 个人 API token / Demo session token / MCP token | 服务端 DB（哈希）+ 客户端 keyring/config | 服务端撤销（tokens 端点已具备） |
| **模型 provider** | OpenAI/Anthropic/Zhipu 等本地推理凭据 | 本地 Pi 自己的凭据存储 | provider 侧；PaperMind 永不接收 |
| **上游身份** | GitHub OAuth token（仅登录瞬间） | 只在服务端内存中使用后即弃，不落库、不下发 CLI/MCP | 无需（即弃） |

硬规则：上游身份 token 不作为 PaperMind token 使用、不传给 MCP、不进 CLI；PaperMind 只保存 `provider`、`provider_subject`、创建时间、TTL 最小映射。

## 3. Scope 模型（E8/E9 升级）

现二值 `read`/`write` 升级为四值（旧 token 迁移映射：read→research:read，write→research:read+jobs:control）：

```text
research:read    查询论文/问题/Claim/证据/diff/导出
research:write   导入、Claim 确认/修订、订阅与设置写
jobs:control     任务提交/取消/重试/队列 pause/resume
admin            token 管理、executor 运维、设置面
```

- HTTP 方法默认映射保留（GET→research:read，其余→按 capability metadata 的 `required_scope`，设计④ §6——capability 成为 scope 的权威来源，替代"按方法猜"）。
- Demo session token：scope 固定 `research:read + research:write(限额内)`，**无 jobs:control、无 admin**；TTL 到期由清理任务删除数据（G2）。
- MCP token：个人实例默认 `research:read + research:write`，可创建只读 token 给外部 agent。
- token 响应与文档不再展示完整 token（仅前缀）；创建时一次性展示。

## 4. CLI device authorization（E10，规范固化）

现有流保持，补齐规范细节：

1. `pm login --endpoint` → `POST /auth/device/start`（device_code 哈希存储、user_code 9 位、TTL 10 分钟）。
2. CLI 打开 `https://<domain>/device/{user_code}`；用户在网页完成身份确认（个人实例：密码会话；Demo：GitHub 登录后确认）。
3. CLI 轮询 `POST /auth/device/poll`：**限速 ≥5s/次**、指数退避；`pending/slow_down/denied/expired/approved` 五态。
4. approve 后签发 PaperMind token（短期、限 scope、可撤销）；**user_code 一次性**、deny 即终止。
5. CLI 侧存储：token 进系统 keyring（回退 0600 配置文件）；`pm logout` 调撤销端点后清本地。

## 5. GitHub Web 登录（G2，Demo 第一 provider）

```text
浏览器 → /auth/github/start → GitHub authorize（scope=read:user 最小）
      → callback /auth/github/callback
      → 服务端换 user 身份 → 校验 → 保存最小映射（provider/subject/created_at/demo_ttl）
      → 丢弃 GitHub token → 签发 PaperMind demo session token
      → 页面展示 pm login/pm demo/pm ui 引导 + 临时空间限额说明
```

- 只请求确认身份所需最小权限（不请求 repo/email scopes）。
- `identity` 表：`(provider, provider_subject)` 唯一；Demo TTL 到期删除临时空间数据，预置公共语料不受影响。
- 微信作为第二 provider：统一 identity adapter（`start/callback/verify` 三方法），接入条件需在微信开放平台实施前复核（设计文档 §6.3）。
- GitHub 客户端 secret 仅存服务端环境；个人实例可完全不用 GitHub（密码会话已够）。

## 6. MCP OAuth protected resource（E7/E8）

- 远程 MCP endpoint 暴露 `/.well-known/oauth-protected-resource`，声明 authorization_servers 与 scopes_supported；个人实例第一版 authorization server 即 PaperMind 自身（密码登录换 token），不强制引入外部 IdP。
- token 校验增加 audience（`aud=papermind-mcp`）与 scope 断言；Origin 校验保持（规范要求）。
- 迁移路径：现有静态个人 token → E8 可撤销/轮换/分 scope（DB 管理，tokens 端点扩展 scope 字段即达成）。
- MCP Tasks 仅 adapter 层转换，内部 Job schema 自主（设计文档 §10）。

## 7. Local UI session 边界（F3）

- bridge 进程内持有 PaperMind token（keyring 读取），浏览器侧只有一次性 nonce → 短期 cookie；token 不进 localStorage/URL/日志。
- cookie 与 bridge 进程生命周期绑定：`pm ui` 退出即失效；重新启动需重新 nonce。
- Local UI 不出现任何"记住登录"持久凭据；长期凭据只有 CLI keyring 里的那份。

## 8. Token 安全规则（汇总，进验收清单）

1. 不出现在 URL query（nonce 除外且一次性）、日志、终端历史、错误消息。
2. 短期 + 可撤销 + 可轮换；API token 展示一次。
3. 日志脱敏：bearer/Authorization 头、device_code、client secret 一律不落盘。
4. 备份不包含 token 明文（DB 本就存哈希）。
5. CORS 白名单显式配置；`/mcp` Origin 校验。

## 9. 测试策略

- 扩展 `tests/test_auth_tokens.py`：scope 矩阵（四值 × 方法 × capability）、旧 token 迁移映射、TTL 过期、撤销即时生效。
- 设备码：限速（5s 内重复 poll → slow_down）、user_code 一次性、deny 终止、过期。
- GitHub 流：mock 回调（最小映射落库、token 即弃断言、TTL 清理）。
- MCP：discovery 文档 schema、aud/scope 校验拒绝用例。

## 10. 待确认决策点

1. **个人实例是否保留密码登录为默认**（GitHub 仅 Demo 必需）？提案：是。
2. **scope 迁移策略**：旧 read/write token 自动映射，还是过期后重建？提案：自动映射 + 下次轮换时提示升级。
3. **MCP authorization server**：第一版 PaperMind 自身（密码换 token），不接外部 IdP——确认。
4. **Demo token TTL**：提案 24h，可配置（`DEMO_SESSION_TTL_HOURS`）。

## 变更记录

- 2026-09-02：初版（A10）；现状盘点基于 packages/auth.py、token_auth.py、auth router 当前实现。
