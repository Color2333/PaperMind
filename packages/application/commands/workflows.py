"""代码化 Workflow 模板（C5，设计③ §Workflow 与 fan-out）

- Planner 是纯函数：`plan(job, existing_tasks) -> [TaskSpec]`，每轮调度增量展开；
- 模板在 WORKFLOW_TEMPLATES 注册（代码定义、状态持久化），支持顺序依赖、
  条件分支（按 payload）与 per-Paper fan-out；
- 幂等：Task 以 idempotency_key 去重（C2 仓储语义），重复 expand 不产生重复 Task；
- 部分成功：单篇 Task 失败不抹掉其他 Paper 的成功结果（父 Job 收敛在 C2
  recompute_job_status，partial 语义已落地）。

不建设通用可视化 DAG 平台（设计③风险项）；单篇失败是否继续由 workflow policy
（continue_on_failure，默认 True）决定。
"""

from __future__ import annotations

from collections.abc import Callable  # noqa: TC003 —— WORKFLOW_TEMPLATES 注解运行期引用
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from packages.application.commands.task_registry import get_spec
from packages.domain.enums import JobStatus

if TYPE_CHECKING:
    from packages.storage.models import DurableTask, Job


@dataclass
class TaskSpec:
    """Planner 产出的 Task 展开计划（幂等键由模板生成）"""

    capability: str
    input_ref: dict = field(default_factory=dict)
    depends_on: list[str] = field(
        default_factory=list
    )  # 依赖的 capability 名（展开期解析为 task id）
    seq: int = 0
    idempotency_key: str | None = None
    priority: int = 0
    timeout_s: int | None = None  # None = 用注册表默认
    max_attempts: int | None = None


# ---------- 模板：RunTopicResearch ----------


def plan_topic_research(job: Job, existing: list[DurableTask]) -> list[TaskSpec]:
    """RunTopicResearch：ResolveSubscription → FetchFeed → [Upsert×N] →
    [Download → (Skim ∥ Embed → ExtractClaims) × N]

    fan-out 按 paper_ids 展开；单篇链内顺序依赖，篇间无依赖（可并行）。
    """
    payload = job.payload or {}
    paper_ids: list[str] = payload.get("paper_ids") or []
    specs: list[TaskSpec] = []
    existing_keys = {t.idempotency_key for t in existing if t.idempotency_key}
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

    if payload.get("fetch_query"):
        _emit(
            TaskSpec(
                capability="fetch_feed",
                input_ref={"query": payload["fetch_query"], "max_results": len(paper_ids) or 20},
                idempotency_key=f"fetch:{job.id}",
                seq=seq,
            )
        )

    for i, pid in enumerate(paper_ids, 1):
        upsert_key = f"{job.id}:upsert:{pid}"
        if not _emit(
            TaskSpec(
                capability="upsert_paper",
                input_ref={"paper_id": pid},
                idempotency_key=upsert_key,
            )
        ):
            continue  # 该 Paper 链已展开过（重放安全）

        download_key = f"{job.id}:download:{pid}"
        _emit(
            TaskSpec(
                capability="download_source",
                input_ref={"paper_id": pid},
                idempotency_key=download_key,
                depends_on=["upsert_paper"],
            )
        )
        skim_key = f"{job.id}:skim:{pid}"
        _emit(
            TaskSpec(
                capability="skim_paper",
                input_ref={"paper_id": pid},
                idempotency_key=skim_key,
                depends_on=["download_source"],
            )
        )
        embed_key = f"{job.id}:embed:{pid}"
        _emit(
            TaskSpec(
                capability="embed_paper",
                input_ref={"paper_id": pid},
                idempotency_key=embed_key,
                depends_on=["upsert_paper"],
            )
        )
        # 条件分支示例：仅高分论文精读（payload 开关，默认关）
        if payload.get("deep_read"):
            _emit(
                TaskSpec(
                    capability="deep_read_paper",
                    input_ref={"paper_id": pid},
                    idempotency_key=f"{job.id}:deep:{pid}",
                    depends_on=["skim_paper"],
                )
            )
        _emit(
            TaskSpec(
                capability="extract_claims",
                input_ref={"paper_id": pid},
                idempotency_key=f"{job.id}:claims:{pid}",
                depends_on=["skim_paper"],
            )
        )
        del i

    return specs


