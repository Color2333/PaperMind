# 设计①：Research State 最小数据契约

状态：**已确认**（2026-09-02 用户按提案采纳 §11 全部决策点；A5 完成，D1 已落地）

日期：2026-09-02

依据：[PaperMind 2026 形态与重构设计](./2026-09-02-papermind-2026-rearchitecture.md)（第三版）§3.1、§4.1–4.3、§4.7、Phase 3；[路线图](./2026-09-02-rearchitecture-roadmap.md) Stage D。

范围：定义 Phase 3 垂直切片所需的**最小**实体、字段、ID、状态机、事件与 provenance 契约。 Phase 2 的 `Job/Task/Attempt` 表**不在本契约内**，ResearchRun 仅以字符串引用与之衔接。

## 1. 设计原则与最小集边界

设计文档的风险清单明确要求"Claim ontology、置信度和关系类型只保留完成 Demo 所需的最小集合"。据此本契约做出以下取舍：

**做**：

- 七个实体：ResearchQuestion、SourceVersion、Claim、Evidence、ClaimRelation、ResearchEvent、ResearchRun。
- Claim 状态机（draft → pending_verification → confirmed / superseded / invalidated）与无证据不得 confirmed 的硬规则。
- 判断来源三分（author / papermind / user），内联为字段而非独立表。
- append-only 事件表，兼任 History 与 outbox（P0 只写不消费）。
- 证据坐标：page/section/figure/table/公式/数值 + 实验条件。

**不做**（显式推迟）：

- 不引入 W3C PROV RDF/语义网栈，只保持字段级映射能力（§7）。
- 不做数值置信度评分（ certainty 用枚举，不用浮点分数）。
- 不做多人并行判断（Judgment 内联，见 §4.3 取舍说明）。
- 不做多对多 question 归属（Claim 单值可空外键，P1 再评估）。
- 不回填历史数据；存量 `papers`/`analysis_reports` 原样保留（§9）。
- watch/通知的自动消费不进 P0（事件表预留 `processed_at`）。

## 2. 实体总览

```text
research_questions 1──n claims 1──n evidence n──1 source_versions n──1 papers（现有表，不改动）
                         │                                   ▲
                         ├──n claim_relations（subject/object 指向 claims）
                         └──provenance: run_id ──────► research_runs
                                                        └── 字符串引用 job_id / task_attempt / prompt_trace
research_events（append-only；记录上述全部聚合变更 = History + outbox）
```

| 实体 | 职责 | 主要写入方 |
| --- | --- | --- |
| research_questions | 聚合一个问题的当前研究状态 | 用户 / CreateResearchQuestion |
| source_versions | 论文的具体版本 + 内容校验值（事实层的"来源"） | ingest / watch / 版本检测 |
| claim | 一个可比较、可修订的最小研究判断 | 用户 / ResearchRun |
| evidence | 指向精确原文位置的证据 | ResearchRun / 用户 |
| claim_relations | Claim 间关系（支持/反驳/取代…） | ResearchRun / 用户 |
| research_events | 全部状态变化的 append-only 记录 | 与聚合变更同事务 |
| research_runs | 一次研究活动的输入/模型/成本/产物（provenance 锚点） | application command |

## 3. ID 与标识策略

- 所有新表主键：**UUIDv7 的 32 位 hex 字符串**（`String(32)`，与现有 `String(36)` hex 主键风格一致）。选 UUIDv7 因为按时间有序——分页、diff、事件排序不再依赖第二排序键，也避免 UUIDv4 导致的索引写放大。
- 外部标识（`arxiv_id`、`doi`、arXiv 版本号 `v2`）不作为任何主键，只作为 source_versions/papers 上的索引列；外部系统的版本漂移不污染内部 ID。
- Evidence 幂等：`fingerprint = sha256(source_version_id + kind + locator_json + quote)`，唯一约束。同一 Attempt 重放不会产生重复证据行（对应设计文档"至少一次执行 + 幂等副作用"）。
- 现有表 `papers.id` 保持不变；SourceVersion 通过外键挂接。

## 4. 字段契约

类型写法兼容 SQLite/PG：JSON 列统一走现有 `JSONB_or_JSON()` 工厂；时间统一 UTC `DateTime`；枚举用 Python `StrEnum` + SQLAlchemy `Enum`（与 `ReadStatus` 同风格）。

### 4.1 research_questions

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK | |
| title | String(512) | 短标题 |
| question | Text | 完整问题表述 |
| status | enum {active, archived} | |
| watch_terms | JSON | `["audio-visual diarization", ...]`，P0 仅存储，watch 逻辑在 P1 |
| created_at / updated_at | DateTime | |

