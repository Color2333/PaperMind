"""代码化 Workflow 模板（C5，设计③ §Workflow 与 fan-out）

- Planner 是纯函数：`plan(job, existing_tasks) -> [TaskSpec]`，每轮调度增量展开；
- 模板在 WORKFLOW_TEMPLATES 注册（代码定义、状态持久化），支持顺序依赖、
  条件分支（按 payload）与 per-Paper fan-out；
- 幂等：Task 以 idempotency_key 去重（C2 仓储语义），重复 expand 不产生重复 Task；
- **依赖用 logical node key（= idempotency_key）解析**——第三轮 REVIEW 修复：
  capability 名在 per-Paper fan-out 中不唯一，用 capability 解析依赖会把
  第二篇的 download 错连到第一篇的 upsert；
- **失败传播**：前驱进入终态失败（failed/dead_letter/cancelled）时，下游
  queued Task 由 `skip_blocked_tasks()` 标记为 cancelled（last_error 注明
  skipped 原因）——Job 可确定收敛，partially_succeeded 可达；
- **输出绑定**：fetch/build 等上游 Task 的 result_ref 在下一轮 expand 时
  驱动 fan-out 与下游 input（fetch 候选 → upsert 链；build 简报 → send）。

不建设通用可视化 DAG 平台（设计③风险项）。
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable  # noqa: TC003 —— WORKFLOW_TEMPLATES 注解运行期引用
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from packages.application.commands.task_registry import get_spec
from packages.domain.enums import JobStatus, TaskStatus

if TYPE_CHECKING:
    from packages.storage.models import DurableTask, Job


@dataclass
class TaskSpec:
    """Planner 产出的 Task 展开计划

    - `idempotency_key` 同时是 **logical node key**：depends_on 引用它，
      expand 期解析为同 Job 内先行 Task 的 id（第三轮 REVIEW 修复）；
    - `depends_on` 不得使用 capability 名（per-Paper fan-out 下不唯一）。
    """

    capability: str
    input_ref: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)  # logical node key（= idempotency_key）
    seq: int = 0
    idempotency_key: str | None = None
    priority: int = 0
    timeout_s: int | None = None  # None = 用注册表默认
    max_attempts: int | None = None


def _existing_keys(existing: list[DurableTask]) -> set[str]:
    return {t.idempotency_key for t in existing if t.idempotency_key}


def _fetch_candidates(existing: list[DurableTask]) -> list[dict]:
    """读取 fetch_feed Task 的 result_ref（输出绑定：候选驱动 upsert fan-out）"""
    for t in existing:
        if t.capability == "fetch_feed":
            result = (t.input_ref or {}).get("result_ref")
            if not result:
                continue
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError:
                    continue
            items = result.get("papers") or result.get("items") or result.get("candidates") or []
            return [p for p in items if isinstance(p, dict) and p.get("arxiv_id")]
    return []


def _paper_brief_payload(existing: list[DurableTask]) -> dict:
    """读取 build_daily_brief Task 的 result_ref（输出绑定：邮件发送所需）"""
    for t in existing:
        if t.capability in ("build_daily_brief", "daily_brief_publish"):
            result = (t.input_ref or {}).get("result_ref") or {}
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError:
                    result = {}
            return result
    return {}


# ---------- 模板：RunTopicResearch ----------


def plan_topic_research(job: Job, existing: list[DurableTask]) -> list[TaskSpec]:
    """RunTopicResearch：FetchFeed →（候选绑定）→ [Upsert → Download →
    (Skim → ExtractClaims) ∥ Embed] × N

    fan-out 来源：payload.paper_ids（预置）优先；否则 fetch Task 的
    result_ref 候选（输出绑定）。单篇链内顺序依赖，篇间无依赖（可并行）。
    """
    payload = job.payload or {}
    specs: list[TaskSpec] = []
    existing_keys = _existing_keys(existing)
    seq = len(existing)

    def _emit(spec: TaskSpec) -> bool:
        """幂等键已存在则跳过；返回是否为新 Task"""
        if spec.idempotency_key and spec.idempotency_key in existing_keys:
            return False
        if spec.idempotency_key:
            existing_keys.add(spec.idempotency_key)
        spec.seq = seq + len(specs)
        specs.append(spec)
        return True

    fetch_key = f"{job.id}:fetch"
    has_fetch = bool(payload.get("fetch_query"))
    if has_fetch and fetch_key not in existing_keys:
        _emit(
            TaskSpec(
                capability="fetch_feed",
                input_ref={
                    "query": payload["fetch_query"],
                    "max_results": len(payload.get("paper_ids") or []) or 20,
                },
                idempotency_key=fetch_key,
            )
        )

    # fan-out 论文清单：预置 ids 优先；否则 fetch 候选（需 fetch 已有结果）
    paper_ids: list[dict | str] = [
        {"arxiv_id": p} if isinstance(p, str) else p for p in (payload.get("paper_ids") or [])
    ]
    if not paper_ids and has_fetch:
        paper_ids = _fetch_candidates(existing)

    for p in paper_ids:
        if isinstance(p, str):
            p = {"arxiv_id": p}
        arxiv_id = p.get("arxiv_id")
        if not arxiv_id:
            continue
        node = f"{job.id}"
        upsert_key = f"{node}:upsert:{arxiv_id}"
        if not _emit(
            TaskSpec(
                capability="upsert_paper",
                # upsert handler 需要论文元数据（PaperCreate 契约）；fetch 候选直接携带
                input_ref={
                    "arxiv_id": arxiv_id,
                    "title": p.get("title", ""),
                    "abstract": p.get("abstract", ""),
                    "metadata": p.get("metadata") or {},
                },
                idempotency_key=upsert_key,
                depends_on=[fetch_key] if has_fetch else [],
            )
        ):
            continue  # 该 Paper 链已展开过（重放安全）

        download_key = f"{node}:download:{arxiv_id}"
        _emit(
            TaskSpec(
                capability="download_source",
                input_ref={"arxiv_id": arxiv_id},
                idempotency_key=download_key,
                depends_on=[upsert_key],
            )
        )
        skim_key = f"{node}:skim:{arxiv_id}"
        _emit(
            TaskSpec(
                capability="skim_paper",
                input_ref={"paper_id": f"${{{upsert_key}:paper_id}}"},
                idempotency_key=skim_key,
                depends_on=[download_key],
            )
        )
        embed_key = f"{node}:embed:{arxiv_id}"
        _emit(
            TaskSpec(
                capability="embed_paper",
                input_ref={"paper_id": f"${{{upsert_key}:paper_id}}"},
                idempotency_key=embed_key,
                depends_on=[upsert_key],
            )
        )
        # 条件分支：仅高分论文精读（payload 开关，默认关）
        if payload.get("deep_read"):
            _emit(
                TaskSpec(
                    capability="deep_read_paper",
                    input_ref={"paper_id": f"${{{upsert_key}:paper_id}}"},
                    idempotency_key=f"{node}:deep:{arxiv_id}",
                    depends_on=[skim_key],
                )
            )
        _emit(
            TaskSpec(
                capability="extract_claims",
                input_ref={"paper_id": f"${{{upsert_key}:paper_id}}"},
                idempotency_key=f"{node}:claims:{arxiv_id}",
                depends_on=[skim_key],
            )
        )

    return specs


# ---------- 模板：ProcessUnreadBatch ----------


def plan_batch(job: Job, existing: list[DurableTask]) -> list[TaskSpec]:
    """ProcessUnreadBatch：per-Paper fan-out 的 skim ∥ embed（对应旧 batch_jobs）"""
    payload = job.payload or {}
    paper_ids: list[str] = payload.get("paper_ids") or []
    kinds: list[str] = payload.get("kinds") or ["skim_paper", "embed_paper"]
    existing_keys = _existing_keys(existing)
    specs: list[TaskSpec] = []

    for pid in paper_ids:
        for kind in kinds:
            key = f"{job.id}:{kind}:{pid}"
            if key in existing_keys:
                continue
            existing_keys.add(key)
            spec = get_spec(kind)
            specs.append(
                TaskSpec(
                    capability=kind,
                    input_ref={"paper_id": pid},
                    idempotency_key=key,
                    seq=len(existing) + len(specs),
                    timeout_s=spec.timeout_s,
                    max_attempts=spec.max_attempts,
                )
            )
    return specs


# ---------- 模板：BuildDailyBrief ----------


def plan_daily_brief(job: Job, existing: list[DurableTask]) -> list[TaskSpec]:
    """BuildDailyBrief：构建简报 → （条件）发送邮件（manual_recovery）

    输出绑定：send 的 recipient/html 从 build Task 的 result_ref 解析
    （result_ref 未就绪时不展开 send——下一轮 expand 再补）。
    """
    existing_keys = _existing_keys(existing)
    specs: list[TaskSpec] = []
    brief_key = f"{job.id}:build_brief"
    if brief_key not in existing_keys:
        existing_keys.add(brief_key)
        spec = get_spec("daily_brief_publish")
        specs.append(
            TaskSpec(
                capability="daily_brief_publish",
                input_ref=dict(job.payload or {}),
                idempotency_key=brief_key,
                seq=len(existing),
                timeout_s=spec.timeout_s,
                max_attempts=spec.max_attempts,
            )
        )
        return specs

    # 条件分支：配置了收件人才追加发送 Task（依赖 build 的 result）
    recipient = (job.payload or {}).get("recipient")
    if not recipient:
        return specs
    mail_key = f"{job.id}:send_mail"
    if mail_key in existing_keys:
        return specs
    built = _paper_brief_payload(existing)
    content_id = built.get("content_id") or built.get("saved_path")
    if not content_id:
        return specs  # build 未完成/无产物——等下一轮
    spec = get_spec("send_brief_email")
    specs.append(
        TaskSpec(
            capability="send_brief_email",
            input_ref={
                "recipient": recipient,
                "subject": built.get("title") or "PaperMind 每日简报",
                "content_id": str(content_id),
            },
            idempotency_key=mail_key,
            depends_on=[brief_key],
            seq=len(existing) + len(specs),
            timeout_s=spec.timeout_s,
            max_attempts=spec.max_attempts,
        )
    )
    return specs


# ---------- 模板：RunCitationSync（per-Paper fan-out）----------


def plan_citation_sync(job: Job, existing: list[DurableTask]) -> list[TaskSpec]:
    payload = job.payload or {}
    paper_ids: list[str] = payload.get("paper_ids") or []
    existing_keys = _existing_keys(existing)
    specs: list[TaskSpec] = []
    spec = get_spec("sync_citations_paper")
    for pid in paper_ids:
        key = f"{job.id}:cite:{pid}"
        if key in existing_keys:
            continue
        existing_keys.add(key)
        specs.append(
            TaskSpec(
                capability="sync_citations_paper",
                input_ref={"paper_id": pid, "limit": payload.get("limit", 8)},
                idempotency_key=key,
                seq=len(existing) + len(specs),
                timeout_s=spec.timeout_s,
                max_attempts=spec.max_attempts,
                priority=payload.get("priority", 0),
            )
        )
    return specs


logger = logging.getLogger(__name__)

WORKFLOW_TEMPLATES: dict[str, Callable[[Job, list[DurableTask]], list[TaskSpec]]] = {
    "RunTopicResearch": plan_topic_research,
    "ProcessUnreadBatch": plan_batch,
    "BuildDailyBrief": plan_daily_brief,
    "RunCitationSync": plan_citation_sync,
}


# ---------- 展开入口 ----------


def expand_due_workflow_jobs(session: Any, limit: int = 50) -> int:
    """对活跃工作流 Job 补展开（"任务完成后展开"调度钩子）。

    此前 expand_job 只在提交时执行一次——多阶段工作流（RunTopicResearch 的
    fetch→upsert→download→skim 链）后续阶段永远不 spawn。由 worker 调度
    循环周期性调用：对模板注册过的、处于 queued/running/partially_succeeded
    的 Job 逐个 expand（幂等，去重由 idempotency_key 保证）。

    返回本轮新展开的 Task 数。
    """
    from sqlalchemy import select

    from packages.storage.models import Job as DurableJob

    active = (
        JobStatus.running,
        JobStatus.queued,
        JobStatus.partially_succeeded,
    )
    jobs = (
        session.execute(
            select(DurableJob)
            .where(DurableJob.kind.in_(list(WORKFLOW_TEMPLATES)))
            .where(DurableJob.status.in_([j.value for j in active]))
            .order_by(DurableJob.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    created_total = 0
    for job in jobs:
        try:
            created = expand_job(session, job.id)
            created_total += len(created)
        except Exception:  # noqa: BLE001 — 单个 Job 展开失败不阻断其余
            logger.warning("expand_due_workflow_jobs: job %s 展开失败", job.id, exc_info=True)
    return created_total


def expand_job(session: Any, job_id: str) -> list[DurableTask]:
    """按模板展开 Job 的下一批 Task（幂等；重复调用不产生重复 Task）。

    - depends_on 中的 logical node key（= idempotency_key）解析为同 Job 内
      先行 Task 的 id（第三轮 REVIEW 修复：不再用 capability 名解析）；
    - 解析不到（上游本轮新建/尚未有结果）的依赖保留 key——由下一轮 expand 补；
      claim 语义保证未满足依赖不会被领取。
    """
    from packages.storage.repositories import JobRepository, TaskRepository

    job = JobRepository(session).get(job_id)
    planner = WORKFLOW_TEMPLATES.get(job.kind)
    if planner is None:
        raise ValueError(f"Job kind {job.kind} 没有注册 Workflow 模板")

    existing = TaskRepository(session).list_for_job(job_id)
    specs = planner(job, existing)
    if not specs:
        return []

    # logical node key（idempotency_key）→ task id 映射（同 Job 内）
    node_to_id: dict[str, str] = {t.idempotency_key: t.id for t in existing if t.idempotency_key}
    # 上游 result_ref（输出绑定源）：node_key → result dict
    node_results: dict[str, dict] = {}
    for t in existing:
        if t.idempotency_key:
            result = (t.input_ref or {}).get("result_ref")
            if isinstance(result, dict):
                node_results[t.idempotency_key] = result
            elif isinstance(result, str):
                with contextlib.suppress(ValueError):
                    node_results[t.idempotency_key] = json.loads(result)

    def _resolve_bound(value: Any) -> Any:
        """解析 input_ref 中的 `${node:field}` 占位符 → 上游 result_ref 字段。

        输出绑定的持久语义：绑定表达式随 Task 落库（input_ref 原样可审计），
        expand 期解析为具体值；上游未完成时保持占位符（本轮不创建该 Task，
        由下一轮 expand 补——claim 依赖语义同时挡住提前领取）。
        """
        if isinstance(value, str) and value.startswith("${") and ":}" in value:
            node_key, field_name = value[2:-1].split(":", 1)
            upstream = node_results.get(node_key) or {}
            resolved = upstream.get(field_name)
            if resolved is None:
                return None  # 绑定未就绪
            return resolved
        return value

    task_repo = TaskRepository(session)
    created: list[DurableTask] = []
    for spec in specs:
        # 绑定未就绪的 Task 本轮跳过（expand 幂等：下一轮补）
        resolved_input: dict = {}
        binding_pending = False
        for k, v in spec.input_ref.items():
            r = _resolve_bound(v)
            if r is None and isinstance(v, str) and v.startswith("${"):
                binding_pending = True
                break
            resolved_input[k] = r
        if binding_pending:
            continue
        if spec.depends_on and not all(key in node_to_id for key in spec.depends_on):
            continue  # 依赖的 Task 本轮尚未创建——下一轮补

        task, created_flag = task_repo.add_task(
            job_id=job_id,
            capability=spec.capability,
            input_ref=resolved_input,
            idempotency_key=spec.idempotency_key,
            depends_on=[node_to_id[key] for key in spec.depends_on if key in node_to_id],
            seq=spec.seq,
            priority=spec.priority,
            resource_class=(get_spec(spec.capability).resource_class),
            timeout_s=spec.timeout_s if spec.timeout_s is not None else 600,
            max_attempts=spec.max_attempts if spec.max_attempts is not None else 3,
        )
        node_to_id[spec.idempotency_key] = task.id
        if created_flag:
            created.append(task)
    return created


def skip_blocked_tasks(session: Any, job_id: str) -> list[str]:
    """失败传播（第三轮 REVIEW）：前驱进入终态失败（failed/dead_letter/
    cancelled）时，下游 queued Task 永不满足 claim 依赖——把它们标记为
    cancelled（last_error 注明 skipped 原因），Job 由 recompute 收敛，
    partially_succeeded 可达。返回被跳过的 task id。
    """
    from packages.storage.repositories import TaskRepository

    repo = TaskRepository(session)
    tasks = repo.list_for_job(job_id)
    by_id = {t.id: t for t in tasks}
    terminal_bad = {"failed", "dead_letter", "cancelled"}

    # 迭代传播：前驱失败 → 下游 cancelled → 下下游也失败
    changed = True
    skipped: list[str] = []
    blocked: set[str] = set()
    while changed:
        changed = False
        for t in tasks:
            if t.id in blocked or t.status != TaskStatus.queued:
                continue
            deps_failed = any(
                d in terminal_bad or d in blocked
                for d in (by_id[dep].status.value for dep in (t.depends_on or []) if dep in by_id)
            )
            if deps_failed or any(
                dep not in by_id and dep in blocked for dep in (t.depends_on or [])
            ):
                t.status = TaskStatus.cancelled
                t.last_error = "skipped: upstream dependency failed"
                blocked.add(t.id)
                skipped.append(t.id)
                changed = True
    if skipped:
        session.flush()
        # 触发 Job 收敛（第三轮 REVIEW：partially_succeeded/cancelled 可达）
        from packages.storage.repositories import JobRepository

        JobRepository(session).recompute_job_status(job_id)
    return skipped


def start_workflow_job(
    session: Any,
    *,
    kind: str,
    payload: dict | None = None,
    idempotency_key: str | None = None,
    research_run_id: str | None = None,
    created_by: str = "api",
) -> tuple[Any, list[DurableTask], bool]:
    """创建工作流 Job 并立即展开第一批 Task；返回 (job, created_tasks, created)"""
    from packages.storage.repositories import JobRepository

    job, created = JobRepository(session).create_job(
        kind=kind,
        payload=payload or {},
        idempotency_key=idempotency_key,
        research_run_id=research_run_id,
        created_by=created_by,
    )
    if not created:
        return job, [], False
    job.status = JobStatus.queued
    created_tasks = expand_job(session, job.id)
    return job, created_tasks, True