# ---------- 模板：ProcessUnreadBatch ----------


def plan_batch(job: Job, existing: list[DurableTask]) -> list[TaskSpec]:
    """ProcessUnreadBatch：per-Paper fan-out 的 skim ∥ embed（对应旧 batch_jobs）"""
    payload = job.payload or {}
    paper_ids: list[str] = payload.get("paper_ids") or []
    kinds: list[str] = payload.get("kinds") or ["skim_paper", "embed_paper"]
    existing_keys = {t.idempotency_key for t in existing if t.idempotency_key}
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
    """BuildDailyBrief：构建简报 → （条件）发送邮件（manual_recovery）"""
    existing_keys = {t.idempotency_key for t in existing if t.idempotency_key}
    specs: list[TaskSpec] = []
    brief_key = f"{job.id}:build_brief"
    if brief_key not in existing_keys:
        existing_keys.add(brief_key)
        spec = get_spec("build_daily_brief")
        specs.append(
            TaskSpec(
                capability="build_daily_brief",
                input_ref=dict(job.payload or {}),
                idempotency_key=brief_key,
                seq=len(existing),
                timeout_s=spec.timeout_s,
                max_attempts=spec.max_attempts,
            )
        )
    # 条件分支：配置了收件人才追加发送 Task（依赖 build）
    if (job.payload or {}).get("recipient"):
        mail_key = f"{job.id}:send_mail"
        if mail_key not in existing_keys:
            spec = get_spec("send_brief_email")
            specs.append(
                TaskSpec(
                    capability="send_brief_email",
                    input_ref={"recipient": job.payload["recipient"]},
                    idempotency_key=mail_key,
                    depends_on=["build_daily_brief"],
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
    existing_keys = {t.idempotency_key for t in existing if t.idempotency_key}
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


WORKFLOW_TEMPLATES: dict[str, Callable[[Job, list[DurableTask]], list[TaskSpec]]] = {
    "RunTopicResearch": plan_topic_research,
    "ProcessUnreadBatch": plan_batch,
    "BuildDailyBrief": plan_daily_brief,
    "RunCitationSync": plan_citation_sync,
}


# ---------- 展开入口 ----------


def expand_job(session: Any, job_id: str) -> list[DurableTask]:
    """按模板展开 Job 的下一批 Task（幂等；重复调用不产生重复 Task）。

    depends_on 中的 capability 名在此解析为同 Job 内先行 Task 的 id。
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

    # capability → task id 映射（同 Job 内已存在 + 本轮新建），用于解析 depends_on
    cap_to_id: dict[str, str] = {}
    for t in existing:
        cap_to_id.setdefault(t.capability, t.id)

    task_repo = TaskRepository(session)
    created: list[DurableTask] = []
    for spec in specs:
        depends_ids = [cap_to_id[cap] for cap in spec.depends_on if cap in cap_to_id]
        task, created_flag = task_repo.add_task(
            job_id=job_id,
            capability=spec.capability,
            input_ref=spec.input_ref,
            idempotency_key=spec.idempotency_key,
            depends_on=depends_ids,
            seq=spec.seq,
            priority=spec.priority,
            resource_class=(get_spec(spec.capability).resource_class),
            timeout_s=spec.timeout_s if spec.timeout_s is not None else 600,
            max_attempts=spec.max_attempts if spec.max_attempts is not None else 3,
        )
        cap_to_id.setdefault(task.capability, task.id)
        if created_flag:
            created.append(task)
    return created


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