### 4.2 source_versions（新表；papers 不动）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK | |
| paper_id | String(36) FK→papers.id | 来源论文 |
| version_label | int | 内部版本号，1 起步 |
| external_version | String(32) nullable | 外部版本串，如 arXiv `v2` |
| doi | String(128) nullable | 该版本 DOI（如有） |
| content_hash | String(64) | PDF 或全文的 sha256，内容校验值 |
| file_path | String(1024) nullable | 该版本 PDF 路径；v1 可与 `papers.pdf_path` 同值 |
| origin_url | String(1024) nullable | 获取地址 |
| detected_by | enum {ingest, watch, manual} | 版本怎么来的 |
| fetched_at | DateTime | |
| is_current | bool | 当前有效版本；新版本入库时旧版置 False |
| created_at | DateTime | |

约束：`unique(paper_id, version_label)`；索引 `(paper_id, is_current)`。
入库规则：新论文 ingest 时自动创建 v1 并发 `SourceAdded` + `SourceVersionDetected` 事件；已有存量论文不回填，直到被垂直切片选中（§9）。

### 4.3 claims

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK | |
| research_question_id | String(32) FK nullable | 单值可空归属（取舍见下） |
| statement | Text | 判断正文（保留原语言） |
| statement_zh | Text nullable | 可选中文转述（与 skim 的 title_zh/abstract_zh 惯例一致） |
| origin | enum {author, papermind, user} | 判断来源三分 |
| status | enum {draft, pending_verification, confirmed, superseded, invalidated} | 见 §5 |
| certainty | enum {established, conditional, conflicted, insufficient_evidence, unknown} | 见 §6 |
| superseded_by_id | String(32) FK nullable | 被哪个新版本取代（便于"取当前版本"查询；关系细节仍在 relations/events） |
| run_id | String(32) FK nullable → research_runs.id | 由哪个 Run 产生（wasGeneratedBy） |
| user_note | Text nullable | 用户批注（user 判断的补充语境） |
| confirmed_at / confirmed_by | DateTime / String(128) nullable | 确认动作记录 |
| invalidated_reason | Text nullable | 失效原因必填于 invalidated |
| created_at / updated_at | DateTime | |

**取舍说明（Judgment 内联）**：设计文档把 Judgment 列为实体，但 P0 内每个 Claim 同一时刻只有一个有效判断来源，因此用 `origin` + `user_note` + 确认字段承载；用户覆盖 AI 判断时改写 `origin='user'` 并由事件记录原值。若 P1 出现"多条并行判断"需求，再升级为独立表，迁移路径是把这些字段平移过去。

### 4.4 evidence

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK | |
| claim_id | String(32) FK→claims.id | |
| source_version_id | String(32) FK→source_versions.id | **非空**——无版本的证据不成立 |
| kind | enum {text_passage, figure, table, formula, numeric_result, dataset} | |
| stance | enum {supports, contradicts, context} | 证据相对 Claim 的方向（复现失败的实验属于 contradicts） |
| locator | JSON | `{page, section, figure_no, table_no, eq_no, bbox, image_analysis_id}` 至少一项非空 |
| quote | Text nullable | 精确引用片段 |
| experiment_conditions | JSON nullable | `{dataset, metric, protocol, split, ...}`——跨论文比较不静默混合 protocol |
| extracted_by | enum {author, papermind, user} | 证据由谁提取 |
| run_id | String(32) FK nullable | |
| image_analysis_id | String(36) FK nullable | 复用现有 `image_analyses`（已有 page/bbox/caption） |
| fingerprint | String(64) unique | 见 §3 |
| created_at | DateTime | |

索引：`(claim_id)`、`(source_version_id)`。

### 4.5 claim_relations

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK | |
| subject_claim_id / object_claim_id | String(32) FK→claims.id | 方向：subject **对** object |
| predicate | enum {supports, partially_supports, contradicts, conditional, replication_failed, supersedes} | 枚举全集按 §4.1 定义；**P0 工作流只产生 supports / contradicts / supersedes**，其余值仅预留 |
| origin | enum {papermind, user} | 关系由谁断言 |
| run_id / note / created_at | | |

约束：`unique(subject, object, predicate)`；反向查询走 `(object)` 索引。

