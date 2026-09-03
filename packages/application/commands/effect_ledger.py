"""副作用账本（C9，设计③ §执行语义）

外部效果（邮件/provider call）与幂等去重的统一入口：
- `register_effect`：effect_key 幂等——已存在返回 (record, False)，不重复执行；
- handler 执行外部副作用前先 register，未登记才执行（DB 唯一约束兜底并发）；
- effect_key 约定：能力幂等键 + 效果类型（如 "mail:{date}:{recipient}:send"）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from packages.domain.ids import new_id

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from packages.domain.enums import EffectKind
    from packages.storage.models import TaskEffect


def register_effect(
    session: Session,
    *,
    effect_key: str,
    kind: EffectKind,
    task_id: str | None = None,
    payload: dict | None = None,
) -> tuple[TaskEffect | None, bool]:
    """登记效果；effect_key 已存在 → (既有记录, False)（去重，调用方跳过执行）"""
    from packages.storage.models import TaskEffect

    existing = session.query(TaskEffect).filter(TaskEffect.effect_key == effect_key).one_or_none()
    if existing is not None:
        return existing, False
    record = TaskEffect(
        id=new_id(),
        task_id=task_id,
        effect_key=effect_key,
        kind=kind,
        payload=payload or {},
    )
    session.add(record)
    session.flush()
    return record, True


def has_effect(session: Session, effect_key: str) -> bool:
    from packages.storage.models import TaskEffect

    record = session.query(TaskEffect).filter(TaskEffect.effect_key == effect_key).one_or_none()
    return record is not None