### 4.6 research_runs

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK | |
| kind | String(64) | `skim` / `deep_read` / `topic_research` / `daily_brief` / `claim_extraction` … |
| research_question_id | FK nullable | |
| trigger | enum {manual, watch, scheduler, api} | 为何执行 |
| paper_ids | JSON | 输入论文 |
| model_policy | JSON | `{provider, model_skim, model_deep, policy_version}` |
| status | enum {running, succeeded, failed, partial} | |
| started_at / finished_at | DateTime | |
| cost_refs | JSON | 引用现有 `prompt_traces.id` 列表（不复制成本数字，避免双写） |
| artifact_refs | JSON | `{analysis_report_id, export_path, …}` |
| job_ref | String(128) nullable | Phase 2 的 Job ID（**弱引用字符串，不建 FK**——执行层表归 Stage C 契约管） |
| attempt_refs | JSON nullable | Task/Attempt ID 列表，同上 |
| notes | Text nullable | |

### 4.7 research_events（History + outbox 合一）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | String(32) PK（UUIDv7） | 时间有序 |
| type | enum，见 §8 | |
| aggregate_type | enum {source, source_version, claim, evidence, relation, run} | |
| aggregate_id | String(32) | |
| actor | String(128) | `user` / `papermind:<model>` / `system` |
| run_id / job_ref / attempt_ref | nullable | provenance 衔接 |
| payload | JSON | 变更前后值、理由、引用的 evidence_ids 等 |
| occurred_at | DateTime | |
| processed_at | DateTime nullable | outbox 消费标记；P0 恒为 NULL |

**写入规则：与聚合变更同一数据库事务**（transactional outbox）。P0 没有消费者，表先承担 History/diff 事实源；P1 watch/通知从 `processed_at IS NULL` 拉取。

## 5. Claim 状态机

```text
                 ┌──────────────────────────────────────────────┐
                 │            （建立新版本 + supersedes）        ▼
  [创建] ──► draft ──► pending_verification ──► confirmed ──► superseded
    │           │              ▲                    │
    │           └──────────────┘                    └──────► invalidated
    └──（origin=user 直接进入 confirmed）
```

| 转换 | 触发者 | 前置条件（硬规则） | 事件 |
| --- | --- | --- | --- |
| 创建 → draft | papermind / user | papermind 必须带 `run_id`；无证据坐标时**只能**停在 draft | ClaimProposed |
| draft → pending_verification | 规则 | ≥1 evidence 且 locator 完整 | ClaimProposed（payload 含阶段） |
| draft/pending_verification → confirmed | user；或规则 | **≥1 evidence 且 source_version + locator 完整**；origin 规则见下 | ClaimConfirmed |
| confirmed → superseded | 规则 / user | 新版本 Claim 已建立且 relation(supersedes) 存在 | ClaimRevised |
| 任意 → invalidated | user / 规则（撤稿、复现失败） | `invalidated_reason` 必填 | ClaimInvalidated |

**origin × confirmed 规则**（P0 提案，待确认）：

- `author`：作者声称的内容。只要有一个坐标完整的 evidence，规则**可自动 confirmed**——因为 Claim 的语义是"作者在该版本声称 X"，由引用即证。
- `papermind`：模型推断。**任何情况下不能自动 confirmed**，最高 pending_verification；只有用户显式确认才 confirmed。
- `user`：用户自己写的判断，创建即可 confirmed。

这条规则是设计文档硬规则（"没有证据坐标的 AI 判断只能进入草稿或待验证状态"）的直接落地，并把"谁有权确认"收敛到一处。

## 6. 不确定性建模（certainty）

| 值 | 语义 | 典型设置时机 |
| --- | --- | --- |
| established | 当前证据一致支持 | confirm 时默认 |
| conditional | 仅在特定条件/数据集上成立 | LLM 输出或用户标记，需配 `experiment_conditions` |
| conflicted | 库内存在 contradicts 关系或相互矛盾证据 | P0 手动/P1 规则自动 |
| insufficient_evidence | 有指向但证据不足 | draft 阶段常见 |
| unknown | 无法判断 | 兜底，不强行生成确定答案 |

- `certainty` 是**枚举不是分数**：设计文档要求质量检查"可展开解释"，一个没有依据的 0.87 分数做不到这一点；理由放在事件 payload 与 evidence 明细里。
- 与 `status` 正交：`certainty` 说"证据多硬"，`status` 说"确认流程走到哪"。

## 7. Provenance 映射（PROV 对应，不引入 RDF）

| W3C PROV | PaperMind 落点 |
| --- | --- |
| Entity | SourceVersion、Claim、Evidence、Artifact（导出/简报文件） |
| Activity | ResearchRun（P0）；Job/Task/Attempt（Phase 2 起，经 `job_ref/attempt_refs` 字符串引用） |
| Agent | `user`；`papermind:<provider/model>`（模型与成本细节复用现有 `prompt_traces`） |
| used | ResearchRun → SourceVersion（`paper_ids`）、→ PromptTrace（`cost_refs`） |
| wasGeneratedBy | Claim/Evidence → ResearchRun（`run_id`）；Attempt 级归因进事件 payload（P2 起补） |
| wasDerivedFrom | Claim → Evidence → SourceVersion；ClaimRevised 事件 payload 记录旧 Claim ID |

## 8. 事件清单与 diff 语义

事件类型 = 设计文档 §4.7 清单 + `ClaimRelationRecorded`（冲突/取代 diff 需要它）：

| 事件 | aggregate | diff 呈现（`pm diff` / Demo 第二段） |
| --- | --- | --- |
| SourceAdded / SourceVersionDetected | source / source_version | 新来源 / 新版本 |
| EvidenceExtracted | evidence | ——（由 Claim 侧体现为 strengthen/weaken） |
| ClaimProposed | claim | 新增 |
| ClaimConfirmed | claim | 新增（确认） |
| ClaimRevised | claim | 修订（payload: old_statement/new_statement/supersedes） |
| ClaimInvalidated | claim | 失效（含原因） |
| ClaimRelationRecorded | relation | supports→加强；contradicts→冲突；supersedes→取代 |
| RetractionDetected | source | 撤稿（触发关联 Claim invalidated 流程） |
| ResearchRunCompleted / JobFailed | run | 运行结果；JobFailed 的权威定义在 Phase 2 job 契约 |

`DiffResearchState`（D4）= 按 question 聚合上述事件、按时间范围过滤、映射为"新增/加强/削弱/冲突/取代/失效"六类。事件表是唯一事实源，diff 不读内存、不重算语义。

## 9. 与现有 schema 的共存与迁移

| 现有对象 | 处置 |
| --- | --- |
| `papers` | 不改动。继续承担外部来源索引（arxiv_id/doi/source）、阅读状态、embedding 与检索 |
| `analysis_reports` | 保留为 legacy 产物；新 Run 可在 `artifact_refs` 引用，不迁移内容 |
| `pipeline_runs` | 保留为 legacy 执行记录；Phase 2 的 Attempt 表是它的收敛目标，本契约不处理 |
| `prompt_traces` | 保留；作为 Run 的成本 provenance 来源（`cost_refs`） |
| `citations` | 论文级引用图，与 claim_relations 互补，不合并 |
| `topic_subscriptions` | 旧聚合机制；新 research_questions 独立，不迁移订阅 |

迁移策略：

1. **不回填**。存量论文在未被垂直切片选中前不产生 source_versions/claims。
2. 新导入路径（ingest）在建 Paper 的同一事务里创建 v1 SourceVersion + 两条事件——这一步在 D1/D2 落地，属于对现有 ingest 的增量修改。
3. A4 人工校验样本经一次性脚本写入（含 question、v1 版本、claims、evidence）。
4. Schema 变更：PG 走 alembic migration；SQLite 走 `Base.metadata.create_all`（现有测试路径）。
5. 落地顺序对应路线图 D1（建模+migration）→ D2（样本）→ D3（Run 生成待验证 Claim）→ D4（查询）→ D5（导出）→ D6（outbox 消费面）→ D7（confirmed 规则校验）。

## 10. 查询路径（对应 D4/D5 出口条件）

- `GetResearchQuestion`：question + 按 status/certainty 聚合的 claim 计数（`claims` 单表聚合）。
- `ListClaims`：`WHERE research_question_id=? AND status IN (...) ORDER BY id DESC`（UUIDv7 使 id 即时间序）。
- `GetClaimEvidence`：claim → evidence → source_version → papers，一跳 JOIN；locator/quote/条件全量返回。
- `DiffResearchState`：`research_events WHERE aggregate_id IN (question 的 claims) AND occurred_at BETWEEN ...`。
- `ExportResearchObject`：question + claims + evidence + relations + source_versions + 事件快照 → JSON（含 content_hash）+ Markdown。

## 11. 决策点（2026-09-02 已确认：1–5 全部按提案采纳）

1. **author-origin 自动 confirmed**：作者声称 + 坐标完整证据 → 规则自动确认。替代方案是全部经用户确认（更保守，但 Demo 三段式会少一个"系统自己把作者事实落地"的展示点）。
2. **单 question 归属**：Claim 单值可空外键。多问题共享同一 Claim（多对多）是否可以推迟到 P1？
3. **Claim 文本语言**：`statement` 保留原文语言 + `statement_zh` 可选。如果你希望 Claim 统一中文，提取工作流需要加一步转述（成本与失真）。
4. **certainty 默认值**：papermind 产生 draft 时默认 `insufficient_evidence`（保守），还是必须由 Run 显式给出？
5. **evidence 的用户核验标记**（verified_by/verified_at）：P0 就要，还是并入 P1 质量检查？

## 变更记录

- 2026-09-02：初版（A5）。
